"""
Integration tests for the support ticket submission endpoint.

Tests the POST /support/submit route which allows authenticated users
to report issues with their orders.
"""
import pytest
from sqlQueries import create_connection, close_connection, execute_query, fetch_one


def test_submit_ticket_success(client, temp_db_path, seed_minimal_data, login_session):
    """Test successful ticket submission with valid data."""
    # Create an order for the logged-in user
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit a ticket
    message = "My food arrived cold and the order was incomplete."
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': message},
                          follow_redirects=False)
    
    # Should redirect to profile with success message
    assert response.status_code in (302, 303)
    assert 'ticket_success=1' in response.location
    
    # Verify ticket was created in database
    conn = create_connection(temp_db_path)
    try:
        ticket_row = fetch_one(conn, '''
            SELECT ticket_id, usr_id, ord_id, message, status, response
            FROM Ticket WHERE ord_id = ?
        ''', (ord_id,))
        
        assert ticket_row is not None
        assert ticket_row[1] == seed_minimal_data["usr_id"]  # usr_id
        assert ticket_row[2] == ord_id  # ord_id
        assert ticket_row[3] == message  # message
        assert ticket_row[4] == "Open"  # status
        assert ticket_row[5] is None  # response (should be null initially)
    finally:
        close_connection(conn)


def test_submit_ticket_message_too_short(client, temp_db_path, seed_minimal_data, login_session):
    """Test ticket submission fails when message is less than 10 characters."""
    # Create an order for the logged-in user
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit a ticket with message that's too short (9 characters)
    short_message = "Too short"
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': short_message},
                          follow_redirects=False)
    
    # Should redirect to profile with error
    assert response.status_code in (302, 303)
    assert 'ticket_error=message_too_short' in response.location
    
    # Verify no ticket was created
    conn = create_connection(temp_db_path)
    try:
        ticket_row = fetch_one(conn, 'SELECT ticket_id FROM Ticket WHERE ord_id = ?', (ord_id,))
        assert ticket_row is None
    finally:
        close_connection(conn)


def test_submit_ticket_message_exactly_10_chars(client, temp_db_path, seed_minimal_data, login_session):
    """Test ticket submission succeeds with exactly 10 character message."""
    # Create an order for the logged-in user
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit a ticket with exactly 10 characters
    message = "1234567890"  # Exactly 10 characters
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': message},
                          follow_redirects=False)
    
    # Should succeed
    assert response.status_code in (302, 303)
    assert 'ticket_success=1' in response.location
    
    # Verify ticket was created
    conn = create_connection(temp_db_path)
    try:
        ticket_row = fetch_one(conn, 'SELECT message FROM Ticket WHERE ord_id = ?', (ord_id,))
        assert ticket_row is not None
        assert ticket_row[0] == message
    finally:
        close_connection(conn)


def test_submit_ticket_order_not_found(client, login_session):
    """Test ticket submission fails when order doesn't exist."""
    # Try to submit ticket for non-existent order
    response = client.post('/support/submit',
                          data={'ord_id': 99999, 'message': 'This order does not exist'},
                          follow_redirects=False)
    
    # Should redirect with error
    assert response.status_code in (302, 303)
    assert 'ticket_error=order_not_found' in response.location


def test_submit_ticket_order_belongs_to_different_user(client, temp_db_path, seed_minimal_data, login_session):
    """Test ticket submission fails when order belongs to a different user."""
    # Create another user
    conn = create_connection(temp_db_path)
    try:
        from werkzeug.security import generate_password_hash
        execute_query(conn, '''
            INSERT INTO "User" (first_name, last_name, email, phone, password_HS, wallet)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ("Other", "User", "other@example.com", "5555555", generate_password_hash("password"), 0))
        
        other_usr_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        other_usr_id = other_usr_row[0]
        
        # Create an order for the other user
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], other_usr_id, '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Try to submit ticket for other user's order (logged in as test@x.com)
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': 'This is not my order'},
                          follow_redirects=False)
    
    # Should redirect with unauthorized error
    assert response.status_code in (302, 303)
    assert 'ticket_error=unauthorized' in response.location
    
    # Verify no ticket was created
    conn = create_connection(temp_db_path)
    try:
        ticket_row = fetch_one(conn, 'SELECT ticket_id FROM Ticket WHERE ord_id = ?', (ord_id,))
        assert ticket_row is None
    finally:
        close_connection(conn)


def test_submit_ticket_invalid_order_id(client, login_session):
    """Test ticket submission fails with invalid order ID format."""
    # Try to submit with invalid order ID
    response = client.post('/support/submit',
                          data={'ord_id': 'invalid', 'message': 'Valid message here'},
                          follow_redirects=False)
    
    # Should redirect with error
    assert response.status_code in (302, 303)
    assert 'ticket_error=invalid_order' in response.location


def test_submit_ticket_missing_order_id(client, login_session):
    """Test ticket submission fails when order ID is missing."""
    response = client.post('/support/submit',
                          data={'message': 'Valid message here'},
                          follow_redirects=False)
    
    # Should redirect with error
    assert response.status_code in (302, 303)
    assert 'ticket_error=invalid_order' in response.location


def test_submit_ticket_empty_message(client, temp_db_path, seed_minimal_data, login_session):
    """Test ticket submission fails with empty message."""
    # Create an order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit with empty message
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': ''},
                          follow_redirects=False)
    
    # Should redirect with error
    assert response.status_code in (302, 303)
    assert 'ticket_error=message_too_short' in response.location


def test_submit_ticket_whitespace_only_message(client, temp_db_path, seed_minimal_data, login_session):
    """Test ticket submission fails with whitespace-only message."""
    # Create an order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit with whitespace-only message (gets stripped to empty)
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': '     '},
                          follow_redirects=False)
    
    # Should redirect with error
    assert response.status_code in (302, 303)
    assert 'ticket_error=message_too_short' in response.location


def test_submit_ticket_not_authenticated(client, temp_db_path, seed_minimal_data):
    """Test ticket submission requires authentication."""
    # Create an order (without logging in)
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Try to submit without being logged in
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': 'Valid message here'},
                          follow_redirects=False)
    
    # Should redirect to login
    assert response.status_code in (302, 303)
    assert '/login' in response.location


def test_submit_ticket_timestamps_set(client, temp_db_path, seed_minimal_data, login_session):
    """Test that created_at and updated_at timestamps are set automatically."""
    # Create an order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit ticket
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': 'Valid message here'},
                          follow_redirects=False)
    
    assert response.status_code in (302, 303)
    
    # Verify timestamps are set
    conn = create_connection(temp_db_path)
    try:
        ticket_row = fetch_one(conn, '''
            SELECT created_at, updated_at FROM Ticket WHERE ord_id = ?
        ''', (ord_id,))
        
        assert ticket_row is not None
        assert ticket_row[0] is not None  # created_at
        assert ticket_row[1] is not None  # updated_at
        # Initially, created_at and updated_at should be the same
        assert ticket_row[0] == ticket_row[1]
    finally:
        close_connection(conn)


def test_submit_ticket_long_message(client, temp_db_path, seed_minimal_data, login_session):
    """Test ticket submission with a very long message."""
    # Create an order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit with very long message (500 characters)
    long_message = "A" * 500
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': long_message},
                          follow_redirects=False)
    
    # Should succeed
    assert response.status_code in (302, 303)
    assert 'ticket_success=1' in response.location
    
    # Verify full message was stored
    conn = create_connection(temp_db_path)
    try:
        ticket_row = fetch_one(conn, 'SELECT message FROM Ticket WHERE ord_id = ?', (ord_id,))
        assert ticket_row is not None
        assert ticket_row[0] == long_message
        assert len(ticket_row[0]) == 500
    finally:
        close_connection(conn)


def test_submit_multiple_tickets_same_order(client, temp_db_path, seed_minimal_data, login_session):
    """Test that multiple tickets can be submitted for the same order."""
    # Create an order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit first ticket
    response1 = client.post('/support/submit',
                           data={'ord_id': ord_id, 'message': 'First issue with this order'},
                           follow_redirects=False)
    assert response1.status_code in (302, 303)
    assert 'ticket_success=1' in response1.location
    
    # Submit second ticket for same order
    response2 = client.post('/support/submit',
                           data={'ord_id': ord_id, 'message': 'Second issue with same order'},
                           follow_redirects=False)
    assert response2.status_code in (302, 303)
    assert 'ticket_success=1' in response2.location
    
    # Verify both tickets exist
    conn = create_connection(temp_db_path)
    try:
        from sqlQueries import fetch_all
        tickets = fetch_all(conn, 'SELECT ticket_id, message FROM Ticket WHERE ord_id = ?', (ord_id,))
        assert len(tickets) == 2
        messages = [t[1] for t in tickets]
        assert 'First issue with this order' in messages
        assert 'Second issue with same order' in messages
    finally:
        close_connection(conn)


def test_submit_ticket_special_characters_in_message(client, temp_db_path, seed_minimal_data, login_session):
    """Test ticket submission with special characters in message."""
    # Create an order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"], '{"test": "data"}', "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        ord_id = ord_row[0]
    finally:
        close_connection(conn)
    
    # Submit with special characters
    special_message = "Food had issues: <script>alert('xss')</script> & \"quotes\" 'apostrophes' 100% bad!"
    response = client.post('/support/submit',
                          data={'ord_id': ord_id, 'message': special_message},
                          follow_redirects=False)
    
    # Should succeed
    assert response.status_code in (302, 303)
    assert 'ticket_success=1' in response.location
    
    # Verify message was stored correctly (not sanitized/escaped in DB)
    conn = create_connection(temp_db_path)
    try:
        ticket_row = fetch_one(conn, 'SELECT message FROM Ticket WHERE ord_id = ?', (ord_id,))
        assert ticket_row is not None
        assert ticket_row[0] == special_message
    finally:
        close_connection(conn)
