"""Unit tests for POST /review/submit.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``app/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``app/CSC510_DB.db``.

Review eligibility is keyed on (usr_id, rtr_id), and ``temp_db_path`` is
session-scoped, so every test creates its own user and its own restaurant.
Sharing ``seed_minimal_data`` here would let one test's review block the next
one -- which is why the project's own duplicate-review and happy-path review
tests are commented out rather than passing.
"""
import pytest
from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_all, fetch_one

PASSWORD = "secret123"


def _make_user(temp_db_path, email):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Uc14","Tester",?,"9195550700",?,0,"","")''',
            (email, generate_password_hash(PASSWORD)),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _make_restaurant(temp_db_path, name):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "Restaurant"(name,address,city,state,zip,status)
               VALUES (?, "3 Test Way", "Raleigh", "NC", "27606", "open")''',
            (name,),
        )
        return fetch_one(conn, 'SELECT rtr_id FROM "Restaurant" WHERE name = ?', (name,))[0]
    finally:
        close_connection(conn)


def _make_order(temp_db_path, rtr_id, usr_id, status):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            'INSERT INTO "Order"(rtr_id,usr_id,details,status) VALUES (?, ?, "{}", ?)',
            (rtr_id, usr_id, status),
        )
        return fetch_one(conn, "SELECT last_insert_rowid()")[0]
    finally:
        close_connection(conn)


def _reviews(temp_db_path, usr_id, rtr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_all(
            conn,
            'SELECT title, rating, description FROM "Review" WHERE usr_id = ? AND rtr_id = ?',
            (usr_id, rtr_id),
        )
    finally:
        close_connection(conn)


def _login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 302


def test_submitting_a_review_for_a_delivered_order_inserts_it_and_returns_201(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc14-happy@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC14 Happy Grill")
    ord_id = _make_order(temp_db_path, rtr_id, usr_id, "Delivered")
    _login(client, "uc14-happy@example.test")

    response = client.post(
        "/review/submit",
        json={
            "restaurant_id": rtr_id,
            "order_id": ord_id,
            "rating": 5,
            "title": "Great food",
            "comment": "Arrived hot.",
        },
    )

    assert response.status_code == 201
    assert response.get_json() == {"ok": True, "rtr_id": rtr_id}
    assert _reviews(temp_db_path, usr_id, rtr_id) == [("Great food", 5, "Arrived hot.")]


# This proves a review submitted against the user's own eligible order is persisted with its rating, title and comment intact and acknowledged with HTTP 201.


def test_a_second_review_for_the_same_restaurant_is_rejected_with_409(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc14-dupe@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC14 Dupe Grill")
    first_ord = _make_order(temp_db_path, rtr_id, usr_id, "Delivered")
    second_ord = _make_order(temp_db_path, rtr_id, usr_id, "Delivered")
    _login(client, "uc14-dupe@example.test")

    first = client.post(
        "/review/submit",
        json={"restaurant_id": rtr_id, "order_id": first_ord, "rating": 5, "title": "A", "comment": "A"},
    )
    assert first.status_code == 201

    second = client.post(
        "/review/submit",
        json={"restaurant_id": rtr_id, "order_id": second_ord, "rating": 1, "title": "B", "comment": "B"},
    )

    assert second.status_code == 409
    assert second.get_json()["error"] == "Restaurant already reviewed"
    assert len(_reviews(temp_db_path, usr_id, rtr_id)) == 1


# This proves the duplicate guard is per (user, restaurant) rather than per order: a second order from the same restaurant cannot be reviewed, and the first review is left untouched.


@pytest.mark.parametrize("status", ["Ordered", "Preparing", "Delivering"])
def test_an_order_that_has_not_been_delivered_is_refused_with_403(client, temp_db_path, status):
    """The guard used to compare against ``OrderStatus.ORDERED``, so it admitted
    "Ordered" and rejected "Delivered". Only delivered orders are reviewable now.
    """
    email = f"uc14-undelivered-{status.lower()}@example.test"
    usr_id = _make_user(temp_db_path, email)
    rtr_id = _make_restaurant(temp_db_path, f"UC14 Undelivered {status} Grill")
    ord_id = _make_order(temp_db_path, rtr_id, usr_id, status)
    _login(client, email)

    response = client.post(
        "/review/submit",
        json={"restaurant_id": rtr_id, "order_id": ord_id, "rating": 5, "title": "A", "comment": "A"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Order not delivered or unauthorized"
    assert _reviews(temp_db_path, usr_id, rtr_id) == []


# This proves orders that have been placed but not yet delivered cannot be reviewed.


@pytest.mark.parametrize(
    "drop,override",
    [
        ("rating", {}),
        ("restaurant_id", {}),
        ("order_id", {}),
        (None, {"rating": "five"}),
        (None, {"order_id": "abc"}),
        (None, {"rating": None}),
    ],
)
def test_a_missing_or_non_numeric_field_is_rejected_with_400(client, temp_db_path, drop, override):
    """Every field used to be coerced before any of them was checked, so
    ``int(None)`` raised ``TypeError`` inside the route's blanket ``except`` and
    a malformed client request was answered with 500.
    """
    tag = f"{drop}-{'-'.join(f'{k}{v}' for k, v in override.items())}".lower()
    email = f"uc14-bad-{tag}@example.test"
    usr_id = _make_user(temp_db_path, email)
    rtr_id = _make_restaurant(temp_db_path, f"UC14 Bad {tag} Grill")
    ord_id = _make_order(temp_db_path, rtr_id, usr_id, "Delivered")
    _login(client, email)

    payload = {"restaurant_id": rtr_id, "order_id": ord_id, "rating": 5, "title": "A", "comment": "A"}
    payload.pop(drop, None)
    payload.update(override)
    response = client.post("/review/submit", json=payload)

    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid rating or restaurant ID"
    assert _reviews(temp_db_path, usr_id, rtr_id) == []


# This proves a missing or non-numeric rating, restaurant_id or order_id is reported as a 400 client error before any DB work.


@pytest.mark.parametrize(
    "tag,kwargs",
    [
        ("form", {"data": "rating=5"}),
        ("malformed", {"data": "not json", "content_type": "application/json"}),
        ("list", {"json": [1, 2, 3]}),
    ],
)
def test_a_non_object_body_is_rejected_with_400(client, temp_db_path, tag, kwargs):
    _make_user(temp_db_path, f"uc14-body-{tag}@example.test")
    _login(client, f"uc14-body-{tag}@example.test")

    response = client.post("/review/submit", **kwargs)

    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid rating or restaurant ID"


# This proves a form-encoded, malformed or non-object JSON body is a 400 rather than a 500.
