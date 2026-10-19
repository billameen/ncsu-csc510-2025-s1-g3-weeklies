"""Integration tests: top-ups, gifts and orders move money through the ledger (M2).

Since M2 a wallet balance is the sum of the user's ``LedgerEntry`` rows. The old
``User.wallet`` column is read exactly once per user, as an opening balance.
"""
import json

from werkzeug.security import generate_password_hash

import ledger
from sqlQueries import close_connection, create_connection, execute_query, fetch_one
from wallet_helpers import wallet_cents

PASSWORD = "secret123"


def _make_user(db, email, phone, wallet_cents_in_old_column):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Led","Ger",?,?,?,?,"","")''',
            (email, phone, generate_password_hash(PASSWORD), wallet_cents_in_old_column),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _make_item(db, name, price_cents=1000):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "Restaurant"(name,address,city,state,zip,status)
               VALUES (?, "1 Test Way", "Raleigh", "NC", "27606", "open")''',
            (name,),
        )
        rtr_id = fetch_one(conn, 'SELECT rtr_id FROM "Restaurant" WHERE name = ?', (name,))[0]
        execute_query(
            conn,
            '''INSERT INTO "MenuItem"(rtr_id,name,description,price,calories,instock,allergens)
               VALUES (?, ?, "test item", ?, 100, 1, "")''',
            (rtr_id, name + " Plate", price_cents),
        )
        itm_id = fetch_one(conn, 'SELECT max(itm_id) FROM "MenuItem" WHERE rtr_id = ?', (rtr_id,))[0]
        return rtr_id, itm_id
    finally:
        close_connection(conn)


def _login(c, email):
    assert c.post("/login", data={"email": email, "password": PASSWORD}).status_code == 302


def _ledger(db, fn, *args):
    conn = create_connection(db)
    try:
        return fn(conn, *args)
    finally:
        close_connection(conn)


def _entries(db, txn_id):
    return dict(_ledger(db, lambda c: c.execute(
        'SELECT account, amount_cents FROM "LedgerEntry" WHERE txn_id = ?', (txn_id,)).fetchall()))


def test_an_order_is_split_between_restaurant_tax_and_fees(client, temp_db_path):
    usr = _make_user(temp_db_path, "led-order@example.test", "9195556001", 10_000)
    rtr_id, itm_id = _make_item(temp_db_path, "Ledger Split Cafe")
    _login(client, "led-order@example.test")

    resp = client.post("/order", json={
        "restaurant_id": rtr_id, "items": [{"itm_id": itm_id, "qty": 2}],
        "delivery_type": "delivery", "tip": 2.00,
    })

    assert resp.status_code == 200
    ord_id = resp.get_json()["ord_id"]
    details = json.loads(_ledger(temp_db_path, lambda c: c.execute(
        'SELECT details FROM "Order" WHERE ord_id = ?', (ord_id,)).fetchone()[0]))
    # $20.00 food + $2.00 tip to the restaurant, $1.45 tax, $3.99 + $1.49 fees = $28.93
    assert _entries(temp_db_path, details["ledger_txn_id"]) == {
        f"user:{usr}": -2893,
        f"restaurant:{rtr_id}": 2200,
        "tax": 145,
        "fees:delivery": 399,
        "fees:service": 149,
    }
    assert wallet_cents(temp_db_path, usr) == 10_000 - 2893
    assert _ledger(temp_db_path, ledger.check_ledger).ok


def test_pickup_orders_have_no_delivery_fee_entry(client, temp_db_path):
    usr = _make_user(temp_db_path, "led-pickup@example.test", "9195556002", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Ledger Pickup Cafe")
    _login(client, "led-pickup@example.test")

    resp = client.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id}],
                                       "delivery_type": "pickup"})

    details = json.loads(_ledger(temp_db_path, lambda c: c.execute(
        'SELECT details FROM "Order" WHERE ord_id = ?', (resp.get_json()["ord_id"],)).fetchone()[0]))
    assert "fees:delivery" not in _entries(temp_db_path, details["ledger_txn_id"])
    assert wallet_cents(temp_db_path, usr) == 5000 - 1222


def test_a_refused_order_writes_nothing_to_the_ledger(client, temp_db_path):
    usr = _make_user(temp_db_path, "led-poor@example.test", "9195556003", 100)
    rtr_id, itm_id = _make_item(temp_db_path, "Ledger Poor Cafe")
    _login(client, "led-poor@example.test")
    txns_before = _ledger(temp_db_path, lambda c: c.execute(
        'SELECT count(*) FROM "LedgerTransaction"').fetchone()[0])

    resp = client.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id}]})

    assert resp.status_code == 402
    assert _ledger(temp_db_path, lambda c: c.execute(
        'SELECT count(*) FROM "LedgerTransaction"').fetchone()[0]) == txns_before
    assert _ledger(temp_db_path, lambda c: c.execute(
        'SELECT count(*) FROM "Order" WHERE usr_id = ?', (usr,)).fetchone()[0]) == 0


def test_the_old_wallet_column_becomes_an_opening_balance_exactly_once(app, client, temp_db_path):
    usr = _make_user(temp_db_path, "led-open@example.test", "9195556004", 4321)
    _login(client, "led-open@example.test")
    with app.test_client() as again:
        _login(again, "led-open@example.test")
    client.post("/profile/wallet/topup", data={"amount": "1.00"})

    # Later edits to the old column are ignored: the ledger is the only source.
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, 'UPDATE "User" SET wallet = 999999 WHERE usr_id = ?', (usr,))
    finally:
        close_connection(conn)

    assert wallet_cents(temp_db_path, usr) == 4321 + 100
    openings = _ledger(temp_db_path, lambda c: c.execute(
        '''SELECT count(*) FROM "LedgerTransaction" WHERE kind = 'opening_balance'
           AND idempotency_key = ?''', (ledger.opening_key(usr),)).fetchone()[0])
    assert openings == 1
    assert _ledger(temp_db_path, ledger.balance, ledger.OPENING_ACCOUNT) <= -4321


def test_a_user_with_an_empty_old_wallet_needs_no_opening_entry(client, temp_db_path):
    usr = _make_user(temp_db_path, "led-empty@example.test", "9195556005", 0)
    _login(client, "led-empty@example.test")

    assert _ledger(temp_db_path, ledger.open_legacy_wallet, usr) is None
    assert wallet_cents(temp_db_path, usr) == 0


def test_the_profile_page_shows_the_ledger_balance(client, temp_db_path):
    _make_user(temp_db_path, "led-profile@example.test", "9195556006", 1000)
    _login(client, "led-profile@example.test")
    client.post("/profile/wallet/topup", data={"amount": "2.34"})

    page = client.get("/profile").get_data(as_text=True)

    assert "$ 12.34" in page


def test_a_negative_tip_on_the_legacy_get_path_is_rejected(client, temp_db_path):
    usr = _make_user(temp_db_path, "led-legacy-tip@example.test", "9195556007", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Ledger Legacy Tip Cafe")
    _login(client, "led-legacy-tip@example.test")

    resp = client.get(f"/order?itm_id={itm_id}&tip=-100", follow_redirects=False)

    assert resp.status_code == 302 and "ordered=" not in resp.headers["Location"]
    assert wallet_cents(temp_db_path, usr) == 5000


def test_gift_memo_and_history_show_up_for_both_users(client, temp_db_path):
    a = _make_user(temp_db_path, "led-gift-a@example.test", "9195556008", 2000)
    b = _make_user(temp_db_path, "led-gift-b@example.test", "9195556009", 0)
    _login(client, "led-gift-a@example.test")

    client.post("/profile/wallet/gift", data={"recipient_email": "led-gift-b@example.test",
                                              "amount": "7.50"})

    a_hist = _ledger(temp_db_path, ledger.history, ledger.user_account(a))
    b_hist = _ledger(temp_db_path, ledger.history, ledger.user_account(b))
    assert a_hist[0]["amount_cents"] == -750 and b_hist[0]["amount_cents"] == 750
    assert a_hist[0]["memo"] == "Gift from led-gift-a@example.test to led-gift-b@example.test"
    assert [h["kind"] for h in a_hist] == ["gift", "opening_balance"]


def test_the_whole_ledger_still_balances_after_a_mix_of_requests(app, client, temp_db_path):
    _make_user(temp_db_path, "led-mix-a@example.test", "9195556010", 3000)
    _make_user(temp_db_path, "led-mix-b@example.test", "9195556011", 500)
    rtr_id, itm_id = _make_item(temp_db_path, "Ledger Mix Cafe")
    _login(client, "led-mix-a@example.test")
    client.post("/profile/wallet/topup", data={"amount": "10.00"})
    client.post("/profile/wallet/gift", data={"recipient_email": "led-mix-b@example.test", "amount": "12.00"})
    client.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id}]})
    client.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id, "qty": 9}]})  # too much
    with app.test_client() as b:
        _login(b, "led-mix-b@example.test")
        b.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id}],
                               "delivery_type": "pickup"})

    check = _ledger(temp_db_path, ledger.check_ledger)
    assert check.ok, check
