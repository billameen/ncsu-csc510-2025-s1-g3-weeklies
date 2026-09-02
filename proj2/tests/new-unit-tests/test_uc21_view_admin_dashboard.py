import json
import os
import sys
from datetime import datetime, timedelta
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
    Assumption: Flask test client configured with testing mode and a consistent secret key.
    """
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_secret_key"
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_db_and_render(monkeypatch):
    """
    Assumption: Database helper functions (create_connection, close_connection, fetch_one, fetch_all)
    and render_template in Flask_app can be monkeypatched to inspect dashboard parameters and isolate unit testing.
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
        # Return only the body: the route itself appends the status code as a
        # (body, status) tuple on the error path, so returning a tuple here too
        # would double-wrap it into an invalid ((body, status), status) response.
        return f"Rendered {template_name}"

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


def test_admin_dashboard_unauthenticated_redirects_to_login(client):
    # Extension 2a: Unauthenticated visitor accessing /admin
    response = client.get("/admin")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
# This proves unauthenticated users attempting to access the admin dashboard are redirected to the login page.


def test_admin_dashboard_non_admin_returns_403_forbidden(client, mock_db_and_render):
    # Extension 2b: Authenticated user lacking administrator privileges
    with client.session_transaction() as sess:
        sess["Username"] = "Regular Customer"
        sess["is_admin"] = False

    response = client.get("/admin")
    assert response.status_code == 403

    ctx = mock_db_and_render["context"]
    assert ctx["template"] == "error.html"
    assert ctx["error"] == "Access Denied"
# This proves authenticated users without administrator privileges are rejected with an HTTP 403 Access Denied error.


def test_admin_dashboard_main_flow_kanban_and_tickets(client, mock_db_and_render):
    # Main Success Scenario: Admin viewing active orders from the last 7 days and paginated tickets
    recent_time_1 = (datetime.now() - timedelta(days=1)).isoformat()
    recent_time_2 = (datetime.now() - timedelta(days=3)).isoformat()
    old_time = (datetime.now() - timedelta(days=10)).isoformat()  # > 7 days ago

    recent_order_1 = json.dumps({
        "placed_at": recent_time_1,
        "charges": {"total": 28.50}
    })
    recent_order_2 = json.dumps({
        "placed_at": recent_time_2,
        "charges": {"total": 45.00}
    })
    old_order = json.dumps({
        "placed_at": old_time,
        "charges": {"total": 15.00}
    })

    # Order rows: (ord_id, rtr_id, usr_id, details, status, first_name, last_name, restaurant_name)
    order_rows = [
        (101, 1, 42, recent_order_1, "Ordered", "Alice", "Smith", "Tokyo Diner"),
        (102, 2, 43, recent_order_2, "Preparing", "Bob", "Jones", "Pasta Place"),
        (100, 1, 42, old_order, "Delivered", "Alice", "Smith", "Tokyo Diner"),  # Should be filtered out (>7 days)
    ]

    # Ticket count lookup: 25 total tickets
    mock_db_and_render["fetch_one"].return_value = (25,)

    # Ticket rows: (ticket_id, usr_id, ord_id, message, response, status, created_at, updated_at, first_name, last_name)
    ticket_created = (datetime.now() - timedelta(hours=2)).isoformat()
    ticket_rows = [
        (1, 42, 101, "Late delivery", None, "Open", ticket_created, ticket_created, "Alice", "Smith"),
        (2, 43, 102, "Missing drink", "Investigating", "In Progress", ticket_created, ticket_created, "Bob", "Jones"),
    ]

    mock_db_and_render["fetch_all"].side_effect = [
        order_rows,
        ticket_rows,
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get("/admin?page=1")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["template"] == "admin.html"
    assert ctx["current_page"] == 1
    assert ctx["total_pages"] == 2  # ceil(25 / 20)
    assert ctx["total_tickets"] == 25

    # Verify Kanban grouping and 7-day date filtering
    kanban = ctx["orders_by_status"]
    assert len(kanban["Ordered"]) == 1
    assert kanban["Ordered"][0]["ord_id"] == 101
    assert kanban["Ordered"][0]["customer_name"] == "Alice Smith"
    assert kanban["Ordered"][0]["total"] == "$28.50"

    assert len(kanban["Preparing"]) == 1
    assert kanban["Preparing"][0]["ord_id"] == 102

    # Old order (ord_id=100) must not appear in 'Delivered'
    assert len(kanban["Delivered"]) == 0

    # Verify support tickets processing
    tickets = ctx["tickets"]
    assert len(tickets) == 2
    assert tickets[0]["ticket_id"] == 1
    assert tickets[0]["customer_name"] == "Alice Smith"
    assert tickets[0]["status"] == "Open"
# This proves the admin dashboard groups active orders from the last 7 days into Kanban columns and paginates prioritized support tickets.


def test_admin_dashboard_missing_order_status_defaults_to_ordered(client, mock_db_and_render):
    # Extension 4b: Order record has empty/None status string
    recent_time = (datetime.now() - timedelta(days=1)).isoformat()
    order_details = json.dumps({"placed_at": recent_time, "charges": {"total": 19.99}})

    order_rows = [
        (105, 1, 42, order_details, None, "Alice", "Smith", "Tokyo Diner"),  # status is None
    ]

    mock_db_and_render["fetch_one"].return_value = (0,)
    mock_db_and_render["fetch_all"].side_effect = [
        order_rows,
        [],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get("/admin")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    kanban = ctx["orders_by_status"]
    # Verify that order with None status defaulted to 'Ordered'
    assert len(kanban["Ordered"]) == 1
    assert kanban["Ordered"][0]["ord_id"] == 105
    assert kanban["Ordered"][0]["status"] == "Ordered"
# This proves order records lacking a status attribute safely default to 'Ordered' in the Kanban board.


def test_admin_dashboard_corrupted_order_json_skipped_gracefully(client, mock_db_and_render):
    # Extension 4a: Order record contains malformed or unparseable JSON
    recent_time = (datetime.now() - timedelta(days=1)).isoformat()
    valid_details = json.dumps({"placed_at": recent_time, "charges": {"total": 22.00}})

    order_rows = [
        (106, 1, 42, "{invalid JSON", "Ordered", "Alice", "Smith", "Tokyo Diner"),
        (107, 1, 42, valid_details, "Ordered", "Alice", "Smith", "Tokyo Diner"),
    ]

    mock_db_and_render["fetch_one"].return_value = (0,)
    mock_db_and_render["fetch_all"].side_effect = [
        order_rows,
        [],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get("/admin")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    kanban = ctx["orders_by_status"]
    # Only the valid order should be parsed and added
    assert len(kanban["Ordered"]) == 1
    assert kanban["Ordered"][0]["ord_id"] == 107
# This proves malformed order details JSON strings are caught and skipped without crashing the dashboard.


@pytest.mark.parametrize("invalid_page", ["invalid", "abc", "-5", "0"])
def test_admin_dashboard_invalid_page_resets_to_one(client, mock_db_and_render, invalid_page):
    # Extension 3a: Non-integer or non-positive page query parameter
    mock_db_and_render["fetch_one"].return_value = (10,)
    mock_db_and_render["fetch_all"].side_effect = [
        [],  # Orders
        [],  # Tickets
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get(f"/admin?page={invalid_page}")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["current_page"] == 1
# This proves non-integer or negative page parameters are safely reset to page one.


def test_admin_dashboard_page_exceeding_total_pages_clamped(client, mock_db_and_render):
    # Extension 3a: Requested page exceeds total available pages (page=99 where total_tickets=25 -> 2 pages)
    mock_db_and_render["fetch_one"].return_value = (25,)
    mock_db_and_render["fetch_all"].side_effect = [
        [],  # Orders
        [],  # Tickets
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get("/admin?page=99")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["current_page"] == 2  # Clamped to total_pages (2)
# This proves requesting a ticket page number higher than total available pages is clamped to the maximum page number.


def test_admin_dashboard_zero_tickets_defaults(client, mock_db_and_render):
    # Boundary Case: Zero tickets in Ticket table
    mock_db_and_render["fetch_one"].return_value = (0,)
    mock_db_and_render["fetch_all"].side_effect = [
        [],  # Orders
        [],  # Tickets
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get("/admin")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    assert ctx["total_tickets"] == 0
    assert ctx["total_pages"] == 1
    assert ctx["current_page"] == 1
    assert ctx["tickets"] == []
# This proves an empty support ticket database initializes total pages to one and renders an empty ticket list without errors.


def test_admin_dashboard_database_connection_closed(client, mock_db_and_render):
    # Verification that the database connection is closed in the finally block
    mock_db_and_render["fetch_all"].side_effect = RuntimeError("SQLite database error")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    with pytest.raises(RuntimeError, match="SQLite database error"):
        client.get("/admin")

    assert mock_db_and_render["close_connection"].called
# This proves the database connection is guaranteed to be closed in the finally block even when exceptions occur.


def test_admin_dashboard_non_standard_order_status_not_dropped(client, mock_db_and_render):
    # Extension Not Handled #2:
    # Expected behavior: orders with statuses like 'Cancelled' or 'Refunded' should be surfaced
    # or categorized somewhere on the dashboard, not silently discarded.
    # Known defect: line 1353 tests `if status in orders_by_status:` where the dict only has
    # ['Ordered', 'Preparing', 'Delivering', 'Delivered'], silently dropping orders with status
    # 'Cancelled'. This test asserts the CORRECT behavior and will fail until non-standard
    # statuses are surfaced (e.g. their own Kanban column or a catch-all bucket).
    recent_time = (datetime.now() - timedelta(days=1)).isoformat()
    order_details = json.dumps({"placed_at": recent_time, "charges": {"total": 30.00}})

    order_rows = [
        (108, 1, 42, order_details, "Cancelled", "Alice", "Smith", "Tokyo Diner"),
    ]

    mock_db_and_render["fetch_one"].return_value = (0,)
    mock_db_and_render["fetch_all"].side_effect = [
        order_rows,
        [],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.get("/admin")
    assert response.status_code == 200

    ctx = mock_db_and_render["context"]
    kanban = ctx["orders_by_status"]
    all_order_ids = [order["ord_id"] for col in kanban.values() for order in col]
    assert 108 in all_order_ids
# This fails while the Cancelled order is silently dropped from every column; it passes once
# non-standard order statuses are surfaced somewhere on the Kanban board.