"""Unit tests for POST /order (JSON), including rejection of the removed legacy GET path.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``app/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``app/CSC510_DB.db``.

``temp_db_path`` and ``app`` are session-scoped, so rows written by one test
persist for the rest of the run. Every test below therefore creates its own
user, restaurant and menu item under a name unique to that test rather than
reusing ``seed_minimal_data``.
"""
import json

import pytest
from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one
import ledger

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
        return ledger.wallet_balance(conn, usr_id)
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
    stored = json.loads(details)
    # Charges are stored as integer cents (M2), never float dollars.
    # 2 x $10.00 = $20.00 subtotal, 7.25% tax, $3.99 delivery, $1.49 service, $2.00 tip.
    assert stored["charges_cents"] == {
        "subtotal": 2000,
        "tax": 145,
        "delivery_fee": 399,
        "service_fee": 149,
        "tip": 200,
        "total": 2893,
    }
    assert all(type(v) is int for v in stored["charges_cents"].values())
    assert "charges" not in stored
    assert stored["items"][0]["unit_price_cents"] == 1000
    assert stored["items"][0]["line_total_cents"] == 2000
    assert _wallet_cents(temp_db_path, usr_id) == 10_000 - 2893
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 10_000 - 2893


# This proves a valid JSON order computes tax and fees as documented, writes an "Ordered" row, and debits the wallet by exactly the charged total.


def test_a_negative_tip_is_rejected_and_leaves_the_wallet_untouched(client, temp_db_path):
    """A negative tip used to drive ``total`` below zero, pass the affordability
    guard, and credit the wallet via ``SET wallet = wallet - ?``. It must now be
    rejected before any charge is computed.
    """
    usr_id = _make_user(temp_db_path, "uc8-tip@example.test", wallet_cents=0)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Tip Cafe", price_cents=1000)
    _login(client, "uc8-tip@example.test")

    response = client.post(
        "/order",
        json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id, "qty": 1}], "tip": -100},
    )

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "invalid_tip"}
    assert _latest_order(temp_db_path, usr_id) is None
    assert _wallet_cents(temp_db_path, usr_id) == 0


# This proves a negative tip is rejected with invalid_tip, no order is stored, and the wallet is not credited.


@pytest.mark.parametrize("tip", ["nan", "inf", "Infinity", "abc"])
def test_a_non_finite_or_non_numeric_tip_is_rejected(client, temp_db_path, tip):
    """``_dollars_to_cents`` swallows the error from ``int(nan)``/``int(inf)`` and
    returns 0, so a non-finite tip used to price the whole order at $0.00.
    """
    email = f"uc8-tip-{tip.lower()}@example.test"
    usr_id = _make_user(temp_db_path, email, wallet_cents=0)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, f"UC8 Tip {tip} Cafe", price_cents=1000)
    _login(client, email)

    response = client.post(
        "/order",
        json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id, "qty": 1}], "tip": tip},
    )

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "invalid_tip"}
    assert _latest_order(temp_db_path, usr_id) is None
    assert _wallet_cents(temp_db_path, usr_id) == 0


# This proves NaN, infinite and non-numeric tips are rejected instead of producing a free order.


def test_the_legacy_get_path_is_removed_and_places_no_order(client, temp_db_path):
    """The legacy GET branch inserted an "Ordered" row with no balance check and
    no debit. The route now only accepts POST.
    """
    usr_id = _make_user(temp_db_path, "uc8-legacy@example.test", wallet_cents=0)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Legacy Cafe", price_cents=1000)
    _login(client, "uc8-legacy@example.test")

    response = client.get(f"/order?itm_id={itm_id}&qty=3", follow_redirects=False)

    assert response.status_code == 405
    assert _latest_order(temp_db_path, usr_id) is None
    assert _wallet_cents(temp_db_path, usr_id) == 0


# This proves GET /order no longer places an unpaid order.


def test_a_non_json_post_is_rejected(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc8-form@example.test", wallet_cents=10_000)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Form Cafe", price_cents=1000)
    _login(client, "uc8-form@example.test")

    response = client.post("/order", data={"itm_id": itm_id, "qty": 1})

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "invalid_input"}
    assert _latest_order(temp_db_path, usr_id) is None


# This proves a form-encoded POST no longer falls through to the removed legacy path.


@pytest.mark.parametrize("bad_id", [0, -1, "abc", None])
def test_an_invalid_item_id_alongside_a_valid_one_is_rejected(client, temp_db_path, bad_id):
    """Validation used to drop non-positive ids, after which the charge loop looked
    them up in ``dbmap`` anyway and raised ``KeyError``. Any bad id must now reject
    the whole request.
    """
    email = f"uc8-mixed-{str(bad_id).lower()}@example.test"
    usr_id = _make_user(temp_db_path, email, wallet_cents=100_000)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, f"UC8 Mixed {bad_id} Cafe", price_cents=1000)
    _login(client, email)

    response = client.post(
        "/order",
        json={
            "restaurant_id": rtr_id,
            "items": [{"itm_id": itm_id, "qty": 1}, {"itm_id": bad_id, "qty": 1}],
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "invalid_item"}
    assert _latest_order(temp_db_path, usr_id) is None
    assert _wallet_cents(temp_db_path, usr_id) == 100_000


# This proves a payload mixing a valid item with a zero, negative, non-numeric or missing id returns invalid_item instead of crashing.


def test_a_stale_session_wallet_cannot_buy_an_order_the_database_balance_cannot_cover(client, temp_db_path):
    """The affordability check used to trust ``session['Wallet']``, and the guarded
    debit (``WHERE wallet >= ?``) silently matched zero rows while the order insert
    still committed -- so a stale session (e.g. funds spent on another device) got
    free food. The check now reads the database, and the debit must hit exactly one
    row or the whole transaction rolls back.
    """
    usr_id = _make_user(temp_db_path, "uc8-stale@example.test", wallet_cents=0)
    rtr_id, itm_id = _make_restaurant_with_item(temp_db_path, "UC8 Stale Cafe", price_cents=1000)
    _login(client, "uc8-stale@example.test")
    with client.session_transaction() as sess:
        sess["Wallet"] = 100_000

    response = client.post(
        "/order",
        json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id, "qty": 1}]},
    )

    assert response.status_code == 402
    assert response.get_json() == {"ok": False, "error": "insufficient_funds"}
    assert _latest_order(temp_db_path, usr_id) is None
    assert _wallet_cents(temp_db_path, usr_id) == 0
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 0


# This proves an order is charged against the database balance, not a stale session copy, and the session is corrected.
