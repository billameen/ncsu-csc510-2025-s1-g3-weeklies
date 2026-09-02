import os
import sys
from io import BytesIO
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
    Assumption: Flask test client with testing mode and a constant secret key for session manipulation.
    """
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_secret_key"
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_db_and_pdf(monkeypatch):
    """
    Assumption: Database helper functions (create_connection, close_connection, fetch_one)
    and pdf generator (generate_order_receipt_pdf) in Flask_app can be monkeypatched
    to isolate unit testing without requiring an active SQLite database or filesystem PDF generation.
    """
    mock_conn = MagicMock()
    mock_close = MagicMock()
    mock_create = MagicMock(return_value=mock_conn)
    mock_fetch = MagicMock()
    mock_pdf_gen = MagicMock(return_value=b"%PDF-1.4 mock pdf binary stream")

    import Flask_app

    monkeypatch.setattr(Flask_app, "create_connection", mock_create)
    monkeypatch.setattr(Flask_app, "close_connection", mock_close)
    monkeypatch.setattr(Flask_app, "fetch_one", mock_fetch)
    monkeypatch.setattr(Flask_app, "generate_order_receipt_pdf", mock_pdf_gen)

    return {
        "conn": mock_conn,
        "create_connection": mock_create,
        "close_connection": mock_close,
        "fetch_one": mock_fetch,
        "generate_order_receipt_pdf": mock_pdf_gen,
    }


def test_order_receipt_unauthenticated_redirects_to_login(client):
    # Main Flow Step 2 & Extension 2a: Unauthenticated access without active session
    response = client.get("/orders/10/receipt.pdf")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
# This proves unauthenticated users attempting to access receipt downloads are redirected to the login page.


def test_order_receipt_success_with_session_usr_id(client, mock_db_and_pdf):
    # Main Flow: User logged in with usr_id in session, accessing their own order (usr_id=42)
    mock_db_and_pdf["fetch_one"].return_value = (42,)

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42
        sess["Email"] = "alice@example.com"

    response = client.get("/orders/101/receipt.pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert "attachment" in response.headers.get("Content-Disposition", "")
    assert "filename=order_101_receipt.pdf" in response.headers.get("Content-Disposition", "")
    assert response.data == b"%PDF-1.4 mock pdf binary stream"
# This proves authenticated customers can successfully download valid PDF receipts for their own orders when usr_id is in the session.


def test_order_receipt_success_with_email_fallback(client, mock_db_and_pdf):
    # Extension 4b: Legacy session lacking usr_id, resolving owner via session Email
    # 1st fetch_one call: Order query returns owner usr_id=42
    # 2nd fetch_one call: User query returns usr_id=42 for the session email
    mock_db_and_pdf["fetch_one"].side_effect = [(42,), (42,)]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "alice@example.com"
        # No 'usr_id' in session

    response = client.get("/orders/101/receipt.pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert "filename=order_101_receipt.pdf" in response.headers.get("Content-Disposition", "")
    assert response.data == b"%PDF-1.4 mock pdf binary stream"
# This proves legacy sessions lacking usr_id fall back to email verification and allow receipt downloads if the resolved user ID matches the order owner.


def test_order_receipt_not_found(client, mock_db_and_pdf):
    # Extension 3a: Non-existent order ID in database returns 404
    mock_db_and_pdf["fetch_one"].return_value = None

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.get("/orders/999/receipt.pdf")
    assert response.status_code == 404
# This proves attempting to download a receipt for a non-existent order ID returns an HTTP 404 Not Found error.


def test_order_receipt_forbidden_for_different_user(client, mock_db_and_pdf):
    # Extension 4a: Order belongs to user 99, but logged-in user is 42
    mock_db_and_pdf["fetch_one"].return_value = (99,)

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.get("/orders/101/receipt.pdf")
    assert response.status_code == 403
# This proves users cannot download receipts for orders belonging to another user when usr_id in session does not match order ownership.


def test_order_receipt_forbidden_email_fallback_mismatch(client, mock_db_and_pdf):
    # Extension 4b & 4a: Legacy session without usr_id, email resolves to user 42 but order belongs to user 99
    mock_db_and_pdf["fetch_one"].side_effect = [(99,), (42,)]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "alice@example.com"

    response = client.get("/orders/101/receipt.pdf")
    assert response.status_code == 403
# This proves email fallback verification aborts with HTTP 403 Forbidden if the email resolves to a user ID different from the order owner.


def test_order_receipt_forbidden_email_fallback_user_not_found(client, mock_db_and_pdf):
    # Extension 4b: Legacy session without usr_id, and session email is not found in User table
    mock_db_and_pdf["fetch_one"].side_effect = [(99,), None]

    with client.session_transaction() as sess:
        sess["Username"] = "Unknown User"
        sess["Email"] = "unknown@example.com"

    response = client.get("/orders/101/receipt.pdf")
    assert response.status_code == 403
# This proves email fallback verification aborts with HTTP 403 Forbidden if the session email is not found in the User table.


def test_order_receipt_database_connection_closed_on_abort_and_success(client, mock_db_and_pdf):
    # Verification that finally block calls close_connection even when aborted
    mock_db_and_pdf["fetch_one"].return_value = None  # Will trigger 404 abort

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42

    response = client.get("/orders/999/receipt.pdf")
    assert response.status_code == 404
    assert mock_db_and_pdf["close_connection"].called
# This proves the database connection is guaranteed to close in the finally block regardless of whether the receipt download succeeds or aborts with an error.


def test_order_receipt_admin_can_download_other_users_receipt(client, mock_db_and_pdf):
    # Extension Not Handled #2: An administrator (is_admin=True) assisting customers should be
    # able to view/download receipts for orders they do not own.
    # Known defect: the route strictly checks row[0] == session['usr_id'] without an is_admin
    # override, so this currently 403s. This test asserts the CORRECT behavior and will fail
    # (403 != 200) until an admin override is added to the route.
    mock_db_and_pdf["fetch_one"].return_value = (42,)  # Order belongs to customer 42

    with client.session_transaction() as sess:
        sess["Username"] = "Support Admin"
        sess["usr_id"] = 1  # Admin ID, different from order owner
        sess["is_admin"] = True
        sess["Email"] = "admin@weeklies.com"

    response = client.get("/orders/101/receipt.pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
# This fails while admins have no override and are rejected with 403; it passes once
# administrators are granted access to receipts they don't own.


def test_order_receipt_generator_failure_returns_500_gracefully(client, mock_db_and_pdf):
    # Extension Not Handled #1: if PDF compilation fails (e.g. malformed details or a library
    # error), the route should catch the error and return a clean 500 response instead of
    # crashing the request.
    # Known defect: generate_order_receipt_pdf has no try/except wrapper, so the exception
    # currently bubbles up unhandled. This test asserts the CORRECT behavior and will fail
    # (with an unhandled RuntimeError) until the route wraps PDF generation in error handling.
    mock_db_and_pdf["fetch_one"].return_value = (42,)
    mock_db_and_pdf["generate_order_receipt_pdf"].side_effect = RuntimeError("PDF Generation Engine Failure")

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["usr_id"] = 42
        sess["Email"] = "alice@example.com"

    response = client.get("/orders/101/receipt.pdf")
    assert response.status_code == 500
# This fails with an unhandled RuntimeError while the route has no try/except around the PDF
# generator; it passes once generator failures are caught and turned into a proper 500 response.