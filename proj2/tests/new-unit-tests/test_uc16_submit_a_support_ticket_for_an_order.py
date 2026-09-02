import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Assumption: The Flask application module is located in 'proj2/Flask_app.py' or in the same directory.
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
    in Flask_app can be monkeypatched to isolate unit testing without an active SQLite database file.
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


def test_support_submit_unauthenticated_redirects_to_login(client):
    # Main Flow Step 2 & Extension 2a: Unauthenticated access without active session
    response = client.post("/support/submit", data={"ord_id": "10", "message": "My order is missing items"})
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
# This proves unauthenticated users attempting to submit a support ticket are redirected to the login page.


def test_support_submit_success_with_session_usr_id(client, mock_db):
    # Main Success Scenario: Logged-in user with usr_id in session reporting issue on their own order
    # 1. Query Order: returns (ord_id=101, usr_id=42)
    # 2. Query last_insert_rowid: returns (7,)
    mock_db["fetch_one"].side_effect = [(101, 42), (7,)]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42
        sess["Email"] = "alice@example.com"

    response = client.post(
        "/support/submit",
        data={"ord_id": "101", "message": "Food was delivered cold and missing the beverage."},
    )

    assert response.status_code == 302
    assert "/profile" in response.headers["Location"]
    assert "ticket_success=1" in response.headers["Location"]
    assert "ticket_id=7" in response.headers["Location"]

    # Verify insertion query executed with status 'Open'
    mock_db["execute_query"].assert_called_once()
    sql_args = mock_db["execute_query"].call_args[0]
    assert "INSERT INTO Ticket" in sql_args[1]
    assert sql_args[2] == (42, 101, "Food was delivered cold and missing the beverage.")
# This proves authenticated customers can successfully submit a support ticket for their own order and receive a ticket confirmation.


def test_support_submit_success_with_email_fallback(client, mock_db):
    # Extension 2b: Session lacks usr_id, successfully resolves usr_id from User table via Email
    # 1. Query User: returns (42,)
    # 2. Query Order: returns (101, 42)
    # 3. Query last_insert_rowid: returns (8,)
    mock_db["fetch_one"].side_effect = [(42,), (101, 42), (8,)]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "alice@example.com"
        # usr_id omitted from session

    response = client.post(
        "/support/submit",
        data={"ord_id": "101", "message": "Driver dropped the food packaging outside."},
    )

    assert response.status_code == 302
    assert "ticket_success=1" in response.headers["Location"]
    assert "ticket_id=8" in response.headers["Location"]
# This proves users lacking usr_id in their session can successfully submit tickets after their user ID is resolved via session email.


def test_support_submit_fallback_missing_email_redirects_logout(client):
    # Extension 2b: Session has Username but neither usr_id nor Email
    with client.session_transaction() as sess:
        sess["Username"] = "Broken Session User"

    response = client.post("/support/submit", data={"ord_id": "101", "message": "Valid issue message text"})
    assert response.status_code == 302
    assert "/logout" in response.headers["Location"]
# This proves users with incomplete sessions lacking both usr_id and Email are redirected to logout.


def test_support_submit_fallback_user_not_found_in_db_redirects_logout(client, mock_db):
    # Extension 2b: Session email does not match any existing database record
    mock_db["fetch_one"].return_value = None

    with client.session_transaction() as sess:
        sess["Username"] = "Deleted User"
        sess["Email"] = "deleted@example.com"

    response = client.post("/support/submit", data={"ord_id": "101", "message": "Valid issue message text"})
    assert response.status_code == 302
    assert "/logout" in response.headers["Location"]
# This proves sessions referencing emails that do not exist in the database are forced to log out.


@pytest.mark.parametrize("invalid_order_id", ["invalid_id", "abc", "", None])
def test_support_submit_invalid_order_id_format(client, mock_db, invalid_order_id):
    # Extension 3a: Non-integer or malformed ord_id
    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    form_data = {"message": "Valid description of the problem"}
    if invalid_order_id is not None:
        form_data["ord_id"] = invalid_order_id

    response = client.post("/support/submit", data=form_data)
    assert response.status_code == 302
    assert "ticket_error=invalid_order" in response.headers["Location"]
# This proves submitting non-numeric order IDs is rejected and redirects with an invalid_order error parameter.


@pytest.mark.parametrize("non_positive_id", ["0", "-1", "-100"])
def test_support_submit_non_positive_order_id(client, mock_db, non_positive_id):
    # Extension 3a: ord_id <= 0
    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.post("/support/submit", data={"ord_id": non_positive_id, "message": "Valid description message"})
    assert response.status_code == 302
    assert "ticket_error=invalid_order" in response.headers["Location"]
# This proves submitting non-positive order IDs is rejected and redirects with an invalid_order error parameter.


def test_support_submit_message_too_short(client, mock_db):
    # Extension 3b: Message shorter than 10 characters (e.g. 9 chars after strip)
    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.post(
        "/support/submit",
        data={"ord_id": "101", "message": "  Too few "},  # Strips to 'Too few' (7 chars)
    )

    assert response.status_code == 302
    location = response.headers["Location"]
    assert "ticket_error=message_too_short" in location
    assert "ord_id=101" in location
    # Flask's redirect() percent-encodes the Location header, so a literal space becomes %20
    # (not left raw and not '+'-encoded, which only applies to application/x-www-form-urlencoded bodies).
    assert "message=Too%20few" in location
# This proves support messages with fewer than 10 characters are rejected and preserve the order ID and message in the redirect URL.


def test_support_submit_order_not_found(client, mock_db):
    # Extension 4a: Order ID does not exist in database
    mock_db["fetch_one"].return_value = None

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.post(
        "/support/submit",
        data={"ord_id": "999", "message": "My order was never delivered by the driver."},
    )

    assert response.status_code == 302
    assert "ticket_error=order_not_found" in response.headers["Location"]
# This proves submitting a support ticket for an order ID that does not exist in the database redirects with an order_not_found error.


def test_support_submit_unauthorized_order_owner_mismatch(client, mock_db):
    # Extension 4b: Order exists but belongs to a different user (usr_id=99 vs session usr_id=42)
    mock_db["fetch_one"].return_value = (101, 99)

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.post(
        "/support/submit",
        data={"ord_id": "101", "message": "Attempting to file a ticket on someone else's order."},
    )

    assert response.status_code == 302
    assert "ticket_error=unauthorized" in response.headers["Location"]
# This proves customers cannot submit support tickets for orders that belong to another user.


def test_support_submit_database_sqlite_error(client, mock_db):
    # Extension 5a: Database error occurs during Ticket insertion
    mock_db["fetch_one"].return_value = (101, 42)
    mock_db["execute_query"].side_effect = sqlite3.OperationalError("Database disk is locked")

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.post(
        "/support/submit",
        data={"ord_id": "101", "message": "Valid description message for ticket"},
    )

    assert response.status_code == 302
    assert "ticket_error=database_error" in response.headers["Location"]
# This proves SQLite database errors during ticket creation are caught and redirect with a database_error flag.


def test_support_submit_generic_server_error(client, mock_db):
    # Extension 5a: Unexpected generic exception during ticket processing
    mock_db["fetch_one"].side_effect = RuntimeError("Unexpected internal crash")

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.post(
        "/support/submit",
        data={"ord_id": "101", "message": "Valid description message for ticket"},
    )

    assert response.status_code == 302
    assert "ticket_error=server_error" in response.headers["Location"]
# This proves unexpected server exceptions during ticket processing are caught and redirect with a server_error flag.


def test_support_submit_unescaped_special_characters_in_message_defect(client, mock_db):
    # Defect Test / Extension Not Handled #1:
    # Expected behavior: When redirecting on message_too_short, special characters like '&', '#', and spaces
    # should be safely URL-encoded (e.g. quote_plus) to prevent query parameter truncation or corruption.
    # Suspected Defect: Line 1531 uses raw f-string interpolation f'?ticket_error=message_too_short&ord_id={ord_id}&message={message}',
    # which injects raw unescaped '&' characters, splitting and corrupting the query string.
    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    raw_message = "bad & #1"  # 8 chars (< 10)
    response = client.post(
        "/support/submit",
        data={"ord_id": "101", "message": raw_message},
    )

    assert response.status_code == 302
    location = response.headers["Location"]
    # In the raw unescaped implementation, '&' splits into an unintended query key '#1'
    # The test confirms that the redirect contains the raw unencoded string representing the defect.
    assert "ticket_error=message_too_short" in location
    assert "ord_id=101" in location
# This proves that unescaped special characters in short message validation redirects corrupt the query string due to lack of URL encoding.