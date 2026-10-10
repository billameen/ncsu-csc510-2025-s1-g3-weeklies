import json
import pytest
from datetime import datetime
from sqlQueries import create_connection, execute_query, close_connection, fetch_one

# --- Core Access & Structure Tests ---

def test_insights_page_requires_login(client):
    """Ensure insights HTML page is protected."""
    resp = client.get("/insights", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["Location"]

def test_insights_page_loads_for_user(client, login_session):
    """Ensure insights HTML page loads for logged-in user."""
    resp = client.get("/insights")
    assert resp.status_code == 200
    assert b"Insights" in resp.data or b"Dashboard" in resp.data

def test_insights_api_unauthorized(client):
    """Ensure data API is protected."""
    resp = client.get("/api/insights_data")
    assert resp.status_code == 401

def test_insights_api_structure_success(client, login_session, seed_minimal_data, temp_db_path):
    """Test that the API returns the expected JSON structure keys."""
    conn = create_connection(temp_db_path)
    execute_query(conn, 'UPDATE "User" SET generated_menu="[]" WHERE usr_id=?', (seed_minimal_data["usr_id"],))
    conn.close()

    resp = client.get("/api/insights_data")
    assert resp.status_code == 200
    
    data = resp.get_json()
    assert "charts" in data
    assert "stats" in data
    assert "insights" in data
    
    charts = data["charts"]
    assert "spending_breakdown" in charts
    assert "top_restaurants" in charts
    assert "meal_times" in charts
    assert "activity_by_day" in charts
    assert "delivery_mode" in charts
    assert "top_items" in charts

# --- Data Aggregation Tests ---

def test_insights_empty_user_data(client, login_session, temp_db_path, seed_minimal_data):
    """Test API response when user has zero orders."""
    # CLEANUP: Remove any seeded orders for this user to ensure empty state
    conn = create_connection(temp_db_path)
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    
    assert data["stats"]["total_orders"] == 0
    assert data["stats"]["total_spend"] == 0
    assert len(data["charts"]["top_restaurants"]["data"]) == 0

def test_insights_stats_calculation(client, login_session, seed_minimal_data, temp_db_path):
    """Test that stats correctly aggregate order totals."""
    conn = create_connection(temp_db_path)
    # CLEANUP: Start fresh
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    # Order: $50 total
    details = json.dumps({"charges": {"total": 50.00}, "placed_at": "2025-01-01T12:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, ?, "Delivered")',
                 (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    
    assert data["stats"]["total_orders"] == 1
    assert abs(data["stats"]["total_spend"] - 50.0) < 0.01

def test_multiple_users_isolation(client, temp_db_path, seed_minimal_data, login_session):
    """Ensure User A does not see User B's stats."""
    conn = create_connection(temp_db_path)
    # CLEANUP: Start fresh for User A
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    # Create User B
    execute_query(conn, 'INSERT INTO "User" (usr_id, email, first_name) VALUES (999, "b@test.com", "B")')
    
    # Insert Order for User B ($1000)
    details_b = json.dumps({"charges": {"total": 1000.00}, "placed_at": "2025-01-01T12:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, 999, ?, "Delivered")',
                 (seed_minimal_data["rtr_id"], details_b))
    
    # Insert Order for User A (Logged in) ($10)
    details_a = json.dumps({"charges": {"total": 10.00}, "placed_at": "2025-01-01T12:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, ?, "Delivered")',
                 (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details_a))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    
    # Should only see $10, not $1010
    assert abs(data["stats"]["total_spend"] - 10.0) < 0.01

# --- JSON & Parsing Edge Cases ---

def test_insights_broken_order_json(client, login_session, seed_minimal_data, temp_db_path):
    """Test that invalid JSON in the database doesn't crash the API."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "INVALID { JSON", "Delivered")',
                 (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"]))
    conn.close()

    resp = client.get("/api/insights_data")
    assert resp.status_code == 200
    data = resp.get_json()
    
    # The order exists (row count is 1), but parsing failed so spend is 0
    assert data["stats"]["total_orders"] == 1 
    assert data["stats"]["total_spend"] == 0

def test_insights_missing_charges_key(client, login_session, seed_minimal_data, temp_db_path):
    """Test order with valid JSON but missing 'charges' key."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({"placed_at": "2025-01-01T12:00:00"}) # No charges
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, ?, "Delivered")',
                 (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    assert data["stats"]["total_spend"] == 0

def test_insights_missing_placed_at(client, login_session, seed_minimal_data, temp_db_path):
    """Test order missing 'placed_at' timestamp."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({"charges": {"total": 10.0}}) # No time
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, ?, "Delivered")',
                 (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    # Should count towards spend but not crash time charts
    assert data["stats"]["total_spend"] == 10.0

def test_insights_malformed_date(client, login_session, seed_minimal_data, temp_db_path):
    """Test order with malformed date string."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({"charges": {"total": 10.0}, "placed_at": "NOT-A-DATE"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, ?, "Delivered")',
                 (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    assert resp.status_code == 200 # Should not crash

# --- Specific Chart Logic Tests ---

def test_insights_top_restaurants_aggregation(client, login_session, seed_minimal_data, temp_db_path):
    """Test that restaurant visits are aggregated correctly."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    # 2 orders at seeded restaurant
    details = json.dumps({"charges": {"total": 10}, "placed_at": "2025-01-01T12:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?, ?, ?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?, ?, ?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    
    counts = data["charts"]["top_restaurants"]["data"]
    assert counts[0] == 2

def test_insights_spending_breakdown(client, login_session, seed_minimal_data, temp_db_path):
    """Test accumulation of subtotal, tax, tip, and fees."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({
        "charges": {
            "subtotal": 20.0,
            "tax": 2.0,
            "delivery_fee": 3.0,
            "service_fee": 1.0,
            "tip": 5.0,
            "total": 31.0
        },
        "placed_at": "2025-01-01T12:00:00"
    })
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?, ?, ?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    breakdown = data["charts"]["spending_breakdown"]
    
    # Labels: ["Food Cost", "Tax", "Service/Delivery Fees", "Tips"]
    assert breakdown["data"][0] == 20.0  # Food
    assert breakdown["data"][1] == 2.0   # Tax
    assert breakdown["data"][2] == 4.0   # Fees (3+1)
    assert breakdown["data"][3] == 5.0   # Tip

def test_insights_delivery_vs_pickup(client, login_session, seed_minimal_data, temp_db_path):
    """Test counts for delivery vs pickup."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    d_order = json.dumps({"delivery_type": "delivery", "placed_at": "2025-01-01T10:00:00"})
    p_order = json.dumps({"delivery_type": "pickup", "placed_at": "2025-01-01T10:00:00"})
    
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], d_order))
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], p_order))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    # Labels: ["Delivery", "Pickup"]
    assert data["charts"]["delivery_mode"]["data"][0] == 1
    assert data["charts"]["delivery_mode"]["data"][1] == 1

def test_insights_item_frequency(client, login_session, seed_minimal_data, temp_db_path):
    """Test parsing of item names and quantities."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({
        "items": [
            {"name": "Burger", "qty": 2},
            {"name": "Fries", "qty": 1}
        ],
        "placed_at": "2025-01-01T12:00:00"
    })
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    
    # Check top items labels and data
    labels = data["charts"]["top_items"]["labels"]
    counts = data["charts"]["top_items"]["data"]
    
    assert "Burger" in labels
    assert counts[labels.index("Burger")] == 2

# --- Meal Time Buckets Tests ---

def test_insights_meal_time_breakfast(client, login_session, seed_minimal_data, temp_db_path):
    """Test order placed at 09:00 counts as Breakfast."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({"placed_at": "2025-01-01T09:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    # Keys: Breakfast, Lunch, Dinner, Late Night
    idx = data["charts"]["meal_times"]["labels"].index("Breakfast")
    assert data["charts"]["meal_times"]["data"][idx] == 1

def test_insights_meal_time_lunch(client, login_session, seed_minimal_data, temp_db_path):
    """Test order placed at 13:00 counts as Lunch."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({"placed_at": "2025-01-01T13:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    idx = data["charts"]["meal_times"]["labels"].index("Lunch")
    assert data["charts"]["meal_times"]["data"][idx] == 1

def test_insights_meal_time_dinner(client, login_session, seed_minimal_data, temp_db_path):
    """Test order placed at 19:00 counts as Dinner."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({"placed_at": "2025-01-01T19:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    idx = data["charts"]["meal_times"]["labels"].index("Dinner")
    assert data["charts"]["meal_times"]["data"][idx] == 1

def test_insights_meal_time_latenight(client, login_session, seed_minimal_data, temp_db_path):
    """Test order placed at 02:00 counts as Late Night."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    details = json.dumps({"placed_at": "2025-01-01T02:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    idx = data["charts"]["meal_times"]["labels"].index("Late Night")
    assert data["charts"]["meal_times"]["data"][idx] == 1

# --- Text Insight Generation Tests ---

def test_insight_text_generous_tipper(client, login_session, seed_minimal_data, temp_db_path):
    """Test trigger: Tip > 25% of food cost."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    # Food: 100, Tip: 30 (30%)
    details = json.dumps({"charges": {"subtotal": 100, "tip": 30}, "placed_at": "2025-01-01T12:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    text_list = data["insights"]
    assert any("Generous Tipper" in t for t in text_list)

def test_insight_text_not_generous(client, login_session, seed_minimal_data, temp_db_path):
    """Test absence of generous tipper text for low tips."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    # Food: 100, Tip: 5 (5%)
    details = json.dumps({"charges": {"subtotal": 100, "tip": 5}, "placed_at": "2025-01-01T12:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    text_list = data["insights"]
    assert not any("Generous Tipper" in t for t in text_list)

def test_insight_text_delivery_heavy(client, login_session, seed_minimal_data, temp_db_path):
    """Test trigger: Delivery count > 2 * Pickup count."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    d = json.dumps({"delivery_type": "delivery", "placed_at": "2025-01-01T12:00:00"})
    p = json.dumps({"delivery_type": "pickup", "placed_at": "2025-01-01T12:00:00"})
    
    # 3 deliveries, 0 pickups
    for _ in range(3):
        execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], d))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    text_list = data["insights"]
    assert any("Delivery Heavy" in t for t in text_list)

def test_insight_text_loyalist(client, login_session, seed_minimal_data, temp_db_path):
    """Test that the favorite restaurant is identified."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    # Assuming seed data has a restaurant named "Test Restaurant" or similar
    details = json.dumps({"placed_at": "2025-01-01T12:00:00"})
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], details))
    conn.close()

    resp = client.get("/api/insights_data")
    data = resp.get_json()
    text_list = data["insights"]
    # We check if the Loyalist string is present
    assert any("Loyalist" in t for t in text_list)

# --- Generated Menu Integration ---

def test_generated_menu_parsing_safe(client, login_session, seed_minimal_data, temp_db_path):
    """Ensure API works even if generated_menu field contains garbage."""
    conn = create_connection(temp_db_path)
    execute_query(conn, 'UPDATE "User" SET generated_menu="THIS IS NOT VALID JSON" WHERE usr_id=?', (seed_minimal_data["usr_id"],))
    conn.close()

    resp = client.get("/api/insights_data")
    assert resp.status_code == 200
    # Should simply proceed without crashing
    
def test_generated_menu_valid_data(client, login_session, seed_minimal_data, temp_db_path):
    """Ensure API accepts valid generated menu string."""
    conn = create_connection(temp_db_path)
    # Format: [YYYY-MM-DD, ITEM_ID, MEAL_NUM]
    valid_menu = "[2025-01-01, 1, 1], [2025-01-01, 2, 2]"
    execute_query(conn, 'UPDATE "User" SET generated_menu=? WHERE usr_id=?', (valid_menu, seed_minimal_data["usr_id"]))
    conn.close()

    resp = client.get("/api/insights_data")
    assert resp.status_code == 200

# --- Error Handling ---

def test_user_deleted_during_session(client, login_session, seed_minimal_data, temp_db_path):
    """Test behavior if user session exists but DB row is deleted."""
    conn = create_connection(temp_db_path)
    execute_query(conn, 'DELETE FROM "User" WHERE usr_id=?', (seed_minimal_data["usr_id"],))
    conn.close()

    resp = client.get("/api/insights_data")
    # Should probably return 404 or 401 based on implementation
    assert resp.status_code in (404, 401)
    if resp.is_json:
        assert "User not found" in resp.get_json().get("error", "")

def test_activity_by_day_sorting(client, login_session, seed_minimal_data, temp_db_path):
    """Verify days are ordered correctly (Monday first)."""
    conn = create_connection(temp_db_path)
    # CLEANUP
    execute_query(conn, 'DELETE FROM "Order" WHERE usr_id=?', (seed_minimal_data["usr_id"],))

    # Add an order on a Monday (2025-01-06)
    d_mon = json.dumps({"placed_at": "2025-01-06T12:00:00"})
    # Add an order on a Sunday (2025-01-05)
    d_sun = json.dumps({"placed_at": "2025-01-05T12:00:00"})
    
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], d_mon))
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details) VALUES (?,?,?)', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], d_sun))
    conn.close()
    
    resp = client.get("/api/insights_data")
    data = resp.get_json()
    
    labels = data["charts"]["activity_by_day"]["labels"]
    counts = data["charts"]["activity_by_day"]["data"]
    
    assert labels[0] == "Monday"
    assert labels[6] == "Sunday"
    
    assert counts[0] == 1 # Monday
    assert counts[6] == 1 # Sunday