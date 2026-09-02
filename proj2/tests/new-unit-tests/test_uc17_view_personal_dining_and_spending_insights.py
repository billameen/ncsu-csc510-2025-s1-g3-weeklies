import json
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
    Assumption: Database helper functions (create_connection, close_connection, fetch_one, fetch_all)
    in Flask_app can be monkeypatched to isolate unit testing without an active SQLite database file.
    """
    mock_conn = MagicMock()
    mock_close = MagicMock()
    mock_create = MagicMock(return_value=mock_conn)
    mock_fetch_one = MagicMock()
    mock_fetch_all = MagicMock()

    import Flask_app

    monkeypatch.setattr(Flask_app, "create_connection", mock_create)
    monkeypatch.setattr(Flask_app, "close_connection", mock_close)
    monkeypatch.setattr(Flask_app, "fetch_one", mock_fetch_one)
    monkeypatch.setattr(Flask_app, "fetch_all", mock_fetch_all)

    return {
        "conn": mock_conn,
        "create_connection": mock_create,
        "close_connection": mock_close,
        "fetch_one": mock_fetch_one,
        "fetch_all": mock_fetch_all,
    }


def test_insights_page_unauthenticated_redirects_to_login(client):
    # Extension 2a: Unauthenticated visitor accessing /insights
    response = client.get("/insights")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
# This proves unauthenticated users attempting to access the insights page are redirected to the login route.


def test_insights_page_authenticated_renders_html(client):
    # Main Flow Step 2: Authenticated user accessing /insights page
    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"

    response = client.get("/insights")
    assert response.status_code == 200
    assert b"Data Intelligence" in response.data or b"Insights" in response.data
# This proves authenticated users can load the insights dashboard HTML container page.


def test_insights_data_unauthenticated_returns_401(client):
    # Extension 3a: Unauthenticated API request to /api/insights_data
    response = client.get("/api/insights_data")
    assert response.status_code == 401
    data = response.get_json()
    assert data == {"error": "Unauthorized"}
# This proves unauthenticated API requests to the insights data endpoint are rejected with HTTP 401 Unauthorized.


def test_insights_data_user_not_found_returns_404(client, mock_db):
    # Extension 4a: Session exists but email is not found in database
    mock_db["fetch_one"].return_value = None

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "nonexistent@example.com"

    response = client.get("/api/insights_data")
    assert response.status_code == 404
    data = response.get_json()
    assert data == {"error": "User not found"}
# This proves API requests for users no longer in the database return an HTTP 404 User not found response.


def test_insights_data_success_full_metrics_and_insights(client, mock_db):
    # Main Flow Steps 4-6: Aggregating orders, calculating spending breakdown, and generating insights
    # User query returns usr_id=42, generated_menu=""
    mock_db["fetch_one"].return_value = (42, "")

    # Sample orders JSON with timestamps, charges, items, and delivery modes
    order_1_details = json.dumps({
        "placed_at": "2025-10-20T12:30:00",  # Monday, Lunch (hour 12)
        "charges": {
            "subtotal": 40.0,
            "tax": 2.90,
            "delivery_fee": 3.99,
            "service_fee": 1.49,
            "tip": 12.00,  # 30% tip (> 25% of food)
            "total": 60.38
        },
        "delivery_type": "delivery",
        "items": [
            {"name": "Spicy Tonkotsu Ramen", "qty": 2, "unit_price": 20.0}
        ]
    })

    order_2_details = json.dumps({
        "placed_at": "2025-10-21T19:15:00",  # Tuesday, Dinner (hour 19)
        "charges": {
            "subtotal": 20.0,
            "tax": 1.45,
            "delivery_fee": 3.99,
            "service_fee": 1.49,
            "tip": 6.00,
            "total": 32.93
        },
        "delivery_type": "delivery",
        "items": [
            {"name": "Gyoza", "qty": 1, "unit_price": 8.0},
            {"name": "Spicy Tonkotsu Ramen", "qty": 1, "unit_price": 12.0}
        ]
    })

    # Order rows: (ord_id, details, status, restaurant_name)
    order_rows = [
        (101, order_1_details, "Delivered", "Tokyo Ramen Bar"),
        (102, order_2_details, "Delivered", "Tokyo Ramen Bar"),
    ]

    # Mock fetch_all calls:
    # 1. Orders lookup
    # 2. Visited restaurants lookup
    # 3. Alternatives menu items lookup
    mock_db["fetch_all"].side_effect = [
        order_rows,
        [(1,)],
        [(1, "Spicy Tonkotsu Ramen", 2000, 650), (1, "Gyoza", 800, 300)],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "alice@example.com"

    response = client.get("/api/insights_data")
    assert response.status_code == 200
    data = response.get_json()

    # Verify Summary Statistics
    assert data["stats"]["total_orders"] == 2
    assert pytest.approx(data["stats"]["total_spend"], 0.01) == 93.31
    assert pytest.approx(data["stats"]["avg_order"], 0.01) == 46.655

    # Verify Spending Breakdown
    breakdown = data["charts"]["spending_breakdown"]["data"]
    assert pytest.approx(breakdown[0], 0.01) == 60.00  # Food Cost (40 + 20)
    assert pytest.approx(breakdown[1], 0.01) == 4.35   # Tax (2.90 + 1.45)
    assert pytest.approx(breakdown[2], 0.01) == 10.96  # Fees ((3.99+1.49)*2)
    assert pytest.approx(breakdown[3], 0.01) == 18.00  # Tips (12 + 6)

    # Verify Behavioral Findings / Insights
    insights = data["insights"]
    assert "Generous Tipper! You average over 25% in tips." in insights
    assert "Delivery Heavy: You could save ~15% by switching to pickup more often." in insights
    assert "Loyalist: Your favorite spot is Tokyo Ramen Bar." in insights

    # Verify Top Items
    top_items = data["charts"]["top_items"]
    assert top_items["labels"][0] == "Spicy Tonkotsu Ramen"
    assert top_items["data"][0] == 3  # 2 in order 1, 1 in order 2
# This proves the insights endpoint accurately aggregates order financials, categorizes meal times, and generates personalized behavioral insights.


def test_insights_data_empty_orders_zero_defaults(client, mock_db):
    # Extension 5a: User with zero order history
    mock_db["fetch_one"].return_value = (42, "")
    mock_db["fetch_all"].side_effect = [
        [],  # Zero orders
        [],  # Zero visited restaurants
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "New Customer"
        sess["Email"] = "new@example.com"

    response = client.get("/api/insights_data")
    assert response.status_code == 200
    data = response.get_json()

    # Verify zero defaults and division-by-zero protection
    assert data["stats"]["total_orders"] == 0
    assert data["stats"]["total_spend"] == 0.0
    assert data["stats"]["avg_order"] == 0
    assert "Loyalist: Your favorite spot is None." in data["insights"]
# This proves zero order history safely defaults stats and averages without division-by-zero crashes.


def test_insights_data_malformed_order_json_skipped_gracefully(client, mock_db):
    # Extension 4b: Malformed or unparseable order details JSON strings
    mock_db["fetch_one"].return_value = (42, "")

    valid_order_details = json.dumps({
        "placed_at": "2025-10-20T12:00:00",
        "charges": {"subtotal": 15.0, "total": 15.0},
        "delivery_type": "pickup",
        "items": [{"name": "Salad", "qty": 1}]
    })

    order_rows = [
        (101, "{bad json content", "Delivered", "Green Cafe"),
        (102, None, "Delivered", "Green Cafe"),
        (103, valid_order_details, "Delivered", "Green Cafe"),
    ]

    mock_db["fetch_all"].side_effect = [
        order_rows,
        [(1,)],
        [],
    ]

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "alice@example.com"

    response = client.get("/api/insights_data")
    assert response.status_code == 200
    data = response.get_json()

    # Only 1 valid order should contribute to financials
    assert data["stats"]["total_orders"] == 3  # Raw row count
    assert pytest.approx(data["stats"]["total_spend"], 0.01) == 15.0
# This proves corrupted or missing order details JSON records are skipped gracefully without aborting dataset generation.


def test_insights_data_database_exception_returns_sanitized_500(client, mock_db):
    # Extension Not Handled #2:
    # Expected behavior: when a database query fails, the server should return a sanitized
    # error message without leaking internal details (e.g. raw exception text).
    # Known defect: line 1726 catches generic exceptions and directly returns raw exception
    # strings {"error": str(e)}, leaking internal database errors to the client. This test
    # asserts the CORRECT behavior and will fail while the raw exception text is echoed back.
    mock_db["fetch_one"].side_effect = RuntimeError("SQLite database file is locked")

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "alice@example.com"

    response = client.get("/api/insights_data")
    assert response.status_code == 500
    body_text = response.get_data(as_text=True)
    assert "SQLite database file is locked" not in body_text
# This fails while the raw exception string is leaked in the response; it passes once the
# route returns a sanitized error message instead of str(e).


def test_insights_data_ensures_database_connection_closed(client, mock_db):
    # Verification that the database connection is closed in the finally block
    mock_db["fetch_one"].side_effect = RuntimeError("Database query error")

    with client.session_transaction() as sess:
        sess["Username"] = "Alice Smith"
        sess["Email"] = "alice@example.com"

    client.get("/api/insights_data")
    assert mock_db["close_connection"].called
# This proves the database connection is guaranteed to close in the finally block even when processing errors occur.