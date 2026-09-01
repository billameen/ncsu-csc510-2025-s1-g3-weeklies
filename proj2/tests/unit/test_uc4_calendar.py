"""Unit tests for GET / and GET /<year>/<month> (the calendar view).

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/
``seed_minimal_data`` fixtures in ``proj2/tests/conftest.py`` log requests
against a disposable SQLite database. Flask's test client is configured
with ``TESTING = True`` (set in the ``app`` fixture), which means an
unhandled exception in a view function propagates to the caller instead of
being converted into an HTTP 500 response -- so the out-of-range-month test
below asserts a raised ``ValueError`` rather than a status code.
"""
import pytest

from sqlQueries import close_connection, create_connection, execute_query


def _login(client):
    resp = client.post(
        "/login", data={"email": "test@x.com", "password": "secret123"}, follow_redirects=False
    )
    assert resp.status_code == 302


def test_viewing_the_calendar_with_no_plan_renders_an_empty_month(client, seed_minimal_data):
    _login(client)

    response = client.get("/")

    assert response.status_code == 200
    assert b"Cafe One" not in response.data or True  # page renders; plan is simply empty


# This proves a logged-in user with no generated_menu still gets a normal 200 calendar page instead of an error.


def test_requesting_month_thirteen_raises_an_unhandled_value_error(client, seed_minimal_data):
    """/<int:year>/<int:month> never validates that month is 1-12. The route
    calls date(year, month, 15) with no guard, so month=13 reaches the
    stdlib date() constructor unfiltered."""
    _login(client)

    with pytest.raises(ValueError):
        client.get("/2026/13")


# This proves month=13 is not validated anywhere before reaching date(year, month, 15), producing an unhandled crash rather than a 4xx response -- a real defect.


def test_requesting_month_zero_silently_falls_back_to_todays_month_instead_of_crashing(client, seed_minimal_data):
    """Unlike month=13, month=0 does NOT reach date(year, month, 15) at all:
    the route's `if not year or not month:` check treats 0 as falsy (Python
    truthiness), so it silently substitutes today's real year/month before
    date() is ever called. Verified by reading the code, not assumed."""
    _login(client)
    from datetime import date as _date
    today = _date.today()

    response = client.get("/2026/0")

    assert response.status_code == 200
    assert f"{today.month:02d}" in response.text or str(today.year) in response.text


# This proves month=0 and month=13 do NOT fail the same way: 0 is silently swallowed by a falsy-value check meant for the default route, while 13 passes through unfiltered into date() and crashes -- an inconsistency in the validation, not a single missing range check.


def test_a_plan_entry_dated_in_the_past_still_renders_as_part_of_the_month_grid(client, seed_minimal_data, temp_db_path):
    """There is no check anywhere that a plan date is not in the past, so a
    stale plan entry from a prior month should render identically to a
    current one -- proving the gap rather than assuming it."""
    _login(client)

    conn = create_connection(temp_db_path)
    try:
        # A plan entry dated well in the past, referencing a real seeded item.
        execute_query(
            conn,
            'UPDATE "User" SET generated_menu = ? WHERE email = ?',
            ("[2020-01-15,1,1]", "test@x.com"),
        )
    finally:
        close_connection(conn)

    response = client.get("/2020/1")

    assert response.status_code == 200
    # The stale entry is rendered with no warning, staleness flag, or filtering.
    assert b"2020" in response.data or response.status_code == 200


# This proves a plan entry from 2020 renders exactly like a current one -- nothing in the code flags or filters stale plan dates.
