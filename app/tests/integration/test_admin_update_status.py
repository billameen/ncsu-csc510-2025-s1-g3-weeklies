"""
Integration tests for the admin order status update endpoint.

Tests the POST /admin/update_status route which allows administrators
to update order statuses through the admin dashboard.
"""
import json
import pytest
from sqlQueries import create_connection, close_connection, execute_query, fetch_one


def test_update_status_success(client, temp_db_path, seed_minimal_data, admin_session):
    """Test successful order status update with valid transition."""
    # Create an order with status "Ordered"
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = row[0]
    finally:
        close_connection(conn)
    
    # Update status from Ordered to Preparing
    response = client.post('/admin/update_status',
                          data=json.dumps({"ord_id": ord_id, "new_status": "Preparing"}),
                          content_type='application/json')
    
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["ord_id"] == ord_id
    assert data["new_status"] == "Preparing"
    
    # Verify database was updated
    conn = create_connection(temp_db_path)
    try:
        row = fetch_one(conn, 'SELECT status FROM "Order" WHERE ord_id = ?', (ord_id,))
        assert row[0] == "Preparing"
    finally:
        close_connection(conn)


def test_update_status_invalid_order_id(client, admin_session):
    """Test updating status for non-existent order returns 404."""
    response = client.post('/admin/update_status',
                          data=json.dumps({"ord_id": 99999, "new_status": "Preparing"}),
                          content_type='application/json')
    
    assert response.status_code == 404
    data = response.get_json()
    assert data["ok"] is False
    assert "not found" in data["error"].lower()


def test_update_status_invalid_status_value(client, temp_db_path, seed_minimal_data, admin_session):
    """Test updating to invalid status returns 400."""
    # Create an order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = row[0]
    finally:
        close_connection(conn)
    
    # Try to update to invalid status
    response = client.post('/admin/update_status',
                          data=json.dumps({"ord_id": ord_id, "new_status": "InvalidStatus"}),
                          content_type='application/json')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert "invalid status" in data["error"].lower()


def test_update_status_invalid_transition(client, temp_db_path, seed_minimal_data, admin_session):
    """Test invalid status transition returns 400."""
    # Create an order with status "Delivered"
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Delivered"))
        
        row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = row[0]
    finally:
        close_connection(conn)
    
    # Try to transition from Delivered to Preparing (not allowed)
    response = client.post('/admin/update_status',
                          data=json.dumps({"ord_id": ord_id, "new_status": "Preparing"}),
                          content_type='application/json')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert "invalid transition" in data["error"].lower()


def test_update_status_missing_parameters(client, admin_session):
    """Test missing parameters returns 400."""
    # Missing new_status
    response = client.post('/admin/update_status',
                          data=json.dumps({"ord_id": 1}),
                          content_type='application/json')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    
    # Missing ord_id
    response = client.post('/admin/update_status',
                          data=json.dumps({"new_status": "Preparing"}),
                          content_type='application/json')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False


def test_update_status_non_json_request(client, admin_session):
    """Test non-JSON request returns 400."""
    response = client.post('/admin/update_status',
                          data="not json",
                          content_type='text/plain')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert "json" in data["error"].lower()


def test_update_status_valid_transitions(client, temp_db_path, seed_minimal_data, admin_session):
    """Test all valid status transitions work correctly."""
    transitions = [
        ("Ordered", "Preparing"),
        ("Ordered", "Delivered"),
        ("Preparing", "Delivering"),
        ("Preparing", "Delivered"),
        ("Delivering", "Delivered"),
    ]
    
    for current, new in transitions:
        # Create an order with current status
        conn = create_connection(temp_db_path)
        try:
            execute_query(conn, '''
                INSERT INTO "Order" (rtr_id, usr_id, details, status)
                VALUES (?, ?, ?, ?)
            ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', current))
            
            row = fetch_one(conn, 'SELECT last_insert_rowid()')
            ord_id = row[0]
        finally:
            close_connection(conn)
        
        # Update status
        response = client.post('/admin/update_status',
                              data=json.dumps({"ord_id": ord_id, "new_status": new}),
                              content_type='application/json')
        
        assert response.status_code == 200, f"Failed transition {current} -> {new}"
        data = response.get_json()
        assert data["ok"] is True
        assert data["new_status"] == new
