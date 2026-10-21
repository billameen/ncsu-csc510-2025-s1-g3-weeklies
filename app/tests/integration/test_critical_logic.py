# app/tests/integration/test_critical_logic.py

import json
from datetime import datetime
import pytest
from sqlQueries import create_connection, close_connection, execute_query, fetch_one
import ledger
from wallet_helpers import set_wallet_cents, wallet_cents, wallet_cents_by_email
from urllib.parse import parse_qs, urlsplit

# --- Helper to create a second user for gift/mixed-restaurant tests ---
@pytest.fixture
def seed_second_user(temp_db_path):
    """Create a second user for gifting tests."""
    email = "recipient@x.com"
    conn = create_connection(temp_db_path)
    try:
        # Create user if missing
        execute_query(conn, '''
            INSERT OR IGNORE INTO "User"(first_name,last_name,email,phone,password_HS,wallet)
            VALUES ("Recip","User",?, "5555555", ?, 10000)
        ''', (email, "hashed_pw"))
        # Get usr_id
        usr_row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email=?', (email,))
        usr_id = usr_row[0]
    finally:
        close_connection(conn)
    return {"usr_email": email, "usr_id": usr_id}

# --- Test 1: Atomic Order Placement Error ---
def test_order_post_fails_on_insufficient_funds(client, seed_minimal_data, login_session, temp_db_path):
    """
    Test 1/9: Verifies an order fails with insufficient funds (402) and ensures the wallet
    is not debited (atomic rollback).
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # --- CLEANUP: Remove any prior orders for this user so we start fresh ---
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, 'DELETE FROM "Order" WHERE usr_id = ?', (usr_id,))
    finally:
        close_connection(conn)
    
    # Get the ID of a MenuItem
    conn = create_connection(temp_db_path)
    try:
        item_row = fetch_one(conn, 'SELECT itm_id, price FROM "MenuItem" WHERE rtr_id = ? LIMIT 1', (rtr_id,))
        itm_id = item_row[0]
        # Item price is likely > 1 cent, so this should trigger insufficient funds
    finally:
        close_connection(conn)

    # 1. Set user's wallet balance low (e.g., $0.01 = 1 cent)
    low_balance_cents = 1
    set_wallet_cents(temp_db_path, usr_id, low_balance_cents)

    # Re-login to update session wallet value
    client.post("/login", data={"email": seed_minimal_data["usr_email"], "password": "secret123"})
    
    # Payload for a small order (price + fixed fees/tax will be > 1 cent)
    order_payload = {
        "restaurant_id": rtr_id,
        "items": [{"itm_id": itm_id, "qty": 1}],
        "tip": 0.0,
        "delivery_type": "pickup", 
    }

    # 2. Attempt to place order
    response = client.post("/order", json=order_payload)
    
    # 3. Assert failure and status code
    assert response.status_code == 402
    data = response.get_json()
    assert data["ok"] == False
    assert data["error"] == "insufficient_funds"

    # 4. Assert that wallet balance is UNCHANGED and NO order was placed (atomic rollback)
    conn = create_connection(temp_db_path)
    try:
        final_wallet_cents = wallet_cents(temp_db_path, usr_id)
        order_count_row = fetch_one(conn, 'SELECT COUNT(*) FROM "Order" WHERE usr_id = ?', (usr_id,))
        order_count = order_count_row[0]
    finally:
        close_connection(conn)
        
    assert final_wallet_cents == low_balance_cents, "Wallet balance should not change on insufficient funds (atomic failure)"
    assert order_count == 0, "No order should be recorded in the DB on atomic failure"

# --- Test 2: Review Submission Failure - Order Not Delivered ---
def test_review_submit_fails_if_order_not_delivered(client, seed_minimal_data, login_session, temp_db_path):
    """
    Test 2/9: Verifies review submission fails (403) if the associated order status is not 'Delivered'.
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # Create an order with status 'Preparing'
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, "{}", "Preparing"))
        
        ord_id = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')[0]
    finally:
        close_connection(conn)
        
    # Attempt to submit review for the 'Preparing' order
    response = client.post("/review/submit", json={
        "restaurant_id": rtr_id, 
        "rating": 5, 
        "title": "Great", 
        "comment": "Nice meal", 
        "order_id": ord_id
    })
    
    # Assert failure
    assert response.status_code == 403
    assert response.get_json()["error"] == "Order not delivered or unauthorized"
    
# --- Test 3: Review Submission Failure - Duplicate Review ---
def test_review_submit_fails_on_duplicate_review(client, seed_minimal_data, login_session, temp_db_path):
    """
    Test 3/9: Verifies review submission fails (409) if the user has already reviewed the restaurant.
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    conn = create_connection(temp_db_path)
    try:
        # Clean up potential previous reviews before running this test
        execute_query(conn, 'DELETE FROM "Review" WHERE usr_id = ? AND rtr_id = ?', (usr_id, rtr_id))

        # 1. Create a dummy 'delivered' order
        execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Delivered")', (rtr_id, usr_id))
        ord_id = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')[0]
        
        # 2. Insert the initial review directly into the DB
        execute_query(conn, 'INSERT INTO "Review" (rtr_id, usr_id, title, rating, description) VALUES (?, ?, ?, ?, ?)', 
                      (rtr_id, usr_id, "First Review", 5, "I liked it the first time"))
        
        # Check initial review exists
        initial_count = fetch_one(conn, 'SELECT COUNT(*) FROM "Review" WHERE usr_id = ? AND rtr_id = ?', (usr_id, rtr_id))[0]
        assert initial_count == 1
        
    finally:
        close_connection(conn)
        
    # 3. Attempt to submit a second review
    response = client.post("/review/submit", json={
        "restaurant_id": rtr_id, 
        "rating": 4, 
        "title": "Second Review", 
        "comment": "Attempting to review again", 
        "order_id": ord_id
    })
    
    # 4. Assert failure and status code
    assert response.status_code == 409
    assert response.get_json()["error"] == "Restaurant already reviewed"
    
# --- Test 4: Review Submission Success ---
def test_review_submit_success_stores_review(client, seed_minimal_data, login_session, temp_db_path):
    """
    Test 4/9: Verifies successful review submission and checks DB state.
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # 1. Clean up potential previous reviews and create a dummy 'delivered' order
    conn = create_connection(temp_db_path)
    try:
        # Ensure a clean state by deleting any existing review for this user/restaurant pair
        execute_query(conn, 'DELETE FROM "Review" WHERE usr_id = ? AND rtr_id = ?', (usr_id, rtr_id))

        execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Delivered")', (rtr_id, usr_id))
        ord_id = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')[0]
    finally:
        close_connection(conn)
        
    review_data = {
        "restaurant_id": rtr_id, 
        "rating": 3, 
        "title": "Just okay", 
        "comment": "Room for improvement", 
        "order_id": ord_id
    }
    
    # 2. Submit the review
    response = client.post("/review/submit", json=review_data)
    
    # 3. Assert success
    assert response.status_code == 201
    assert response.get_json()["ok"] == True
    
    # 4. Assert review is in the DB
    conn = create_connection(temp_db_path)
    try:
        review_row = fetch_one(conn, 'SELECT title, rating, description FROM "Review" WHERE usr_id = ? AND rtr_id = ?', (usr_id, rtr_id))
        
        assert review_row is not None
        assert review_row[0] == review_data["title"]
        assert review_row[1] == review_data["rating"]
        assert review_row[2] == review_data["comment"]
        
    finally:
        close_connection(conn)


# --- Test 5: Admin Update Ticket Status - Auto In Progress ---
def test_admin_update_ticket_status_auto_in_progress(client, seed_minimal_data, admin_session, temp_db_path):
    """
    Test 5/9: Verifies that if a response is added to an 'Open' ticket, the status is automatically
    set to 'In Progress', even if the payload requested 'Open'.
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # 1. Create an 'Open' ticket
    conn = create_connection(temp_db_path)
    try:
        # Create dummy order for foreign key
        execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Ordered")', (rtr_id, usr_id))
        ord_id = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')[0]
        
        execute_query(conn, 'INSERT INTO Ticket (usr_id, ord_id, message, status) VALUES (?, ?, ?, ?)', 
                      (usr_id, ord_id, "Initial open message", "Open"))
        
        ticket_id = fetch_one(conn, 'SELECT ticket_id FROM Ticket ORDER BY ticket_id DESC LIMIT 1')[0]
    finally:
        close_connection(conn)
        
    # 2. Attempt to update it, providing a response but requesting status 'Open'
    response_text = "Acknowledged, checking into this now."
    payload = {
        "ticket_id": ticket_id,
        "new_status": "Open", # Intentionally setting to Open
        "response": response_text
    }
    
    response = client.post("/admin/update_ticket_status", json=payload)
    
    # 3. Assert success but with the *forced* status
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] == True
    assert data["new_status"] == "In Progress", "Status should be auto-set to 'In Progress' when response is added to 'Open'"
    
# --- Test 6: Admin Update Ticket Status - Preserves Status ---
def test_admin_update_ticket_status_preserves_status_if_not_open(client, seed_minimal_data, admin_session, temp_db_path):
    """
    Test 6/9: Verifies that if a response is added to a 'Resolved' ticket, the status logic is not
    triggered, and the requested status ('Closed') is honored.
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # 1. Create a 'Resolved' ticket
    conn = create_connection(temp_db_path)
    try:
        # Create dummy order for foreign key
        execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Ordered")', (rtr_id, usr_id))
        ord_id = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')[0]
        
        execute_query(conn, 'INSERT INTO Ticket (usr_id, ord_id, message, status) VALUES (?, ?, ?, ?)', 
                      (usr_id, ord_id, "Initial resolved message", "Resolved"))
        
        ticket_id = fetch_one(conn, 'SELECT ticket_id FROM Ticket ORDER BY ticket_id DESC LIMIT 1')[0]
    finally:
        close_connection(conn)
        
    # 2. Attempt to update it, providing a new response and requesting status 'Closed'
    response_text = "Final confirmation sent."
    requested_status = "Closed"
    payload = {
        "ticket_id": ticket_id,
        "new_status": requested_status,
        "response": response_text
    }
    
    response = client.post("/admin/update_ticket_status", json=payload)
    
    # 3. Assert success and the requested status is honored
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] == True
    assert data["new_status"] == requested_status, "Status should honor the requested status if current status is not 'Open'"
    
# --- Test 7: Wallet Gifting Atomicity Failure ---
def test_wallet_gift_fails_on_insufficient_funds_atomicity(client, seed_minimal_data, seed_second_user, login_session, temp_db_path):
    """
    Test 7/9: Verifies that a wallet gift transaction fails atomically if the sender
    has insufficient funds, and checks the correct redirect is issued.
    """
    sender_id = seed_minimal_data["usr_id"]
    recipient_email = seed_second_user["usr_email"]
    
    # 1. Set sender's wallet to $1.00 (100 cents)
    low_balance_cents = 100
    set_wallet_cents(temp_db_path, sender_id, low_balance_cents)
    sender_initial_wallet = wallet_cents(temp_db_path, sender_id)
    recipient_initial_wallet = wallet_cents_by_email(temp_db_path, recipient_email)
    
    # 2. Attempt to gift $50.00 (5000 cents)
    gift_amount = 50.00
    response = client.post("/profile/wallet/gift", data={
        "recipient_email": recipient_email,
        "amount": gift_amount
    }, follow_redirects=False)

    # 3. Assert failure and redirect URL
    assert response.status_code == 302 
    redirect_url = response.headers['Location']
    assert '/profile?wallet_error=insufficient_funds' in redirect_url, "Should redirect to profile with insufficient_funds error"

    # 4. Assert both wallets are UNCHANGED (atomic failure)
    sender_final_wallet = wallet_cents(temp_db_path, sender_id)
    recipient_final_wallet = wallet_cents_by_email(temp_db_path, recipient_email)

    assert sender_final_wallet == sender_initial_wallet, "Sender wallet should not be debited"
    assert recipient_final_wallet == recipient_initial_wallet, "Recipient wallet should not be credited"

# --- Test 8: Order Placement Logic - Mixed Restaurants ---
def test_order_post_fails_on_mixed_restaurant_items(client, seed_minimal_data, login_session, temp_db_path):
    """
    Test 8/9: Verifies that placing an order with items from multiple restaurants fails (400)
    to maintain data integrity.
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id_1 = seed_minimal_data["rtr_id"]
    
    conn = create_connection(temp_db_path)
    try:
        # 1. Create a second restaurant
        execute_query(conn, '''
          INSERT INTO "Restaurant"(name,address,city,status)
          VALUES ("Cafe Two","456 Back","Raleigh","open")
        ''')
        rtr_id_2 = fetch_one(conn, 'SELECT rtr_id FROM Restaurant ORDER BY rtr_id DESC LIMIT 1')[0]
        
        # 2. Create an item for the second restaurant
        execute_query(conn, '''
          INSERT INTO "MenuItem"(rtr_id,name,price,instock)
          VALUES (?, "Burger", 1500, 1)
        ''', (rtr_id_2,))
        item_2_id = fetch_one(conn, 'SELECT itm_id FROM "MenuItem" WHERE rtr_id = ? LIMIT 1', (rtr_id_2,))[0]
        
        # 3. Get an item from the first restaurant
        item_1_id = fetch_one(conn, 'SELECT itm_id FROM "MenuItem" WHERE rtr_id = ? LIMIT 1', (rtr_id_1,))[0]
        
    finally:
        close_connection(conn)

    # 4. Payload for an order attempting to buy items from R1 and R2
    order_payload = {
        "restaurant_id": rtr_id_1, # The main restaurant ID is R1
        "items": [
            {"itm_id": item_1_id, "qty": 1}, # Item from R1
            {"itm_id": item_2_id, "qty": 1}  # Item from R2 (mixed)
        ],
        "tip": 0.0,
        "delivery_type": "delivery", 
    }

    # 5. Attempt to place order
    response = client.post("/order", json=order_payload)
    
    # 6. Assert failure and error code
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] == False
    assert data["error"] == "mixed_restaurants"

# --- Test 9: Support Ticket Submission - Short Message ---
def test_support_submit_fails_on_short_message(client, seed_minimal_data, login_session, temp_db_path):
    """
    Test 9/9: Verifies that submitting a support ticket with a message shorter than 10 
    characters fails and redirects with a specific error flag.
    """
    usr_id = seed_minimal_data["usr_id"]
    rtr_id = seed_minimal_data["rtr_id"]
    
    # 1. Create a dummy order
    conn = create_connection(temp_db_path)
    try:
        execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Ordered")', (rtr_id, usr_id))
        ord_id = fetch_one(conn, 'SELECT ord_id FROM "Order" ORDER BY ord_id DESC LIMIT 1')[0]
        # Clean up existing tickets to ensure the expected ticket ID is manageable/zero
        execute_query(conn, 'DELETE FROM Ticket')
    finally:
        close_connection(conn)

    # 2. Attempt to submit ticket with a short message (9 characters - must be < 10)
    short_message = "Too brief" # Length 9
    
    response = client.post("/support/submit", data={
        "ord_id": ord_id,
        "message": short_message
    }, follow_redirects=False)

    # 3. Assert redirect to profile with error flag
    assert response.status_code == 302
    parts = urlsplit(response.headers['Location'])
    # Parse the query rather than matching raw text: url_for encodes spaces as '+'
    assert parts.path == '/profile'
    assert parse_qs(parts.query) == {
        'ticket_error': ['message_too_short'],
        'ord_id': [str(ord_id)],
        'message': [short_message],
    }

    # 4. Assert no ticket was created
    conn = create_connection(temp_db_path)
    try:
        ticket_count = fetch_one(conn, 'SELECT COUNT(*) FROM Ticket WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)
        
    assert ticket_count == 0, "Ticket should not be created with a short message"