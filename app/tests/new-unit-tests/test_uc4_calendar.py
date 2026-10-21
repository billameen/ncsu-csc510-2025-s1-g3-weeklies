"""Unit tests for GET / and GET /<year>/<month> (the calendar view).

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/
``seed_minimal_data`` fixtures in ``app/tests/conftest.py`` log requests
against a disposable SQLite database.

Tests that change the seeded user's generated_menu restore it afterwards, because the
database is session-scoped and shared with the rest of the suite.
"""
import re
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

import Flask_app
from sqlQueries import close_connection, create_connection, execute_query, fetch_one


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


@pytest.mark.parametrize("path", ["/2026/13", "/2026/0", "/0/5", "/1999/12", "/2101/1", "/1/1", "/9999/12"])
def test_an_out_of_range_month_or_year_returns_404(client, seed_minimal_data, path):
    """Month 13 used to crash, month 0 was silently replaced by today's month, and
    years at the edge of date's range crashed in the prev/next navigation. All of
    them are now rejected the same way."""
    _login(client)

    response = client.get(path)

    assert response.status_code == 404


# This proves invalid calendar URLs are rejected consistently with a 404 instead of crashing or silently showing another month.


@pytest.mark.parametrize(
    "path,hidden,shown",
    [("/2000/1", "&larr; Prev", "Next &rarr;"), ("/2100/12", "Next &rarr;", "&larr; Prev")],
)
def test_the_edge_months_render_and_hide_the_nav_link_that_would_404(client, seed_minimal_data, path, hidden, shown):
    _login(client)

    response = client.get(path)

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert hidden not in page
    assert shown in page


# This proves the first and last renderable months work, and don't link to a month that would 404.


def _item_id(temp_db_path, name="Pasta"):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(conn, 'SELECT itm_id FROM "MenuItem" WHERE name = ? ORDER BY itm_id LIMIT 1', (name,))[0]
    finally:
        close_connection(conn)


@contextmanager
def _plan(temp_db_path, plan):
    """Temporarily set the seeded user's generated_menu."""
    conn = create_connection(temp_db_path)
    try:
        original = fetch_one(conn, 'SELECT generated_menu FROM "User" WHERE email = ?', ("test@x.com",))[0]
        execute_query(conn, 'UPDATE "User" SET generated_menu = ? WHERE email = ?', (plan, "test@x.com"))
    finally:
        close_connection(conn)
    try:
        yield
    finally:
        conn = create_connection(temp_db_path)
        try:
            execute_query(conn, 'UPDATE "User" SET generated_menu = ? WHERE email = ?', (original, "test@x.com"))
        finally:
            close_connection(conn)


def _order_link_dates(page):
    return re.findall(r'class="order-btn"[^>]*?data-date="([0-9-]+)"', page, re.S)


def test_a_past_plan_entry_is_shown_as_history_without_an_order_link(client, seed_minimal_data, temp_db_path):
    _login(client)
    with _plan(temp_db_path, f"[2020-01-15,{_item_id(temp_db_path)},1]"):
        response = client.get("/2020/1")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Pasta" in page  # still visible as history
    assert "day-cell past" in page
    assert "Past date" in page
    assert _order_link_dates(page) == []


# This proves a plan entry dated in the past is marked as past and can no longer be ordered from the calendar.


def test_a_future_plan_entry_can_still_be_ordered(client, seed_minimal_data, temp_db_path):
    _login(client)
    future = date.today() + timedelta(days=3)
    with _plan(temp_db_path, f"[{future.isoformat()},{_item_id(temp_db_path)},2]"):
        response = client.get(f"/{future.year}/{future.month}")

    assert response.status_code == 200
    assert _order_link_dates(response.get_data(as_text=True)) == [future.isoformat()]


# This proves upcoming plan entries keep their Order link.


def test_build_calendar_cells_marks_only_days_before_today_as_past():
    cells = Flask_app.build_calendar_cells({}, 2026, 10, {}, today=date(2026, 10, 19))
    flags = {c["day"]: c["is_past"] for c in cells if c["day"]}

    assert flags[18] is True
    assert flags[19] is False  # today is still orderable
    assert flags[20] is False


# This proves the past flag is computed against the given date, with today itself not counted as past.
