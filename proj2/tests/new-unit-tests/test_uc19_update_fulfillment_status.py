import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Assumption: The Flask application module is located in 'proj2/Flask_app.py' or in the current directory.
# We ensure the module path is added to sys.path so 'Flask_app' and 'models' can be imported in any test execution environment.
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
def mock_db_and_models(monkeypatch):
    """
    Assumption: Database helper functions (create_connection, close_connection, fetch_one, execute_query)
    and models.OrderStatus helper methods (is_valid_status, is_valid_transition) can be monkeypatched
    to isolate unit testing without an active SQLite database.
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

    try:
        import models
        # Default mock implementations for models.OrderStatus methods
        monkeypatch.setattr(
            models.OrderStatus,
            "is_valid_status",
            staticmethod(lambda s: s in ["Ordered", "Preparing", "Delivering", "Delivered"]),
        )
        monkeypatch.setattr(
            models.OrderStatus,
            "is_valid_transition",
            staticmethod(lambda curr, target: (curr, target) in [
                ("Ordered", "Preparing"),
                ("Preparing", "Delivering"),
                ("Delivering", "Delivered"),
            ]),
        )
    except (ImportError, AttributeError):
        pass

    return {
        "conn": mock_conn,
        "create_connection": mock_create,
        "close_connection": mock_close,
        "fetch_one": mock_fetch,
        "execute_query": mock_exec,
    }


def test_admin_update_status_unauthenticated(client):
    # Extension 2a: Unauthenticated access without active session
    response = client.post(
        "/admin/update_status",
        json={"ord_id": 101, "new_status": "Preparing"},
    )
    assert response.status_code == 401
    data = response.get_json()
    assert data == {"ok": False, "error": "unauthorized"}
# This proves unauthenticated requests to update order status are rejected with HTTP 401 Unauthorized.


def test_admin_update_status_forbidden_for_non_admin(client):
    # Extension 2b: Logged in customer lacking administrator privileges
    with client.session_transaction() as sess:
        sess["Username"] = "Regular Customer"
        sess["is_admin"] = False

    response = client.post(
        "/admin/update_status",
        json={"ord_id": 101, "new_status": "Preparing"},
    )
    assert response.status_code == 403
    data = response.get_json()
    assert data == {"ok": False, "error": "forbidden"}
# This proves authenticated users without administrator privileges are rejected with HTTP 403 Forbidden.


def test_admin_update_status_non_json_request(client):
    # Extension 3a: Request sent without JSON content-type
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_status",
        data={"ord_id": 101, "new_status": "Preparing"},  # Form data, not JSON
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data == {"ok": False, "error": "Request must be JSON"}
# This proves requests with non-JSON content types are rejected with HTTP 400 Bad Request.


@pytest.mark.parametrize("invalid_id", ["invalid_id", 0, -5, None])
def test_admin_update_status_invalid_order_id(client, invalid_id):
    # Extension 3a: Invalid or non-positive order ID
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    payload = {"new_status": "Preparing"}
    if invalid_id is not None:
        payload["ord_id"] = invalid_id

    response = client.post("/admin/update_status", json=payload)
    assert response.status_code == 400
    data = response.get_json()
    assert data == {"ok": False, "error": "Invalid order ID"}
# This proves invalid or non-positive order IDs are rejected with HTTP 400 Bad Request.


def test_admin_update_status_missing_new_status(client):
    # Extension 3a: Payload missing new_status parameter
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post("/admin/update_status", json={"ord_id": 101})
    assert response.status_code == 400
    data = response.get_json()
    assert data == {"ok": False, "error": "Missing new_status parameter"}
# This proves requests missing the new_status parameter are rejected with HTTP 400 Bad Request.


def test_admin_update_status_invalid_status_value(client, mock_db_and_models):
    # Extension 3a: Submitting an invalid status string outside allowed set
    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_status",
        json={"ord_id": 101, "new_status": "InvalidStatusXYZ"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "Invalid status: InvalidStatusXYZ" in data.get("error", "")
# This proves submitting an unrecognized status value is rejected with HTTP 400 Bad Request.


def test_admin_update_status_order_not_found(client, mock_db_and_models):
    # Extension 4a: Order ID does not exist in database
    mock_db_and_models["fetch_one"].return_value = None

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_status",
        json={"ord_id": 999, "new_status": "Preparing"},
    )
    assert response.status_code == 404
    data = response.get_json()
    assert data == {"ok": False, "error": "Order not found"}
# This proves attempting to update an order ID that does not exist in the database returns HTTP 404 Not Found.


def test_admin_update_status_invalid_transition(client, mock_db_and_models):
    # Extension 5a: Invalid workflow transition (e.g. Delivered -> Ordered)
    mock_db_and_models["fetch_one"].return_value = (101, "Delivered")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_status",
        json={"ord_id": 101, "new_status": "Preparing"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "Invalid transition from Delivered to Preparing" in data.get("error", "")
# This proves workflow status transitions that violate sequential lifecycle rules are rejected with HTTP 400 Bad Request.


def test_admin_update_status_success(client, mock_db_and_models):
    # Main Success Scenario: Valid transition from 'Ordered' to 'Preparing'
    mock_db_and_models["fetch_one"].return_value = (101, "Ordered")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_status",
        json={"ord_id": 101, "new_status": "Preparing"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data == {"ok": True, "ord_id": 101, "new_status": "Preparing"}

    # Verify SQL update execution
    mock_db_and_models["execute_query"].assert_called_once()
    sql_args = mock_db_and_models["execute_query"].call_args[0]
    assert 'UPDATE "Order" SET status = ? WHERE ord_id = ?' in sql_args[1]
    assert sql_args[2] == ("Preparing", 101)
# This proves administrators can successfully update valid orders through permitted status transitions.


def test_admin_update_status_database_exception(client, mock_db_and_models):
    # Extension 6a: Database failure during execution
    mock_db_and_models["fetch_one"].return_value = (101, "Ordered")
    mock_db_and_models["execute_query"].side_effect = RuntimeError("SQLite disk I/O failure")

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    response = client.post(
        "/admin/update_status",
        json={"ord_id": 101, "new_status": "Preparing"},
    )
    assert response.status_code == 500
    data = response.get_json()
    assert data == {"ok": False, "error": "Internal server error"}
# This proves internal database errors during status updates are caught and return HTTP 500 Internal server error.


def test_admin_update_status_ensures_connection_closed(client, mock_db_and_models):
    # Verification that close_connection is called in the finally block
    mock_db_and_models["fetch_one"].return_value = None  # Triggers early 404 return

    with client.session_transaction() as sess:
        sess["Username"] = "Admin User"
        sess["is_admin"] = True

    client.post(
        "/admin/update_status",
        json={"ord_id": 999, "new_status": "Preparing"},
    )
    assert mock_db_and_models["close_connection"].called
# This proves the database connection is guaranteed to be closed in the finally block across both success and error paths.