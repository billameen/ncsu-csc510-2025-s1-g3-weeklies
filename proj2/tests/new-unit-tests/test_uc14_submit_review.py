"""Unit tests for POST /review/submit.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``proj2/CSC510_DB.db``.

Review eligibility is keyed on (usr_id, rtr_id), and ``temp_db_path`` is
session-scoped, so every test creates its own user and its own restaurant.
Sharing ``seed_minimal_data`` here would let one test's review block the next
one -- which is why the project's own duplicate-review and happy-path review
tests are commented out rather than passing.
"""
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


def test_submitting_a_review_for_a_placed_order_inserts_it_and_returns_201(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc14-happy@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC14 Happy Grill")
    ord_id = _make_order(temp_db_path, rtr_id, usr_id, "Ordered")
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
    first_ord = _make_order(temp_db_path, rtr_id, usr_id, "Ordered")
    second_ord = _make_order(temp_db_path, rtr_id, usr_id, "Ordered")
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


def test_an_order_that_actually_reached_delivered_is_refused_as_not_delivered(client, temp_db_path):
    """The comment above the guard says "Verify the order was actually
    delivered", but the comparison is against
    ``OrderStatus.ORDERED.get_lowercase()``, so it admits "Ordered" and
    rejects "Delivered". This is the write-side half of the same inversion
    that GET /profile shows on the read side.
    """
    usr_id = _make_user(temp_db_path, "uc14-delivered@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC14 Delivered Grill")
    ord_id = _make_order(temp_db_path, rtr_id, usr_id, "Delivered")
    _login(client, "uc14-delivered@example.test")

    response = client.post(
        "/review/submit",
        json={"restaurant_id": rtr_id, "order_id": ord_id, "rating": 5, "title": "A", "comment": "A"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Order not delivered or unauthorized"
    assert _reviews(temp_db_path, usr_id, rtr_id) == []


# This proves an order whose status is literally "Delivered" is refused with "Order not delivered", so the only reviewable state is the one the check was meant to exclude -- a real defect, and the mirror image of the profile-page finding.


def test_a_missing_rating_field_is_reported_as_a_500_server_error_instead_of_a_400(
    client, temp_db_path
):
    """Every field is coerced before any of them is checked::

        rating = int(data.get('rating'))

    A missing key yields ``int(None)``, which raises ``TypeError`` inside the
    route's blanket ``except Exception``. That handler answers 500 for what is
    a malformed client request, and the route's own 400 branch for an invalid
    rating is never reached.
    """
    usr_id = _make_user(temp_db_path, "uc14-missing@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC14 Missing Grill")
    ord_id = _make_order(temp_db_path, rtr_id, usr_id, "Ordered")
    _login(client, "uc14-missing@example.test")

    response = client.post(
        "/review/submit",
        json={"restaurant_id": rtr_id, "order_id": ord_id, "title": "A", "comment": "A"},
    )

    assert response.status_code == 500
    assert response.get_json()["error"] == "Server error during submission"
    assert _reviews(temp_db_path, usr_id, rtr_id) == []


# This proves a client-side omission is reported as a server fault: the blanket except turns a TypeError into HTTP 500 and hides the 400 the route defines for bad ratings -- a real defect.
