import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Assumption: The Flask application module is located in 'proj2/Flask_app.py' or in the current directory.
# We ensure the module path is added to sys.path so 'Flask_app' can be imported in any test execution environment.
current_dir = Path(__file__).resolve().parent
candidates = [current_dir, current_dir / "proj2", current_dir.parent / "proj2"]
for candidate in candidates:
    if (candidate / "Flask_app.py").exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
        break

try:
    from Flask_app import app
except ImportError:
    # Fallback assumption if imported as package
    from proj2.Flask_app import app


@pytest.fixture
def client():
    """
    Assumption: Flask test client configured with testing mode and a constant secret key.
    """
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_secret_key"
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_db_and_render(monkeypatch):
    """
    Assumption: Database helper functions (create_connection, close_connection, fetch_one, fetch_all)
    and render_template in Flask_app can be monkeypatched to inspect template parameters and isolate unit testing.
    """
    mock_conn = MagicMock()
    mock_close = MagicMock()
    mock_create = MagicMock(return_value=mock_conn)
    mock_fetch_one = MagicMock()
    mock_fetch_all = MagicMock()
    rendered_context = {}

    import Flask_app

    def fake_render(template_name, **context):
        rendered_context["template"] = template_name
        rendered_context.update(context)
        return f"Rendered {template_name} for table {context.get('table')}"

    monkeypatch.setattr(Flask_app, "create_connection", mock_create)
    monkeypatch.setattr(Flask_app, "close_connection", mock_close)
    monkeypatch.setattr(Flask_app, "fetch_one", mock_fetch_one)
    monkeypatch.setattr(Flask_app, "fetch_all", mock_fetch_all)
    monkeypatch.setattr(Flask_app, "render_template", fake_render)

    return {
        "conn": mock_conn,
        "create_connection": mock_create,
        "close_connection": mock_close,
        "fetch_one": mock_fetch_one,
        "fetch_all": mock_fetch_all,
        "context": rendered_context,
    }


def test_db_view_unauthenticated_redirects_to_login(client):
    # Extension 2a: Unauthenticated visitor accessing /db
    response = client.get("/db")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
# This proves unauthenticated users attempting to access the database viewer are redirected to the login page.


def test_db_view_success_default_user_table(client, mock_db_and_render):
    # Main Flow: Logged-in user accessing /db with no query parameters
    # total_row count returns 25 records
    mock_db_and_render["fetch_one"].return_value = (25,)
    # PRAGMA table_info returns columns: [(cid, name, type, notnull, dflt_value, pk)]
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "usr_id"), (1, "first_name"), (2, "email")],  # PRAGMA columns
        [(1, "Alice", "alice@example.com"), (2, "Bob", "bob@example.com")],  # rows
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    response = client.get("/db")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["template"] == "db_view.html"
    assert ctx["table"] == "User"
    assert ctx["columns"] == ["usr_id", "first_name", "email"]
    assert len(ctx["rows"]) == 2
    assert ctx["page"] == 1
    assert ctx["pages"] == 3  # ceil(25 / 10)
    assert ctx["start"] == 1
    assert ctx["end"] == 10
    assert ctx["total"] == 25
    assert ctx["allowed"] == ["MenuItem", "Order", "Restaurant", "Review", "User"]
# This proves accessing the database viewer without table parameters defaults to the User table and renders the first page.


def test_db_view_success_pagination_calculations(client, mock_db_and_render):
    # Main Flow: Accessing second page of MenuItem table (?t=MenuItem&page=2)
    mock_db_and_render["fetch_one"].return_value = (25,)
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "itm_id"), (1, "name"), (2, "price")],
        [(11, "Item 11", 1000), (12, "Item 12", 1200)],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    response = client.get("/db?t=MenuItem&page=2")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["table"] == "MenuItem"
    assert ctx["page"] == 2
    assert ctx["pages"] == 3
    assert ctx["start"] == 11  # offset (10) + 1
    assert ctx["end"] == 20    # offset (10) + per_page (10)
    assert ctx["total"] == 25
# This proves requesting a specific table and page calculates accurate offset, start, end, and total page boundaries.


def test_db_view_unapproved_table_falls_back_to_user_table(client, mock_db_and_render):
    # Extension 3a: SQL injection attempt or unauthorized table request (?t=SecretTable)
    mock_db_and_render["fetch_one"].return_value = (10,)
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "usr_id"), (1, "email")],
        [(1, "user@example.com")],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    response = client.get('/db?t=SecretTable"; DROP TABLE User;--')
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["table"] == "User"  # Safely fell back to User
# This proves requesting an unapproved table name outside the whitelist safely defaults to the User table.


@pytest.mark.parametrize("invalid_page", ["invalid", "abc", "-5", "0"])
def test_db_view_invalid_page_resets_to_first_page(client, mock_db_and_render, invalid_page):
    # Extension 4a: Non-integer or non-positive page query parameter
    mock_db_and_render["fetch_one"].return_value = (15,)
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "ord_id"), (1, "status")],
        [(1, "Ordered")],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    response = client.get(f"/db?t=Order&page={invalid_page}")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["page"] == 1
    assert ctx["start"] == 1
    assert ctx["end"] == 10
# This proves non-integer or negative page parameters are safely handled and reset to page one.


def test_db_view_page_exceeding_total_pages_clamped_to_max(client, mock_db_and_render):
    # Extension 4b: Page parameter exceeds total available pages (page=99 with 25 items -> 3 pages)
    mock_db_and_render["fetch_one"].return_value = (25,)
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "rtr_id"), (1, "name")],
        [(21, "Rest 21"), (22, "Rest 22")],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    response = client.get("/db?t=Restaurant&page=99")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["page"] == 3  # Clamped to total_pages (3)
    assert ctx["start"] == 21
    assert ctx["end"] == 25  # min(offset + 10, total) -> min(30, 25) = 25
# This proves requesting a page number higher than total available pages is clamped to the last available page.


def test_db_view_empty_table_sets_zero_range(client, mock_db_and_render):
    # Extension 5a: Database table has zero records
    mock_db_and_render["fetch_one"].return_value = (0,)
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "rev_id"), (1, "rating")],  # Columns exist
        [],  # Zero rows
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    response = client.get("/db?t=Review")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["table"] == "Review"
    assert ctx["total"] == 0
    assert ctx["pages"] == 1
    assert ctx["page"] == 1
    assert ctx["start"] == 0
    assert ctx["end"] == 0
    assert ctx["rows"] == []
# This proves viewing an empty database table sets row display boundaries to zero without errors.


def test_db_view_ensures_connection_closed_on_error(client, mock_db_and_render):
    # Verification that the database connection closes even when an exception is raised
    mock_db_and_render["fetch_one"].side_effect = RuntimeError("SQLite query failure")

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    with pytest.raises(RuntimeError, match="SQLite query failure"):
        client.get("/db")

    assert mock_db_and_render["close_connection"].called
# This proves the database connection is guaranteed to be closed in the finally block even if database queries raise an exception.


def test_db_view_non_admin_customer_forbidden(client, mock_db_and_render):
    # Extension Not Handled #1:
    # Expected behavior: the database table viewer (/db) exposes raw user passwords and orders,
    # so it should be restricted to administrators (is_admin=True), returning 403 Forbidden for
    # standard customers.
    # Known defect: db_view() only checks session.get('Username') is None and does not check
    # is_admin, allowing any regular customer to inspect database tables. This test asserts the
    # CORRECT behavior and will fail (200 != 403) until an admin check is added to the route.
    mock_db_and_render["fetch_one"].return_value = (5,)
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "usr_id"), (1, "password_HS")],
        [(1, "hashed_pw_12345")],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Regular Customer"
        sess["is_admin"] = False  # Explicitly not an admin

    response = client.get("/db")
    assert response.status_code == 403
# This fails while non-admin customers are granted access (200); it passes once /db is
# restricted to administrators only.


def test_db_view_ticket_table_included_in_whitelist(client, mock_db_and_render):
    # Extension Not Handled #2:
    # Expected behavior: developers/admins should be able to inspect the 'Ticket' table in /db.
    # Known defect: allowed_tables hardcodes {'User', 'Restaurant', 'MenuItem', 'Order', 'Review'}
    # and omits 'Ticket', causing ?t=Ticket to silently fall back to 'User'. This test asserts
    # the CORRECT behavior and will fail until 'Ticket' is added to the whitelist.
    mock_db_and_render["fetch_one"].return_value = (5,)
    mock_db_and_render["fetch_all"].side_effect = [
        [(0, "ticket_id"), (1, "message")],
        [(1, "Order issue")],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get("/db?t=Ticket")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["table"] == "Ticket"
# This fails (table falls back to "User") while Ticket is missing from allowed_tables; it
# passes once Ticket is added to the whitelist.