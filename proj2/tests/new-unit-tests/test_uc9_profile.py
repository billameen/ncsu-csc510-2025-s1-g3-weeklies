"""Unit tests for GET /profile (profile, order history, support tickets).

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``proj2/CSC510_DB.db``.

``temp_db_path`` and ``app`` are session-scoped, so each test creates its own
user and restaurant under a unique name rather than sharing
``seed_minimal_data``. The review-eligibility logic in the route is
per-restaurant, so tests that care about it use a restaurant of their own.
"""
import json
import re

from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"

# profile.html renders the review button as
#   class="... open-review-modal-btn"
#   data-order-id="{{ order.id }}"
# A second button on the same row ("report-issue-btn") also carries
# data-order-id, so the class name has to be part of the match.
REVIEW_BUTTON = re.compile(r'open-review-modal-btn"\s+data-order-id="(\d+)"')


def _make_user(temp_db_path, email):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Uc9","Tester",?,"9195550200",?,0,"","")''',
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
               VALUES (?, "2 Test Way", "Raleigh", "NC", "27606", "open")''',
            (name,),
        )
        return fetch_one(conn, 'SELECT rtr_id FROM "Restaurant" WHERE name = ?', (name,))[0]
    finally:
        close_connection(conn)


def _make_order(temp_db_path, rtr_id, usr_id, status, details):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            'INSERT INTO "Order"(rtr_id,usr_id,details,status) VALUES (?, ?, ?, ?)',
            (rtr_id, usr_id, details, status),
        )
        return fetch_one(conn, "SELECT last_insert_rowid()")[0]
    finally:
        close_connection(conn)


def _details(total, placed_at="2026-01-02T11:30:00-05:00"):
    return json.dumps({"placed_at": placed_at, "charges": {"total": total}})


def _login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 302


def test_viewing_the_profile_lists_the_users_orders_with_formatted_dates_and_totals(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc9-happy@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC9 Happy Diner")
    _make_order(temp_db_path, rtr_id, usr_id, "Ordered", _details(41.75))
    _login(client, "uc9-happy@example.test")

    response = client.get("/profile")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "UC9 Happy Diner" in page
    assert "$41.75" in page
    assert "2026-01-02 11:30" in page


# This proves an authenticated GET /profile renders 200 with the user's order history, its restaurant name, and its ISO timestamp and total reformatted for display.


def test_an_order_that_actually_reached_delivered_is_never_offered_a_review_button(client, temp_db_path):
    """The route names the flag ``is_delivered`` but compares against
    ``OrderStatus.ORDERED.get_lowercase()``:

        is_delivered = (status or "").lower() == OrderStatus.ORDERED.get_lowercase()

    so review eligibility keys on "Ordered", not "Delivered". Two separate
    restaurants are used because eligibility is also suppressed once any
    order from the same restaurant has claimed the review slot.
    """
    usr_id = _make_user(temp_db_path, "uc9-delivered@example.test")
    delivered_rtr = _make_restaurant(temp_db_path, "UC9 Delivered Diner")
    ordered_rtr = _make_restaurant(temp_db_path, "UC9 Ordered Diner")
    delivered_ord = _make_order(temp_db_path, delivered_rtr, usr_id, "Delivered", _details(25.00))
    ordered_ord = _make_order(temp_db_path, ordered_rtr, usr_id, "Ordered", _details(25.00))
    _login(client, "uc9-delivered@example.test")

    response = client.get("/profile")

    assert response.status_code == 200
    reviewable = REVIEW_BUTTON.findall(response.get_data(as_text=True))
    assert str(ordered_ord) in reviewable
    assert str(delivered_ord) not in reviewable


# This proves the only order a user can review is one that has merely been placed, while an order whose status actually reached "Delivered" is permanently locked out of reviewing -- the eligibility check is inverted against its own variable name, a real defect.


def test_an_order_whose_total_is_exactly_zero_renders_a_blank_total_cell(client, temp_db_path):
    """``_fmt_total`` is only reached when a truthy total survives:

        total_val = charges.get("total") or charges.get("grand_total") or charges.get("amount")

    A total of 0.0 is falsy, so the chain falls through to ``None`` and the
    template is handed an empty string instead of "$0.00".
    """
    usr_id = _make_user(temp_db_path, "uc9-zero@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC9 Zero Diner")
    _make_order(temp_db_path, rtr_id, usr_id, "Ordered", _details(0.0))
    _make_order(temp_db_path, rtr_id, usr_id, "Ordered", _details(12.34))
    _login(client, "uc9-zero@example.test")

    response = client.get("/profile")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "$12.34" in page
    assert "$0.00" not in page


# This proves a comped or fully-discounted $0.00 order shows an empty total instead of "$0.00", because the falsy-zero `or` chain treats a real total of zero as a missing value -- a real defect.


def test_an_unparseable_details_blob_is_swallowed_and_the_page_still_renders(client, temp_db_path):
    """The per-order parse is wrapped in ``try/except Exception: pass``, so
    corrupt JSON should degrade to blank date/total rather than 500.
    """
    usr_id = _make_user(temp_db_path, "uc9-junk@example.test")
    rtr_id = _make_restaurant(temp_db_path, "UC9 Junk Diner")
    _make_order(temp_db_path, rtr_id, usr_id, "Ordered", "{not valid json at all")
    _login(client, "uc9-junk@example.test")

    response = client.get("/profile")

    assert response.status_code == 200
    assert "UC9 Junk Diner" in response.get_data(as_text=True)


# This proves a corrupt details blob is contained by the route's broad except and the order still appears with an empty date and total, rather than taking the whole profile page down.
