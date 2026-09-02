"""Unit tests for POST /order (JSON) and the legacy GET /order path.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``proj2/CSC510_DB.db``.

``temp_db_path`` and ``app`` are session-scoped, so rows written by one test
persist for the rest of the run. Every test below therefore creates its own
user, restaurant and menu item under a name unique to that test rather than
reusing ``seed_minimal_data``.

Flask's test client is configured with ``TESTING = True`` (set in the ``app``
fixture), so an unhandled exception in a view propagates to the caller instead
of being converted into an HTTP 500 -- the zero-item-id test below therefore
asserts a raised ``KeyError`` rather than a status code.
"""
import json

import pytest
from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


def _make_user(temp_db_path, email, wallet_cents=0):
    """Create a user with a known password and starting wallet; return usr_id."""
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Uc8","Tester",?,"9195550100",?,?,"","")''',
            (email, generate_password_hash(PASSWORD), wallet_cents),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _make_restaurant_with_item(temp_db_path, name, price_cents=1000):
    """Create one restaurant and one menu item under it; return (rtr_id, itm_id)."""
    conn = create_connection(temp_db_path)
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
        itm_id = fetch_one(
            conn, 'SELECT itm_id FROM "MenuItem" WHERE rtr_id = ? ORDER BY itm_id DESC LIMIT 1', (rtr_id,)
        )[0]
        return rtr_id, itm_id
    finally:
        close_connection(conn)


def _wallet_cents(temp_db_path, usr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(conn, 'SELECT wallet FROM "User" WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)


def _latest_order(temp_db_path, usr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(
            conn,
            'SELECT ord_id, details, status FROM "Order" WHERE usr_id = ? ORDER BY ord_id DESC LIMIT 1',
            (usr_id,),
        )
    finally:
        close_connection(conn)


def _login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 302


def test_placing_a_json_order_debits_the_wallet_and_stores_the_computed_charges(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc8-happy@example.test", wallet_cents=10_000)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Happy Cafe", price_cents=1000)
    _login(client, "uc8-happy@example.test")

    response = client.post(
        "/order",
        json={
            "restaurant_id": rtr_id,
            "items": [{"itm_id": itm_id, "qty": 2}],
            "delivery_type": "delivery",
            "tip": 2.00,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert isinstance(body["ord_id"], int)

    ord_id, details, status = _latest_order(temp_db_path, usr_id)
    assert ord_id == body["ord_id"]
    assert status == "Ordered"
    charges = json.loads(details)["charges"]
    # 2 x $10.00 = $20.00 subtotal, 7.25% tax, $3.99 delivery, $1.49 service, $2.00 tip.
    assert charges == {
        "subtotal": 20.00,
        "tax": 1.45,
        "delivery_fee": 3.99,
        "service_fee": 1.49,
        "tip": 2.00,
        "total": 28.93,
    }
    assert _wallet_cents(temp_db_path, usr_id) == 10_000 - 2893
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 10_000 - 2893


# This proves a valid JSON order computes tax and fees as documented, writes an "Ordered" row, and debits the wallet by exactly the charged total.


def test_a_negative_tip_inverts_the_total_and_credits_the_wallet_instead_of_debiting_it(client, temp_db_path):
    """``tip`` is read straight from the payload with no lower bound:

        tip_dollars = _money(payload.get("tip") or 0)
        total = _money(subtotal + tax + delivery_fee + service_fee + tip_dollars)

    A large negative tip drives ``total`` below zero. The affordability guard
    is ``if user_wallet_cents < total_cents``, which a negative total always
    passes, and the debit is ``SET wallet = wallet - ?``, so subtracting a
    negative number pays the user.
    """
    usr_id = _make_user(temp_db_path, "uc8-tip@example.test", wallet_cents=0)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Tip Cafe", price_cents=1000)
    _login(client, "uc8-tip@example.test")

    response = client.post(
        "/order",
        json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id, "qty": 1}], "tip": -100},
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    # $10.00 + $0.73 tax + $3.99 + $1.49 - $100.00 = -$83.79
    _, details, _ = _latest_order(temp_db_path, usr_id)
    assert json.loads(details)["charges"]["total"] == -83.79
    assert _wallet_cents(temp_db_path, usr_id) == 8379
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 8379


# This proves a negative tip is accepted unvalidated, produces a negative order total, and credits the user's wallet -- a real defect that lets an order mint money.


def test_the_legacy_get_path_places_an_order_with_no_wallet_check_and_no_debit(client, temp_db_path):
    """The POST/JSON branch checks funds and debits atomically. The legacy GET
    branch further down the same view does neither: it computes the same
    charges and runs a bare INSERT into "Order" with no balance check.
    """
    usr_id = _make_user(temp_db_path, "uc8-legacy@example.test", wallet_cents=0)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Legacy Cafe", price_cents=1000)
    _login(client, "uc8-legacy@example.test")

    response = client.get(f"/order?itm_id={itm_id}&qty=3", follow_redirects=False)

    assert response.status_code == 302
    assert "/profile?ordered=" in response.headers["Location"]
    ord_id, details, status = _latest_order(temp_db_path, usr_id)
    assert status == "Ordered"
    assert json.loads(details)["charges"]["total"] == 37.66
    assert _wallet_cents(temp_db_path, usr_id) == 0


# This proves a user with a $0.00 balance can place a $37.66 order through the legacy GET path, which skips both the insufficient_funds check and the wallet debit entirely -- a real defect.


def test_an_item_id_of_zero_alongside_a_valid_one_escapes_validation_and_raises_a_key_error(
    client, temp_db_path
):
    """Validation builds ``itm_ids`` from items with ``itm_id > 0``, so a
    zero id is dropped before the "does this item exist" checks run. The
    charge loop that follows iterates the *original* ``items_in`` list and
    does ``meta = dbmap[iid]``, so the id that validation discarded is looked
    up anyway and misses. That lookup sits outside the route's try/except.
    """
    _make_user(temp_db_path, "uc8-mixed@example.test", wallet_cents=100_000)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Mixed Cafe", price_cents=1000)
    _login(client, "uc8-mixed@example.test")

    with pytest.raises(KeyError):
        client.post(
            "/order",
            json={
                "restaurant_id": rtr_id,
                "items": [{"itm_id": itm_id, "qty": 1}, {"itm_id": 0, "qty": 1}],
            },
        )


# This proves a payload mixing one valid item with an itm_id of 0 slips past every validation branch and crashes on an unguarded dict lookup, rather than returning the no_items or item_not_found error the route defines -- a real defect.
