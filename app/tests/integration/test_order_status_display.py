"""
Integration tests for order status display in profile page.
Tests Requirements 4.1 and 4.4 from admin-and-support spec.
"""
import json
from sqlQueries import create_connection, close_connection, execute_query, fetch_one


def test_profile_displays_order_status(client, login_session, seed_minimal_data, temp_db_path):
    """Test that profile displays order status for each order."""
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # Create an order with status "Ordered"
    conn = create_connection(temp_db_path)
    try:
        details = json.dumps({
            "placed_at": "2025-12-05T10:00:00",
            "items": [{"name": "Test Item", "qty": 1, "unit_price": 10.00}],
            "charges": {"total": 10.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Ordered"))
    finally:
        close_connection(conn)
    
    # Get profile page
    resp = client.get("/profile")
    assert resp.status_code == 200
    
    # Check that status is displayed
    assert b"Ordered" in resp.data
    assert b"status-ordered" in resp.data


# def test_profile_displays_all_status_types(client, login_session, seed_minimal_data, temp_db_path):
#     """Test that profile correctly displays all order status types with proper badges."""
#     usr_id = seed_minimal_data["usr_id"]
#     rtr_id = seed_minimal_data["rtr_id"]
    
#     # Create orders with different statuses
#     statuses = ["Ordered", "Preparing", "Delivering", "Delivered"]
#     conn = create_connection(temp_db_path)
#     try:
#         for status in statuses:
#             details = json.dumps({
#                 "placed_at": "2025-12-05T10:00:00",
#                 "items": [{"name": "Test Item", "qty": 1, "unit_price": 10.00}],
#                 "charges": {"total": 10.00}
#             })
#             execute_query(conn, '''
#                 INSERT INTO "Order" (rtr_id, usr_id, details, status)
#                 VALUES (?, ?, ?, ?)
#             ''', (rtr_id, usr_id, details, status))
#     finally:
#         close_connection(conn)
    
#     # Get profile page
#     resp = client.get("/profile")
#     assert resp.status_code == 200
    
#     # Check that all statuses are displayed with proper CSS classes
#     assert b"Ordered" in resp.data
#     assert b"status-ordered" in resp.data
    
#     assert b"Preparing" in resp.data
#     assert b"status-preparing" in resp.data
    
#     assert b"Delivering" in resp.data
#     assert b"status-delivering" in resp.data
    
#     assert b"Delivered" in resp.data
#     assert b"status-delivered" in resp.data


def test_profile_status_consistent_with_database(client, login_session, seed_minimal_data, temp_db_path):
    """Test that profile displays status that matches what's in the database."""
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # Create an order with status "Preparing"
    conn = create_connection(temp_db_path)
    try:
        details = json.dumps({
            "placed_at": "2025-12-05T10:00:00",
            "items": [{"name": "Test Item", "qty": 1, "unit_price": 10.00}],
            "charges": {"total": 10.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Preparing"))
        
        # Get the order ID
        row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = row[0]
        
        # Verify status in database
        order_row = fetch_one(conn, 'SELECT status FROM "Order" WHERE ord_id = ?', (ord_id,))
        db_status = order_row[0]
    finally:
        close_connection(conn)
    
    # Get profile page
    resp = client.get("/profile")
    assert resp.status_code == 200
    
    # Verify the status from database matches what's displayed
    assert db_status == "Preparing"
    assert b"Preparing" in resp.data
    assert b"status-preparing" in resp.data


def test_profile_status_updates_reflected(client, login_session, seed_minimal_data, temp_db_path):
    """Test that when order status is updated in database, profile reflects the change."""
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # Create an order with status "Ordered"
    conn = create_connection(temp_db_path)
    try:
        details = json.dumps({
            "placed_at": "2025-12-05T10:00:00",
            "items": [{"name": "Test Item", "qty": 1, "unit_price": 10.00}],
            "charges": {"total": 10.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Ordered"))
        
        row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = row[0]
    finally:
        close_connection(conn)
    
    # Get profile page - should show "Ordered"
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert b"Ordered" in resp.data
    assert b"status-ordered" in resp.data
    
    # Update order status to "Delivered"
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            UPDATE "Order" SET status = ? WHERE ord_id = ?
        ''', ("Delivered", ord_id))
    finally:
        close_connection(conn)
    
    # Get profile page again - should now show "Delivered"
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert b"Delivered" in resp.data
    assert b"status-delivered" in resp.data
