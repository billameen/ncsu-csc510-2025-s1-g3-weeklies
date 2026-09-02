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
    Assumption: Flask test client configured with testing mode and a consistent secret key.
    """
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_secret_key"
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_db(monkeypatch):
    """
    Assumption: Database helper functions (create_connection, close_connection, fetch_one, execute_query)
    in Flask_app can be monkeypatched to isolate unit testing without an active SQLite database.
    """
    mock_conn = MagicMock()
    mock_close = MagicMock()
    mock_create = MagicMock(return_value=mock_conn)
    mock_fetch = MagicMock()
    mock_exec = MagicMock()

    import Flask_app

    monkeypatch.setattr(Flask_app, "create_connection", mock_create)
    monkeypatch.setattr(Flask_app, "close_connection", mock_close)
    monkeypatch.setattr(Flask_app, "fetch_one", mock_fetch)
    monkeypatch.setattr(Flask_app, "execute_query", mock_exec)

    return {
        "conn": mock_conn,
        "create_connection": mock_create,
        "close_connection": mock_close,
        "fetch_one": mock_fetch,
        "execute_query": mock_exec,
    }


def test_admin_update_ticket_status_unauthenticated(client):
    # Extension 2a: Unauthenticated visitor accessing endpoint
    response = client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 5, "new_status": "In Progress"},
    )
    assert response.status_code == 401
    data = response.get_json()
    assert data == {"ok": False, "error": "unauthorized"}
# This proves unauthenticated requests to update ticket status are rejected with HTTP 401 Unauthorized.


def test_admin_update_ticket_status_forbidden_for_non_admin(client):
    # Extension 2b: Logged in customer lacking administrator privileges
    with client.session_transaction() as sess:
        sess["Username"] = "Regular Customer"
        sess["is_admin"] = False

    response = client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 5, "new_status": "In Progress"},
    )
    assert response.status_code == 403
    data = response.get_json()
    assert data == {"ok": False, "error": "forbidden"}
# This proves authenticated users without administrator privileges are rejected with HTTP 403 Forbidden.


def test_admin_update_ticket_status_non_json_request(client):
    # Extension 3a: Request sent without JSON content-type
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_ticket_status",
        data={"ticket_id": "5", "new_status": "In Progress"},  # Form data
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data == {"ok": False, "error": "Request must be JSON"}
# This proves requests with non-JSON content types are rejected with HTTP 400 Bad Request.


@pytest.mark.parametrize("invalid_id", ["invalid_id", 0, -1, None])
def test_admin_update_ticket_status_invalid_ticket_id(client, invalid_id):
    # Extension 3a: Non-integer or non-positive ticket ID
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    payload = {"new_status": "In Progress"}
    if invalid_id is not None:
        payload["ticket_id"] = invalid_id

    response = client.post("/admin/update_ticket_status", json=payload)
    assert response.status_code == 400
    data = response.get_json()
    assert data == {"ok": False, "error": "Invalid ticket ID"}
# This proves non-positive or malformed ticket IDs are rejected with HTTP 400 Bad Request.


def test_admin_update_ticket_status_missing_new_status(client):
    # Extension 3a: Missing new_status parameter
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post("/admin/update_ticket_status", json={"ticket_id": 5})
    assert response.status_code == 400
    data = response.get_json()
    assert data == {"ok": False, "error": "Missing new_status parameter"}
# This proves requests missing the new_status parameter are rejected with HTTP 400 Bad Request.


def test_admin_update_ticket_status_unrecognized_status(client):
    # Extension 3a: Status value not in ["Open", "In Progress", "Resolved", "Closed"]
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 5, "new_status": "ArchivedStatus"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data == {"ok": False, "error": "Invalid status: ArchivedStatus"}
# This proves submitting an unrecognized ticket status value is rejected with HTTP 400 Bad Request.


def test_admin_update_ticket_status_ticket_not_found(client, mock_db):
    # Extension 4a: Ticket ID does not exist in database
    mock_db["fetch_one"].return_value = None

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 999, "new_status": "Resolved"},
    )
    assert response.status_code == 404
    data = response.get_json()
    assert data == {"ok": False, "error": "Ticket not found"}
# This proves attempting to update a support ticket that does not exist in the database returns HTTP 404 Not Found.


def test_admin_update_ticket_status_only_success(client, mock_db):
    # Main Flow: Updating status without response text (In Progress -> Resolved)
    mock_db["fetch_one"].return_value = (5, "In Progress")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 5, "new_status": "Resolved"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data == {"ok": True, "ticket_id": 5, "new_status": "Resolved"}

    mock_db["execute_query"].assert_called_once()
    sql_args = mock_db["execute_query"].call_args[0]
    assert "UPDATE Ticket SET status = ? WHERE ticket_id = ?" in sql_args[1]
    assert sql_args[2] == ("Resolved", 5)
# This proves administrators can update ticket status without attaching a response message.


def test_admin_update_ticket_status_with_response_success(client, mock_db):
    # Main Flow: Updating ticket status with staff response text
    mock_db["fetch_one"].return_value = (5, "In Progress")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_ticket_status",
        json={
            "ticket_id": 5,
            "new_status": "Resolved",
            "response": "We have refunded the missing item.",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data == {"ok": True, "ticket_id": 5, "new_status": "Resolved"}

    mock_db["execute_query"].assert_called_once()
    sql_args = mock_db["execute_query"].call_args[0]
    assert "UPDATE Ticket SET status = ?, response = ? WHERE ticket_id = ?" in sql_args[1]
    assert sql_args[2] == ("Resolved", "We have refunded the missing item.", 5)
# This proves administrators can simultaneously update ticket status and attach official staff response text.


def test_admin_update_ticket_automatic_in_progress_promotion(client, mock_db):
    # Extension 5a: Adding response to an 'Open' ticket automatically upgrades status to 'In Progress'
    mock_db["fetch_one"].return_value = (5, "Open")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_ticket_status",
        json={
            "ticket_id": 5,
            "new_status": "Open",  # Request specifies Open, but response is provided
            "response": "We are currently investigating your delivery delay.",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data == {"ok": True, "ticket_id": 5, "new_status": "In Progress"}

    sql_args = mock_db["execute_query"].call_args[0]
    assert sql_args[2] == ("In Progress", "We are currently investigating your delivery delay.", 5)
# This proves submitting a staff response on an Open ticket automatically promotes the ticket status to In Progress.


def test_admin_update_ticket_database_exception(client, mock_db):
    # Extension 6a: Database query raises an exception
    mock_db["fetch_one"].return_value = (5, "Open")
    mock_db["execute_query"].side_effect = RuntimeError("Database write error")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 5, "new_status": "Resolved"},
    )
    assert response.status_code == 500
    data = response.get_json()
    assert data == {"ok": False, "error": "Internal server error"}
# This proves unexpected database exceptions during ticket updates return HTTP 500 Internal server error.


def test_admin_update_ticket_ensures_connection_closed(client, mock_db):
    # Verification that close_connection is called in the finally block
    mock_db["fetch_one"].return_value = None  # Triggers 404 path

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 999, "new_status": "Closed"},
    )
    assert mock_db["close_connection"].called
# This proves the database connection is guaranteed to close in the finally block across all execution paths.


def test_admin_update_ticket_response_preserves_previous_history(client, mock_db):
    # Extension Not Handled #2:
    # Expected behavior: follow-up responses from support should append to a thread or
    # otherwise preserve prior response history, not silently erase it.
    # Known defect: the route only ever fetches (ticket_id, status) and then executes
    # 'UPDATE Ticket SET response = ?' with just the new text, discarding any previous
    # response. This test asserts the CORRECT behavior and will fail until responses are
    # appended/preserved instead of overwritten.
    existing_response = "Here is our first update regarding your ticket."
    mock_db["fetch_one"].return_value = (5, "In Progress", existing_response)

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    new_followup_response = "Here is our second update regarding your ticket."
    response = client.post(
        "/admin/update_ticket_status",
        json={"ticket_id": 5, "new_status": "In Progress", "response": new_followup_response},
    )

    assert response.status_code == 200
    sql_args = mock_db["execute_query"].call_args[0]
    stored_response = sql_args[2][1]
    # The persisted response should retain the prior message as well as the new one.
    assert existing_response in stored_response
    assert new_followup_response in stored_response
# This fails while a new response wholly replaces the old one; it passes once staff responses
# preserve a threaded history instead of overwriting the response column.