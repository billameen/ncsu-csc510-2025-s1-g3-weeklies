"""
Integration tests for the admin dashboard route.

Tests the /admin route which displays orders grouped by status
and support tickets sorted by priority.
"""
import json
from datetime import datetime, timedelta
from sqlQueries import create_connection, close_connection, execute_query, fetch_one


def test_admin_dashboard_renders(client, seed_minimal_data, admin_session):
    """Test that the admin dashboard route renders successfully."""
    response = client.get("/admin")
    assert response.status_code == 200


def test_admin_dashboard_with_orders(client, seed_minimal_data, admin_session, temp_db_path):
    """Test that admin dashboard displays orders grouped by status."""
    # Create some test orders
    conn = create_connection(temp_db_path)
    try:
        usr_id = seed_minimal_data["usr_id"]
        rtr_id = seed_minimal_data["rtr_id"]
        
        # Create orders with different statuses
        now = datetime.now()
        
        # Order 1: Ordered status
        details1 = json.dumps({
            "placed_at": now.isoformat(),
            "charges": {"total": 25.99}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details1, "Ordered"))
        
        # Order 2: Preparing status
        details2 = json.dumps({
            "placed_at": now.isoformat(),
            "charges": {"total": 35.50}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details2, "Preparing"))
        
        # Order 3: Old order (should be filtered out)
        old_date = (now - timedelta(days=10)).isoformat()
        details3 = json.dumps({
            "placed_at": old_date,
            "charges": {"total": 15.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details3, "Delivered"))
        
    finally:
        close_connection(conn)
    
    # Get admin dashboard
    response = client.get("/admin")
    assert response.status_code == 200
    
    # Check that recent orders are present
    assert b"$25.99" in response.data
    assert b"$35.50" in response.data
    
    # Old order should not be present (filtered by 7 days)
    assert b"$15.00" not in response.data


def test_admin_dashboard_with_tickets(client, seed_minimal_data, admin_session, temp_db_path):
    """Test that admin dashboard displays support tickets sorted by status."""
    # Create some test tickets
    conn = create_connection(temp_db_path)
    try:
        usr_id = seed_minimal_data["usr_id"]
        rtr_id = seed_minimal_data["rtr_id"]
        
        # Create an order first
        details = json.dumps({
            "placed_at": datetime.now().isoformat(),
            "charges": {"total": 20.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')
        ord_id = ord_row[0]
        
        # Create tickets with different statuses in reverse order to test sorting
        # Insert in order: Resolved, Closed, In Progress, Open
        # Expected display order: Open, In Progress, Resolved, Closed
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr_id, ord_id, "Wrong order", "Resolved", "2025-12-05 10:00:00"))
        
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr_id, ord_id, "Issue closed", "Closed", "2025-12-05 11:00:00"))
        
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr_id, ord_id, "Missing item", "In Progress", "2025-12-05 12:00:00"))
        
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr_id, ord_id, "Food was cold", "Open", "2025-12-05 13:00:00"))
        
    finally:
        close_connection(conn)
    
    # Get admin dashboard
    response = client.get("/admin")
    assert response.status_code == 200
    
    # Check that tickets are present
    assert b"Food was cold" in response.data
    assert b"Missing item" in response.data
    assert b"Wrong order" in response.data
    assert b"Issue closed" in response.data
    
    # Verify sorting order: Open should appear before In Progress, which should appear before Resolved, which should appear before Closed
    html = response.data.decode('utf-8')
    open_pos = html.find("Food was cold")
    in_progress_pos = html.find("Missing item")
    resolved_pos = html.find("Wrong order")
    closed_pos = html.find("Issue closed")
    
    # Assert that positions follow the expected order
    assert open_pos < in_progress_pos, "Open tickets should appear before In Progress tickets"
    assert in_progress_pos < resolved_pos, "In Progress tickets should appear before Resolved tickets"
    assert resolved_pos < closed_pos, "Resolved tickets should appear before Closed tickets"


def test_admin_dashboard_empty_state(client, seed_minimal_data, admin_session):
    """Test that admin dashboard handles empty state (no orders or tickets)."""
    response = client.get("/admin")
    assert response.status_code == 200
    # Should render without errors even with no data


def test_admin_dashboard_tickets_sorted_by_created_at_within_status(client, seed_minimal_data, admin_session, temp_db_path):
    """Test that tickets within the same status are sorted by created_at DESC (newest first)."""
    conn = create_connection(temp_db_path)
    try:
        usr_id = seed_minimal_data["usr_id"]
        rtr_id = seed_minimal_data["rtr_id"]
        
        # Create an order first
        details = json.dumps({
            "placed_at": datetime.now().isoformat(),
            "charges": {"total": 20.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')
        ord_id = ord_row[0]
        
        # Create multiple tickets with the same status but different timestamps
        # Insert in chronological order, but expect reverse order in display
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr_id, ord_id, "Oldest open ticket", "Open", "2025-12-05 10:00:00"))
        
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr_id, ord_id, "Middle open ticket", "Open", "2025-12-05 11:00:00"))
        
        execute_query(conn, '''
            INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr_id, ord_id, "Newest open ticket", "Open", "2025-12-05 12:00:00"))
        
    finally:
        close_connection(conn)
    
    # Get admin dashboard
    response = client.get("/admin")
    assert response.status_code == 200
    
    # Verify that within the Open status, tickets are sorted by created_at DESC
    html = response.data.decode('utf-8')
    newest_pos = html.find("Newest open ticket")
    middle_pos = html.find("Middle open ticket")
    oldest_pos = html.find("Oldest open ticket")
    
    # Assert that newest appears before middle, which appears before oldest
    assert newest_pos < middle_pos, "Newest ticket should appear before middle ticket"
    assert middle_pos < oldest_pos, "Middle ticket should appear before oldest ticket"


def test_admin_dashboard_ticket_pagination(client, seed_minimal_data, admin_session, temp_db_path):
    """Test that admin dashboard paginates tickets correctly (20 per page)."""
    conn = create_connection(temp_db_path)
    try:
        # Delete all existing tickets to ensure clean state
        execute_query(conn, 'DELETE FROM Ticket')
        
        usr_id = seed_minimal_data["usr_id"]
        rtr_id = seed_minimal_data["rtr_id"]
        
        # Create an order first
        details = json.dumps({
            "placed_at": datetime.now().isoformat(),
            "charges": {"total": 20.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')
        ord_id = ord_row[0]
        
        # Create 25 tickets to test pagination (should span 2 pages)
        for i in range(25):
            execute_query(conn, '''
                INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (usr_id, ord_id, f"Test ticket {i+1}", "Open", f"2025-12-05 {10+i//10}:{i%10}:00"))
        
    finally:
        close_connection(conn)
    
    # Test page 1 (should show 20 tickets)
    response = client.get("/admin?page=1")
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    
    # Check pagination info is present
    assert "Showing page 1 of 2" in html
    assert "25 total tickets" in html
    
    # Check that pagination controls are present
    assert "Next →" in html
    assert "Previous" in html
    
    # Test page 2 (should show remaining 5 tickets)
    response = client.get("/admin?page=2")
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    
    # Check pagination info
    assert "Showing page 2 of 2" in html
    
    # Test invalid page number (should default to page 1)
    response = client.get("/admin?page=0")
    assert response.status_code == 200
    
    response = client.get("/admin?page=-1")
    assert response.status_code == 200
    
    # Test page beyond total pages (should show last page)
    response = client.get("/admin?page=999")
    assert response.status_code == 200


def test_admin_dashboard_pagination_preserves_url(client, seed_minimal_data, admin_session, temp_db_path):
    """Test that pagination controls preserve the page parameter in URLs."""
    conn = create_connection(temp_db_path)
    try:
        # Delete all existing tickets to ensure clean state
        execute_query(conn, 'DELETE FROM Ticket')
        
        usr_id = seed_minimal_data["usr_id"]
        rtr_id = seed_minimal_data["rtr_id"]
        
        # Create an order
        details = json.dumps({
            "placed_at": datetime.now().isoformat(),
            "charges": {"total": 20.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')
        ord_id = ord_row[0]
        
        # Create 45 tickets to ensure 3 pages (20 + 20 + 5)
        for i in range(45):
            execute_query(conn, '''
                INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (usr_id, ord_id, f"Ticket {i+1}", "Open", f"2025-12-05 10:00:{i:02d}"))
        
    finally:
        close_connection(conn)
    
    # Get page 2
    response = client.get("/admin?page=2")
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    
    # Check that pagination links include page parameter
    assert 'href="/admin?page=1"' in html  # Previous button and page 1 link
    assert 'href="/admin?page=3"' in html  # Next button and page 3 link
    assert 'Showing page 2 of' in html  # Current page indicator


def test_admin_dashboard_no_pagination_with_few_tickets(client, seed_minimal_data, admin_session, temp_db_path):
    """Test that pagination controls are not shown when there are 20 or fewer tickets."""
    # First, clear any existing tickets to ensure clean state
    conn = create_connection(temp_db_path)
    try:
        # Delete all existing tickets
        execute_query(conn, 'DELETE FROM Ticket')
        
        usr_id = seed_minimal_data["usr_id"]
        rtr_id = seed_minimal_data["rtr_id"]
        
        # Create an order
        details = json.dumps({
            "placed_at": datetime.now().isoformat(),
            "charges": {"total": 20.00}
        })
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, details, "Ordered"))
        
        ord_row = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')
        ord_id = ord_row[0]
        
        # Create only 10 tickets (less than 20, so only 1 page)
        for i in range(10):
            execute_query(conn, '''
                INSERT INTO Ticket (usr_id, ord_id, message, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (usr_id, ord_id, f"Ticket {i+1}", "Open", f"2025-12-05 10:00:{i:02d}"))
        
    finally:
        close_connection(conn)
    
    # Get admin dashboard
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    
    # Pagination controls should not be present when there's only 1 page
    # Check that the actual pagination HTML div is not in the body
    # (CSS class definitions in <style> tags don't count)
    assert '<!-- Pagination Controls -->' in html  # Comment should be there
    # But the actual pagination div should not follow it
    pagination_comment_pos = html.find('<!-- Pagination Controls -->')
    next_section_pos = html.find('</section>', pagination_comment_pos)
    pagination_section = html[pagination_comment_pos:next_section_pos]
    # The pagination section should only contain the comment and whitespace, no actual pagination div
    assert '<div class="pagination">' not in pagination_section
