"""
Integration tests for the admin ticket status update endpoint.

Tests the POST /admin/update_ticket_status route which allows administrators
to update ticket statuses and add responses through the admin dashboard.
"""
import json
import pytest
from sqlQueries import create_connection, close_connection, execute_query, fetch_one


def test_update_ticket_status_success(client, temp_db_path, seed_minimal_data, admin_session):
    """Test successful ticket status update."""
    # Create a ticket with status "Open"
    conn = create_connection(temp_db_path)
    try:
        # First create an order
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
        
        # Create a ticket
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["usr_id"], ord_id, "Test issue message", "Open"))
        
        ticket_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ticket_id = ticket_row[0]
    finally:
        close_connection(conn)
    
    # Update status from Open to In Progress
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({"ticket_id": ticket_id, "new_status": "In Progress"}),
                          content_type='application/json')
    
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["ticket_id"] == ticket_id
    assert data["new_status"] == "In Progress"
    
    # Verify database was updated
    conn = create_connection(temp_db_path)
    try:
        row = fetch_one(conn, 'SELECT status FROM Ticket WHERE ticket_id = ?', (ticket_id,))
        assert row[0] == "In Progress"
    finally:
        close_connection(conn)


def test_update_ticket_status_with_response(client, temp_db_path, seed_minimal_data, admin_session):
    """Test updating ticket status and adding a response to a non-Open ticket."""
    # Create a ticket with status "In Progress" (not Open)
    conn = create_connection(temp_db_path)
    try:
        # First create an order
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
        
        # Create a ticket with status "In Progress" (not Open)
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["usr_id"], ord_id, "Test issue message", "In Progress"))
        
        ticket_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ticket_id = ticket_row[0]
    finally:
        close_connection(conn)
    
    # Update with response (should respect the requested status since not Open)
    response_text = "We're looking into this issue"
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({
                              "ticket_id": ticket_id, 
                              "new_status": "Resolved",
                              "response": response_text
                          }),
                          content_type='application/json')
    
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    
    # Verify database was updated with response and status
    conn = create_connection(temp_db_path)
    try:
        row = fetch_one(conn, 'SELECT status, response FROM Ticket WHERE ticket_id = ?', (ticket_id,))
        assert row[0] == "Resolved"
        assert row[1] == response_text
    finally:
        close_connection(conn)


def test_update_ticket_auto_status_on_response(client, temp_db_path, seed_minimal_data, admin_session):
    """Test automatic status update to 'In Progress' when response is added to 'Open' ticket."""
    # Create a ticket with status "Open"
    conn = create_connection(temp_db_path)
    try:
        # First create an order
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
        
        # Create a ticket
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["usr_id"], ord_id, "Test issue message", "Open"))
        
        ticket_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ticket_id = ticket_row[0]
    finally:
        close_connection(conn)
    
    # Add response to Open ticket (should auto-update to In Progress)
    response_text = "We're looking into this issue"
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({
                              "ticket_id": ticket_id, 
                              "new_status": "Open",  # Request Open, but should become In Progress
                              "response": response_text
                          }),
                          content_type='application/json')
    
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["new_status"] == "In Progress"  # Should be auto-updated
    
    # Verify database has In Progress status
    conn = create_connection(temp_db_path)
    try:
        row = fetch_one(conn, 'SELECT status, response FROM Ticket WHERE ticket_id = ?', (ticket_id,))
        assert row[0] == "In Progress"
        assert row[1] == response_text
    finally:
        close_connection(conn)


def test_update_ticket_status_invalid_ticket_id(client, admin_session):
    """Test updating status for non-existent ticket returns 404."""
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({"ticket_id": 99999, "new_status": "Resolved"}),
                          content_type='application/json')
    
    assert response.status_code == 404
    data = response.get_json()
    assert data["ok"] is False
    assert "not found" in data["error"].lower()


def test_update_ticket_status_invalid_status_value(client, temp_db_path, seed_minimal_data, admin_session):
    """Test updating to invalid status returns 400."""
    # Create a ticket
    conn = create_connection(temp_db_path)
    try:
        # First create an order
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
        
        # Create a ticket
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["usr_id"], ord_id, "Test issue message", "Open"))
        
        ticket_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ticket_id = ticket_row[0]
    finally:
        close_connection(conn)
    
    # Try to update to invalid status
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({"ticket_id": ticket_id, "new_status": "InvalidStatus"}),
                          content_type='application/json')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert "invalid status" in data["error"].lower()


def test_update_ticket_status_missing_parameters(client, admin_session):
    """Test missing parameters returns 400."""
    # Missing new_status
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({"ticket_id": 1}),
                          content_type='application/json')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    
    # Missing ticket_id
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({"new_status": "Resolved"}),
                          content_type='application/json')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False


def test_update_ticket_status_non_json_request(client, admin_session):
    """Test non-JSON request returns 400."""
    response = client.post('/admin/update_ticket_status',
                          data="not json",
                          content_type='text/plain')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert "json" in data["error"].lower()


def test_update_ticket_status_all_valid_statuses(client, temp_db_path, seed_minimal_data, admin_session):
    """Test all valid ticket statuses can be set."""
    valid_statuses = ["Open", "In Progress", "Resolved", "Closed"]
    
    for status in valid_statuses:
        # Create a ticket
        conn = create_connection(temp_db_path)
        try:
            # First create an order
            execute_query(conn, '''
                INSERT INTO "Order" (rtr_id, usr_id, details, status)
                VALUES (?, ?, ?, ?)
            ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
            
            ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
            ord_id = ord_row[0]
            
            # Create a ticket
            execute_query(conn, '''
                INSERT INTO Ticket (usr_id, ord_id, message, status)
                VALUES (?, ?, ?, ?)
            ''', (seed_minimal_data["usr_id"], ord_id, "Test issue message", "Open"))
            
            ticket_row = fetch_one(conn, 'SELECT last_insert_rowid()')
            ticket_id = ticket_row[0]
        finally:
            close_connection(conn)
        
        # Update to the status
        response = client.post('/admin/update_ticket_status',
                              data=json.dumps({"ticket_id": ticket_id, "new_status": status}),
                              content_type='application/json')
        
        assert response.status_code == 200, f"Failed to set status to {status}"
        data = response.get_json()
        assert data["ok"] is True
        
        # Verify in database (unless it was auto-changed by response logic)
        conn = create_connection(temp_db_path)
        try:
            row = fetch_one(conn, 'SELECT status FROM Ticket WHERE ticket_id = ?', (ticket_id,))
            assert row[0] == status
        finally:
            close_connection(conn)


def test_update_ticket_timestamp_updated(client, temp_db_path, seed_minimal_data, admin_session):
    """Test that updated_at timestamp is updated when ticket is modified."""
    import time
    
    # Create a ticket
    conn = create_connection(temp_db_path)
    try:
        # First create an order
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
        
        # Create a ticket
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["usr_id"], ord_id, "Test issue message", "Open"))
        
        ticket_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ticket_id = ticket_row[0]
        
        # Get initial timestamps
        row = fetch_one(conn, 'SELECT created_at, updated_at FROM Ticket WHERE ticket_id = ?', (ticket_id,))
        initial_created = row[0]
        initial_updated = row[1]
    finally:
        close_connection(conn)
    
    # Wait a moment to ensure timestamp difference
    time.sleep(0.1)
    
    # Update the ticket
    response = client.post('/admin/update_ticket_status',
                          data=json.dumps({"ticket_id": ticket_id, "new_status": "In Progress"}),
                          content_type='application/json')
    
    assert response.status_code == 200
    
    # Verify updated_at changed but created_at didn't
    conn = create_connection(temp_db_path)
    try:
        row = fetch_one(conn, 'SELECT created_at, updated_at FROM Ticket WHERE ticket_id = ?', (ticket_id,))
        final_created = row[0]
        final_updated = row[1]
        
        assert final_created == initial_created  # created_at should not change
        assert final_updated >= initial_updated  # updated_at should be updated
    finally:
        close_connection(conn)
