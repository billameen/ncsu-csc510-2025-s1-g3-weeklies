"""UI for the wallet ledger (M2): profile transaction history, refund badges,
the admin "ledger balanced" check and refund button, and ledger IDs on receipts."""
import json
import re

from werkzeug.security import generate_password_hash

import ledger
import pdf_receipt
from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


def _make_user(db, email, phone, old_wallet_cents, is_admin=0):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies,is_admin)
               VALUES ("Ui","Tester",?,?,?,?,"","",?)''',
            (email, phone, generate_password_hash(PASSWORD), old_wallet_cents, is_admin),
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


def _order(c, rtr_id, itm_id):
    return c.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id}],
                                  "delivery_type": "pickup"}).get_json()["ord_id"]


def _history_rows(html):
    section = html[html.index('id="walletHistory"'):]
    section = section[:section.index("</table>")] if "</table>" in section else section[:300]
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r)).strip()
            for r in re.findall(r"<tr>(.*?)</tr>", section, flags=re.S)[1:]]


def _admin_client(app, db, email, phone):
    _make_user(db, email, phone, 0, is_admin=1)
    c = app.test_client()
    _login(c, email)
    return c


def _card(html, ord_id):
    start = html.index(f'data-ord-id="{ord_id}"')
    nxt = html.find('class="order-card"', start)
    return html[start:nxt if nxt != -1 else start + 2000]


# --- Profile: transaction history ---------------------------------------------

def test_profile_lists_wallet_transactions_newest_first(app, client, temp_db_path):
    _make_user(temp_db_path, "ui-hist@example.test", "9195553001", 1000)
    _make_user(temp_db_path, "ui-hist-friend@example.test", "9195553002", 0)
    rtr_id, itm_id = _make_item(temp_db_path, "UI History Cafe")
    _login(client, "ui-hist@example.test")
    client.post("/profile/wallet/topup", data={"amount": "5.00"})
    client.post("/profile/wallet/gift", data={"recipient_email": "ui-hist-friend@example.test",
                                              "amount": "2.50"})
    _order(client, rtr_id, itm_id)

    rows = _history_rows(client.get("/profile").get_data(as_text=True))

    assert len(rows) == 4
    assert "Order at UI History Cafe" in rows[0] and "-$12.22" in rows[0]
    assert "Gift from ui-hist@example.test to ui-hist-friend@example.test" in rows[1] and "-$2.50" in rows[1]
    assert "Wallet top-up" in rows[2] and "+$5.00" in rows[2]
    assert "Opening balance" in rows[3] and "+$10.00" in rows[3]
    assert all(re.search(r"#\d+$", r) for r in rows)


def test_profile_without_transactions_says_so(client, temp_db_path):
    _make_user(temp_db_path, "ui-empty@example.test", "9195553003", 0)
    _login(client, "ui-empty@example.test")

    html = client.get("/profile").get_data(as_text=True)

    assert "Wallet History" in html and "No wallet transactions yet." in html


def test_the_recipient_sees_the_gift_as_money_in(app, client, temp_db_path):
    _make_user(temp_db_path, "ui-giver@example.test", "9195553004", 1000)
    _make_user(temp_db_path, "ui-receiver@example.test", "9195553005", 0)
    _login(client, "ui-giver@example.test")
    client.post("/profile/wallet/gift", data={"recipient_email": "ui-receiver@example.test", "amount": "3.00"})

    with app.test_client() as receiver:
        _login(receiver, "ui-receiver@example.test")
        rows = _history_rows(receiver.get("/profile").get_data(as_text=True))

    assert len(rows) == 1 and "+$3.00" in rows[0]


# --- Admin: ledger check and refunds ------------------------------------------

def test_admin_dashboard_shows_the_ledger_is_balanced(app, temp_db_path):
    admin = _admin_client(app, temp_db_path, "ui-admin1@example.test", "9195553010")

    html = admin.get("/admin").get_data(as_text=True)

    assert "Ledger balanced ✅" in html
    assert "Ledger NOT balanced" not in html


def test_admin_dashboard_flags_an_unbalanced_ledger(app, temp_db_path, monkeypatch):
    admin = _admin_client(app, temp_db_path, "ui-admin2@example.test", "9195553011")
    monkeypatch.setattr(ledger, "check_ledger",
                        lambda conn: ledger.LedgerCheck(-7, (42,), ("user:9",)))

    html = admin.get("/admin").get_data(as_text=True)

    assert "Ledger NOT balanced ❌" in html
    assert "unbalanced transactions: 42" in html and "negative wallets: user:9" in html
    assert "-$0.07" in html


def test_admin_can_refund_from_the_dashboard_and_the_badges_update(app, client, temp_db_path):
    _make_user(temp_db_path, "ui-refund@example.test", "9195553012", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "UI Refund Cafe")
    _login(client, "ui-refund@example.test")
    ord_id = _order(client, rtr_id, itm_id)
    admin = _admin_client(app, temp_db_path, "ui-admin3@example.test", "9195553013")

    before = _card(admin.get("/admin").get_data(as_text=True), ord_id)
    assert 'class="btn-refund"' in before

    assert admin.post(f"/admin/orders/{ord_id}/refund").get_json()["ok"]

    after = _card(admin.get("/admin").get_data(as_text=True), ord_id)
    assert 'class="btn-refund"' not in after and "Refunded" in after
    profile = client.get("/profile").get_data(as_text=True)
    assert "Refunded" in profile
    rows = _history_rows(profile)
    assert f"Refund for order #{ord_id}" in rows[0] and "+$12.22" in rows[0]


def test_a_cancelled_order_in_the_other_column_can_be_refunded(app, client, temp_db_path):
    _make_user(temp_db_path, "ui-cancel@example.test", "9195553016", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "UI Cancelled Cafe")
    _login(client, "ui-cancel@example.test")
    ord_id = _order(client, rtr_id, itm_id)
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, 'UPDATE "Order" SET status = ? WHERE ord_id = ?', ("Cancelled", ord_id))
    finally:
        close_connection(conn)
    admin = _admin_client(app, temp_db_path, "ui-admin5@example.test", "9195553017")

    html = admin.get("/admin").get_data(as_text=True)

    other = html[html.index('data-status="Other"'):]
    assert f'data-ord-id="{ord_id}"' in other
    assert 'class="btn-refund"' in _card(other, ord_id)


def test_orders_from_before_the_ledger_have_no_refund_button(app, temp_db_path):
    usr = _make_user(temp_db_path, "ui-old@example.test", "9195553014", 0)
    rtr_id, _ = _make_item(temp_db_path, "UI Old Order Cafe")
    from datetime import datetime
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, 'INSERT INTO "Order"(rtr_id, usr_id, details, status) VALUES (?, ?, ?, ?)',
                      (rtr_id, usr, json.dumps({"placed_at": datetime.now().isoformat(),
                                        "charges": {"total": 9.99}}), "Ordered"))
        old_id = fetch_one(conn, 'SELECT max(ord_id) FROM "Order"')[0]
    finally:
        close_connection(conn)
    admin = _admin_client(app, temp_db_path, "ui-admin4@example.test", "9195553015")

    html = admin.get("/admin").get_data(as_text=True)

    card = _card(html, old_id)
    assert "$9.99" in card
    assert 'class="btn-refund"' not in card and "Refunded" not in card


# --- Receipts -----------------------------------------------------------------

def test_receipt_lines_show_the_ledger_transaction_and_refund(app, client, temp_db_path):
    _make_user(temp_db_path, "ui-receipt@example.test", "9195553020", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "UI Receipt Cafe")
    _login(client, "ui-receipt@example.test")
    ord_id = _order(client, rtr_id, itm_id)
    conn = create_connection(temp_db_path)
    try:
        details = json.loads(fetch_one(conn, 'SELECT details FROM "Order" WHERE ord_id = ?', (ord_id,))[0])
        assert pdf_receipt.receipt_ledger_lines(conn, details) == [
            f"Ledger transaction #{details['ledger_txn_id']}"]

        refund_txn = ledger.reverse_transaction(conn, details["ledger_txn_id"], f"refund:order:{ord_id}").txn_id

        assert pdf_receipt.receipt_ledger_lines(conn, details) == [
            f"Ledger transaction #{details['ledger_txn_id']}",
            f"Refunded in full (ledger transaction #{refund_txn})",
        ]
        assert pdf_receipt.receipt_ledger_lines(conn, {"charges": {}}) == []
    finally:
        close_connection(conn)


def test_a_real_receipt_pdf_renders_for_a_ledger_order(client, temp_db_path):
    _make_user(temp_db_path, "ui-pdf@example.test", "9195553021", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "UI PDF Cafe")
    _login(client, "ui-pdf@example.test")
    ord_id = _order(client, rtr_id, itm_id)

    pdf = pdf_receipt.generate_order_receipt_pdf(temp_db_path, ord_id)

    assert pdf.startswith(b"%PDF") and len(pdf) > 1000
