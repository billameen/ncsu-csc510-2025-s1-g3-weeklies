"""Regression tests for M2 bugs 2 and 3 in POST /order.

Bug 3 (stale session balance): ``/order`` checked ``session['Wallet']`` (the
balance cached at login) instead of the database, so money received after
login was invisible and a just-received gift still produced a 402.

Bug 2 (order without a debit): the debit is
``UPDATE ... SET wallet = wallet - ? WHERE usr_id = ? AND wallet >= ?``. When
the balance is too low that UPDATE matches 0 rows, which is not an error, so
the transaction committed and the order was saved without any money moving.
A stale-high session balance (bug 3) was enough to reach that path.

The second ``app.test_client()`` in these tests plays a second browser/device.
"""
import pytest
from werkzeug.security import generate_password_hash

import Flask_app
from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"

# Item price $10.00, pickup: $10.00 + $0.73 tax (7.25%) + $1.49 service fee.
PICKUP_TOTAL_CENTS = 1222


def _make_user(db, email, phone, wallet_cents):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Bug","Tester",?,?,?,?,"","")''',
            (email, phone, generate_password_hash(PASSWORD), wallet_cents),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _make_item(db, name):
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
               VALUES (?, ?, "test item", 1000, 100, 1, "")''',
            (rtr_id, name + " Plate"),
        )
        itm_id = fetch_one(conn, 'SELECT max(itm_id) FROM "MenuItem" WHERE rtr_id = ?', (rtr_id,))[0]
        return rtr_id, itm_id
    finally:
        close_connection(conn)


def _wallet(db, usr_id):
    conn = create_connection(db)
    try:
        return fetch_one(conn, 'SELECT wallet FROM "User" WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)


def _order_count(db, usr_id):
    conn = create_connection(db)
    try:
        return fetch_one(conn, 'SELECT count(*) FROM "Order" WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)


def _login(c, email):
    assert c.post("/login", data={"email": email, "password": PASSWORD}).status_code == 302


def _place_pickup_order(c, rtr_id, itm_id):
    return c.post("/order", json={
        "restaurant_id": rtr_id,
        "items": [{"itm_id": itm_id, "qty": 1}],
        "delivery_type": "pickup",
    })


# --- Bug 3: stale session balance -------------------------------------------

def test_a_gift_received_after_login_can_pay_for_an_order(app, client, temp_db_path):
    buyer = _make_user(temp_db_path, "bug3-buyer@example.test", "9195557001", 0)
    _make_user(temp_db_path, "bug3-friend@example.test", "9195557002", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Bug3 Cafe")
    _login(client, "bug3-buyer@example.test")  # session caches a $0.00 balance

    with app.test_client() as friend:
        _login(friend, "bug3-friend@example.test")
        resp = friend.post("/profile/wallet/gift", data={
            "recipient_email": "bug3-buyer@example.test", "amount": "50.00"})
        assert resp.headers["Location"] == "/profile?wallet_updated=gift"

    resp = _place_pickup_order(client, rtr_id, itm_id)

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["ok"] is True
    assert _wallet(temp_db_path, buyer) == 5000 - PICKUP_TOTAL_CENTS
    assert _order_count(temp_db_path, buyer) == 1


def test_session_balance_matches_the_database_after_an_order(app, client, temp_db_path):
    buyer = _make_user(temp_db_path, "bug3-sync@example.test", "9195557003", 0)
    rtr_id, itm_id = _make_item(temp_db_path, "Bug3 Sync Cafe")
    _login(client, "bug3-sync@example.test")
    with app.test_client() as other_device:  # same user tops up from another device
        _login(other_device, "bug3-sync@example.test")
        other_device.post("/profile/wallet/topup", data={"amount": "20.00"})

    assert _place_pickup_order(client, rtr_id, itm_id).status_code == 200

    with client.session_transaction() as sess:
        assert sess["Wallet"] == _wallet(temp_db_path, buyer) == 2000 - PICKUP_TOTAL_CENTS


# --- Bug 2: order saved without a debit -------------------------------------

def test_a_stale_high_session_balance_cannot_place_a_free_order(app, client, temp_db_path):
    buyer = _make_user(temp_db_path, "bug2-buyer@example.test", "9195557011", 5000)
    _make_user(temp_db_path, "bug2-friend@example.test", "9195557012", 0)
    rtr_id, itm_id = _make_item(temp_db_path, "Bug2 Cafe")
    _login(client, "bug2-buyer@example.test")  # session caches $50.00

    with app.test_client() as phone:  # same user gives the money away from another device
        _login(phone, "bug2-buyer@example.test")
        phone.post("/profile/wallet/gift", data={
            "recipient_email": "bug2-friend@example.test", "amount": "50.00"})
    assert _wallet(temp_db_path, buyer) == 0

    resp = _place_pickup_order(client, rtr_id, itm_id)

    assert resp.status_code == 402
    assert resp.get_json() == {"ok": False, "error": "insufficient_funds"}
    assert _order_count(temp_db_path, buyer) == 0
    assert _wallet(temp_db_path, buyer) == 0


def test_a_balance_spent_elsewhere_after_login_saves_no_order(client, temp_db_path):
    buyer = _make_user(temp_db_path, "bug2-direct@example.test", "9195557013", 5000)
    rtr_id, itm_id = _make_item(temp_db_path, "Bug2 Direct Cafe")
    _login(client, "bug2-direct@example.test")
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, 'UPDATE "User" SET wallet = 1000 WHERE usr_id = ?', (buyer,))
    finally:
        close_connection(conn)

    resp = _place_pickup_order(client, rtr_id, itm_id)

    assert resp.status_code == 402
    assert _order_count(temp_db_path, buyer) == 0
    assert _wallet(temp_db_path, buyer) == 1000
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 1000  # the session is corrected, not left stale


def test_exact_balance_is_enough(client, temp_db_path):
    buyer = _make_user(temp_db_path, "bug2-exact@example.test", "9195557014", PICKUP_TOTAL_CENTS)
    rtr_id, itm_id = _make_item(temp_db_path, "Bug2 Exact Cafe")
    _login(client, "bug2-exact@example.test")

    assert _place_pickup_order(client, rtr_id, itm_id).status_code == 200
    assert _wallet(temp_db_path, buyer) == 0
    assert _order_count(temp_db_path, buyer) == 1


# --- _execute_transaction: a guarded statement that changes nothing aborts ----

@pytest.fixture()
def scratch_conn(tmp_path):
    conn = create_connection(str(tmp_path / "tx.db"))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
    conn.execute("INSERT INTO t (id, v) VALUES (1, 5)")
    conn.commit()
    yield conn
    close_connection(conn)


def test_guarded_update_matching_no_rows_rolls_back_the_whole_transaction(scratch_conn):
    ok = Flask_app._execute_transaction(scratch_conn, [
        ("INSERT INTO t (id, v) VALUES (2, 0)", ()),
        Flask_app.require_rows("UPDATE t SET v = v - 10 WHERE id = 1 AND v >= 10", ()),
    ])

    assert ok is False
    assert scratch_conn.execute("SELECT id, v FROM t ORDER BY id").fetchall() == [(1, 5)]


def test_guarded_update_matching_a_row_commits(scratch_conn):
    ok = Flask_app._execute_transaction(scratch_conn, [
        Flask_app.require_rows("UPDATE t SET v = v - 5 WHERE id = 1 AND v >= 5", ()),
        ("INSERT INTO t (id, v) VALUES (2, 0)", ()),
    ])

    assert ok is True
    assert scratch_conn.execute("SELECT id, v FROM t ORDER BY id").fetchall() == [(1, 0), (2, 0)]


def test_unguarded_statements_keep_their_old_behaviour(scratch_conn):
    ok = Flask_app._execute_transaction(scratch_conn, [
        ("UPDATE t SET v = 99 WHERE id = 404", ()),
    ])
    assert ok is True
