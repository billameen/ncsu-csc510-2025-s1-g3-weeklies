"""Double-click protection (idempotency keys) and refunds (M2).

Every money form and order page sends a one-time ``idempotency_key``. Sending
the same request again with the same key (a double-clicked "Pay", a re-posted
form) must change nothing. Refunds post a reversing ledger transaction; rows
are never edited or deleted.
"""
import json
import threading

from werkzeug.security import generate_password_hash

import ledger
from sqlQueries import close_connection, create_connection, execute_query, fetch_one
from wallet_helpers import wallet_cents

PASSWORD = "secret123"
KEY = "3f2b8c1e-aaaa-4bbb-8ccc-123456789abc"


def _make_user(db, email, phone, wallet_cents_in_old_column, is_admin=0):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies,is_admin)
               VALUES ("Idem","Potent",?,?,?,?,"","",?)''',
            (email, phone, generate_password_hash(PASSWORD), wallet_cents_in_old_column, is_admin),
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


def _q(db, sql, params=()):
    conn = create_connection(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        close_connection(conn)


def _order(c, rtr_id, itm_id, key=KEY, qty=1):
    return c.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id, "qty": qty}],
                                  "delivery_type": "pickup", "idempotency_key": key})


# --- Double-click protection --------------------------------------------------

def test_a_double_submitted_top_up_credits_once(client, temp_db_path):
    usr = _make_user(temp_db_path, "idem-topup@example.test", "9195554001", 0)
    _login(client, "idem-topup@example.test")

    for _ in range(2):
        resp = client.post("/profile/wallet/topup", data={"amount": "5.00", "idempotency_key": KEY})
        assert resp.headers["Location"] == "/profile?wallet_updated=topup"

    assert wallet_cents(temp_db_path, usr) == 500
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 500


def test_a_reused_top_up_key_with_a_different_amount_is_refused(client, temp_db_path):
    usr = _make_user(temp_db_path, "idem-topup2@example.test", "9195554002", 0)
    _login(client, "idem-topup2@example.test")
    client.post("/profile/wallet/topup", data={"amount": "5.00", "idempotency_key": KEY})

    resp = client.post("/profile/wallet/topup", data={"amount": "9.00", "idempotency_key": KEY})

    assert resp.headers["Location"] == "/profile?wallet_error=duplicate_request"
    assert wallet_cents(temp_db_path, usr) == 500


def test_a_double_submitted_gift_moves_money_once(client, temp_db_path):
    a = _make_user(temp_db_path, "idem-gift-a@example.test", "9195554003", 2000)
    b = _make_user(temp_db_path, "idem-gift-b@example.test", "9195554004", 0)
    _login(client, "idem-gift-a@example.test")

    for _ in range(3):
        resp = client.post("/profile/wallet/gift", data={
            "recipient_email": "idem-gift-b@example.test", "amount": "4.00", "idempotency_key": KEY})
        assert resp.headers["Location"] == "/profile?wallet_updated=gift"

    assert (wallet_cents(temp_db_path, a), wallet_cents(temp_db_path, b)) == (1600, 400)


def test_a_reused_gift_key_for_another_recipient_is_refused(client, temp_db_path):
    a = _make_user(temp_db_path, "idem-gift-c@example.test", "9195554005", 2000)
    _make_user(temp_db_path, "idem-gift-d@example.test", "9195554006", 0)
    _make_user(temp_db_path, "idem-gift-e@example.test", "9195554007", 0)
    _login(client, "idem-gift-c@example.test")
    client.post("/profile/wallet/gift", data={"recipient_email": "idem-gift-d@example.test",
                                              "amount": "4.00", "idempotency_key": KEY})

    resp = client.post("/profile/wallet/gift", data={"recipient_email": "idem-gift-e@example.test",
                                                     "amount": "4.00", "idempotency_key": KEY})

    assert resp.headers["Location"] == "/profile?wallet_error=duplicate_request"
    assert wallet_cents(temp_db_path, a) == 1600


def test_a_double_clicked_order_is_placed_and_charged_once(client, temp_db_path):
    usr = _make_user(temp_db_path, "idem-order@example.test", "9195554008", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Idem Order Cafe")
    _login(client, "idem-order@example.test")

    first = _order(client, rtr_id, itm_id).get_json()
    second = _order(client, rtr_id, itm_id).get_json()

    assert first["ok"] and second["ok"]
    assert first["ord_id"] == second["ord_id"]
    assert _q(temp_db_path, 'SELECT count(*) FROM "Order" WHERE usr_id = ?', (usr,)) == [(1,)]
    assert wallet_cents(temp_db_path, usr) == 5000 - 1222


def test_simultaneous_clicks_with_one_key_place_one_order(app, temp_db_path):
    usr = _make_user(temp_db_path, "idem-race@example.test", "9195554009", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Idem Race Cafe")
    clients = [app.test_client() for _ in range(5)]
    for c in clients:
        _login(c, "idem-race@example.test")
    barrier = threading.Barrier(len(clients))
    ids = []

    def click(c):
        barrier.wait()
        ids.append(_order(c, rtr_id, itm_id).get_json()["ord_id"])

    threads = [threading.Thread(target=click, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(ids)) == 1 and None not in ids
    assert _q(temp_db_path, 'SELECT count(*) FROM "Order" WHERE usr_id = ?', (usr,)) == [(1,)]
    assert wallet_cents(temp_db_path, usr) == 5000 - 1222


def test_a_reused_order_key_for_a_different_cart_is_refused(client, temp_db_path):
    usr = _make_user(temp_db_path, "idem-order2@example.test", "9195554010", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Idem Order2 Cafe")
    _login(client, "idem-order2@example.test")
    _order(client, rtr_id, itm_id)

    resp = _order(client, rtr_id, itm_id, qty=2)

    assert resp.status_code == 409
    assert resp.get_json() == {"ok": False, "error": "duplicate_request"}
    assert _q(temp_db_path, 'SELECT count(*) FROM "Order" WHERE usr_id = ?', (usr,)) == [(1,)]


def test_keys_are_private_to_each_user(app, client, temp_db_path):
    a = _make_user(temp_db_path, "idem-a@example.test", "9195554011", 0)
    b = _make_user(temp_db_path, "idem-b@example.test", "9195554012", 0)
    _login(client, "idem-a@example.test")
    client.post("/profile/wallet/topup", data={"amount": "5.00", "idempotency_key": KEY})
    with app.test_client() as other:
        _login(other, "idem-b@example.test")
        resp = other.post("/profile/wallet/topup", data={"amount": "7.00", "idempotency_key": KEY})

    assert resp.headers["Location"] == "/profile?wallet_updated=topup"
    assert (wallet_cents(temp_db_path, a), wallet_cents(temp_db_path, b)) == (500, 700)


def test_requests_without_a_valid_key_still_work(client, temp_db_path):
    usr = _make_user(temp_db_path, "idem-nokey@example.test", "9195554013", 0)
    _login(client, "idem-nokey@example.test")

    client.post("/profile/wallet/topup", data={"amount": "1.00"})
    client.post("/profile/wallet/topup", data={"amount": "1.00", "idempotency_key": "x"})        # too short
    client.post("/profile/wallet/topup", data={"amount": "1.00", "idempotency_key": "a b c d e f g h"})

    assert wallet_cents(temp_db_path, usr) == 300   # each was treated as a new request


def test_the_profile_page_gives_each_form_a_fresh_key(client, temp_db_path):
    _make_user(temp_db_path, "idem-page@example.test", "9195554014", 0)
    _login(client, "idem-page@example.test")

    import re
    keys_1 = re.findall(r'name="idempotency_key" value="([0-9a-f]{32})"', client.get("/profile").get_data(as_text=True))
    keys_2 = re.findall(r'name="idempotency_key" value="([0-9a-f]{32})"', client.get("/profile").get_data(as_text=True))

    assert len(keys_1) == 2 and len(set(keys_1)) == 2
    assert not set(keys_1) & set(keys_2)


# --- Refunds ------------------------------------------------------------------

def _admin(app, db, email, phone):
    _make_user(db, email, phone, 0, is_admin=1)
    c = app.test_client()
    _login(c, email)
    return c


def test_admin_refund_returns_everything_and_keeps_the_ledger_balanced(app, client, temp_db_path):
    usr = _make_user(temp_db_path, "refund-buyer@example.test", "9195554020", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Refund Cafe")
    _login(client, "refund-buyer@example.test")
    ord_id = client.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id}],
                                         "delivery_type": "delivery", "tip": 1.0}).get_json()["ord_id"]
    paid = 5000 - wallet_cents(temp_db_path, usr)
    admin = _admin(app, temp_db_path, "refund-admin@example.test", "9195554021")

    resp = admin.post(f"/admin/orders/{ord_id}/refund")

    body = resp.get_json()
    assert resp.status_code == 200 and body["ok"] is True
    assert body["refunded_cents"] == paid and body["already_refunded"] is False
    assert wallet_cents(temp_db_path, usr) == 5000
    assert _q(temp_db_path, 'SELECT reverses_txn_id IS NOT NULL, kind, memo FROM "LedgerTransaction" '
                            'WHERE txn_id = ?', (body["refund_txn_id"],)) == [
        (1, "refund", f"Refund for order #{ord_id}")]
    conn = create_connection(temp_db_path)
    try:
        assert ledger.balance(conn, ledger.restaurant_account(rtr_id)) == 0
        assert ledger.check_ledger(conn).ok
    finally:
        close_connection(conn)


def test_an_order_is_refunded_only_once(app, client, temp_db_path):
    usr = _make_user(temp_db_path, "refund-twice@example.test", "9195554022", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Refund Twice Cafe")
    _login(client, "refund-twice@example.test")
    ord_id = _order(client, rtr_id, itm_id, key="refund-twice-key-1").get_json()["ord_id"]
    admin = _admin(app, temp_db_path, "refund-admin2@example.test", "9195554023")

    first = admin.post(f"/admin/orders/{ord_id}/refund").get_json()
    second = admin.post(f"/admin/orders/{ord_id}/refund").get_json()

    assert second["ok"] and second["already_refunded"] is True
    assert second["refund_txn_id"] == first["refund_txn_id"]
    assert wallet_cents(temp_db_path, usr) == 5000


def test_refunds_are_admin_only(app, client, temp_db_path):
    _make_user(temp_db_path, "refund-sneaky@example.test", "9195554024", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Refund Sneaky Cafe")
    _login(client, "refund-sneaky@example.test")
    ord_id = _order(client, rtr_id, itm_id, key="refund-sneaky-key").get_json()["ord_id"]

    assert client.post(f"/admin/orders/{ord_id}/refund").status_code == 403
    with app.test_client() as anonymous:
        assert anonymous.post(f"/admin/orders/{ord_id}/refund").status_code == 401


def test_refund_errors(app, temp_db_path):
    usr = _make_user(temp_db_path, "refund-old@example.test", "9195554025", 0)
    conn = create_connection(temp_db_path)
    try:
        # An order placed before the ledger existed has no ledger transaction to reverse.
        execute_query(conn, 'INSERT INTO "Order"(rtr_id, usr_id, details, status) VALUES (1, ?, ?, ?)',
                      (usr, json.dumps({"charges": {"total": 12.5}}), "Ordered"))
        old_ord_id = fetch_one(conn, 'SELECT max(ord_id) FROM "Order"')[0]
    finally:
        close_connection(conn)
    admin = _admin(app, temp_db_path, "refund-admin3@example.test", "9195554026")

    missing = admin.post("/admin/orders/987654/refund")
    old = admin.post(f"/admin/orders/{old_ord_id}/refund")

    assert (missing.status_code, missing.get_json()["error"]) == (404, "order_not_found")
    assert (old.status_code, old.get_json()["error"]) == (409, "not_refundable")
