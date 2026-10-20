"""Regression tests for M2 bug 5: POST /order could return the wrong order ID.

After saving an order, the route looked its ID up as "this user's newest
order" (``SELECT ord_id ... ORDER BY ord_id DESC LIMIT 1``) instead of using
the ID SQLite gave the row it had just inserted (``cursor.lastrowid``). If the
same user placed another order in between (a second tab, a double click), the
first request returned the second order's ID, and the receipt link pointed at
the wrong order.
"""
import json
import threading

from werkzeug.security import generate_password_hash

import Flask_app
import ledger
from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


def _make_user(db, email, phone, wallet_cents):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Ord","Tester",?,?,?,?,"","")''',
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


def _order_row(db, ord_id):
    conn = create_connection(db)
    try:
        return fetch_one(conn, 'SELECT usr_id, rtr_id, details FROM "Order" WHERE ord_id = ?', (ord_id,))
    finally:
        close_connection(conn)


def _login(c, email):
    assert c.post("/login", data={"email": email, "password": PASSWORD}).status_code == 302


def _order(c, rtr_id, itm_id):
    return c.post("/order", json={
        "restaurant_id": rtr_id,
        "items": [{"itm_id": itm_id, "qty": 1}],
        "delivery_type": "pickup",
    })


def test_order_id_belongs_to_the_order_just_placed_even_if_another_lands_first(
    app, client, temp_db_path, monkeypatch
):
    buyer = _make_user(temp_db_path, "bug5-buyer@example.test", "9195559001", 10_000)
    rtr_a, itm_a = _make_item(temp_db_path, "Bug5 Cafe A")
    rtr_b, itm_b = _make_item(temp_db_path, "Bug5 Cafe B")
    _login(client, "bug5-buyer@example.test")
    second_tab = app.test_client()
    _login(second_tab, "bug5-buyer@example.test")

    # Right after the first order is saved, the same user's second tab places
    # another order before the first request has worked out its order ID.
    real_post = ledger.post_transaction
    state = {"second_id": None}

    def post_then_second_order(conn, kind, *args, **kwargs):
        result = real_post(conn, kind, *args, **kwargs)
        if kind == "order" and state["second_id"] is None:
            state["second_id"] = -1  # don't recurse into the second tab's own order
            state["second_id"] = _order(second_tab, rtr_b, itm_b).get_json()["ord_id"]
        return result

    monkeypatch.setattr(ledger, "post_transaction", post_then_second_order)

    first = _order(client, rtr_a, itm_a).get_json()

    assert first["ok"] is True
    assert state["second_id"] not in (None, -1)
    assert first["ord_id"] != state["second_id"]
    usr_id, rtr_id, details = _order_row(temp_db_path, first["ord_id"])
    assert (usr_id, rtr_id) == (buyer, rtr_a)
    assert json.loads(details)["restaurant_id"] == rtr_a


def test_concurrent_orders_each_get_their_own_id(app, temp_db_path):
    buyer = _make_user(temp_db_path, "bug5-many@example.test", "9195559010", 100_000)
    items = [_make_item(temp_db_path, f"Bug5 Many Cafe {i}") for i in range(6)]
    clients = [app.test_client() for _ in items]
    for c in clients:
        _login(c, "bug5-many@example.test")

    barrier = threading.Barrier(len(clients))
    results = {}

    def place(i, c, rtr_id, itm_id):
        barrier.wait()
        results[i] = _order(c, rtr_id, itm_id).get_json()

    threads = [threading.Thread(target=place, args=(i, c, *items[i])) for i, c in enumerate(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = [results[i]["ord_id"] for i in range(len(items))]
    assert all(results[i]["ok"] for i in range(len(items)))
    assert len(set(ids)) == len(ids)
    for i, (rtr_id, _) in enumerate(items):
        usr_id, row_rtr_id, _ = _order_row(temp_db_path, ids[i])
        assert (usr_id, row_rtr_id) == (buyer, rtr_id)


def test_transaction_helper_reports_the_id_of_the_inserted_row(tmp_path):
    conn = create_connection(str(tmp_path / "ids.db"))
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        conn.execute("INSERT INTO t (v) VALUES (1)")
        conn.commit()
        result = {}

        ok = Flask_app._execute_transaction(conn, [
            ("UPDATE t SET v = 2 WHERE id = 1", ()),
            ("INSERT INTO t (v) VALUES (3)", ()),
        ], result=result)

        assert ok is True
        assert result["lastrowid"] == 2
    finally:
        close_connection(conn)
