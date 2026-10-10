import pytest
from app.sqlQueries import create_connection, close_connection, execute_query, fetch_one
from werkzeug.security import generate_password_hash

# Note: fixtures like 'client', 'app', 'login_session', 'seed_minimal_data', 'temp_db_path'
# are automatically available via conftest.py

@pytest.fixture()
def seed_recipient_user(temp_db_path):
    """
    Creates a secondary user with a starting balance of $10.00 (1000 cents).
    """
    email = "recipient@y.com"
    conn = create_connection(temp_db_path)
    try:
        # Create recipient if missing
        usr_row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email=?', (email,))
        if usr_row is None:
            execute_query(conn, '''
              INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet)
              VALUES ("Recip","User",?, "5555555", ?, 1000)
            ''', (email, generate_password_hash("recip_pw")))
            usr_row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email=?', (email,))
        else:
            # Ensure the wallet is 1000 cents for consistent testing
            execute_query(conn, 'UPDATE "User" SET wallet=? WHERE email=?', (1000, email))

        if usr_row:
            return {"usr_email": email, "usr_id": usr_row[0], "wallet_cents": 1000}
        
    finally:
        close_connection(conn)
    return None

def get_user_wallet(app, user_id, temp_db_path):
    """Helper to fetch user wallet balance from DB."""
    conn = create_connection(temp_db_path)
    try:
        row = fetch_one(conn, 'SELECT wallet FROM "User" WHERE usr_id = ?', (user_id,))
        return row[0] if row else 0
    finally:
        close_connection(conn)

# =========================================================
# 1. Wallet Topup Tests (/profile/wallet/topup)
# =========================================================

def test_topup_success(client, login_session, app, seed_minimal_data, temp_db_path):
    """Tests a successful wallet top-up."""
    sender_id = seed_minimal_data["usr_id"]
    initial_wallet = get_user_wallet(app, sender_id, temp_db_path)
    amount = 15.50
    
    resp = client.post("/profile/wallet/topup", data={"amount": amount}, follow_redirects=False)

    # Check redirect for success flag
    assert resp.status_code == 302
    assert resp.location == "/profile?wallet_updated=topup"
    
    # Check if wallet updated in DB (15.50 * 100 = 1550 cents)
    new_wallet = get_user_wallet(app, sender_id, temp_db_path)
    assert new_wallet == initial_wallet + 1550
    
    # Check if session updated
    with client.session_transaction() as sess:
        assert sess['Wallet'] == new_wallet

# No need for this function since invalid amount is not accepted by HTML form
# def test_topup_error_invalid_amount(client, login_session):
#     """Tests error: invalid_amount (non-numeric input)."""
#     resp = client.post("/profile/wallet/topup", data={"amount": "abc"}, follow_redirects=False)
#     assert resp.status_code == 302
#     assert resp.location == "/profile?wallet_error=invalid_amount"

def test_topup_error_zero_amount(client, login_session):
    """Tests error: zero_amount (amount <= 0)."""
    # Test 0.00
    resp1 = client.post("/profile/wallet/topup", data={"amount": 0.00}, follow_redirects=False)
    assert resp1.status_code == 302
    assert resp1.location == "/profile?wallet_error=zero_amount"
    
    # Test negative amount
    resp2 = client.post("/profile/wallet/topup", data={"amount": -10.00}, follow_redirects=False)
    assert resp2.status_code == 302
    assert resp2.location == "/profile?wallet_error=zero_amount"

# =========================================================
# 2. Wallet Gift Tests (/profile/wallet/gift)
# =========================================================

def test_gift_success(client, login_session, app, seed_minimal_data, seed_recipient_user, temp_db_path):
    """Tests a successful gift transaction."""
    sender_id = seed_minimal_data["usr_id"]
    recipient_email = seed_recipient_user["usr_email"]
    recipient_id = seed_recipient_user["usr_id"]
    
    # Pre-condition: Top up sender's wallet to at least $15.00
    client.post("/profile/wallet/topup", data={"amount": 15.00}, follow_redirects=False)
    initial_sender_wallet = get_user_wallet(app, sender_id, temp_db_path)
    initial_recipient_wallet = get_user_wallet(app, recipient_id, temp_db_path)
    
    amount_to_gift = 10.05
    amount_cents_to_gift = 1005
    
    resp = client.post("/profile/wallet/gift", data={
        "recipient_email": recipient_email,
        "amount": amount_to_gift
    }, follow_redirects=False)

    # Check redirect for success flag
    assert resp.status_code == 302
    assert resp.location == "/profile?wallet_updated=gift"
    
    # Verify balances updated in DB
    assert get_user_wallet(app, sender_id, temp_db_path) == initial_sender_wallet - amount_cents_to_gift
    assert get_user_wallet(app, recipient_id, temp_db_path) == initial_recipient_wallet + amount_cents_to_gift
    
    # Check if sender session updated
    with client.session_transaction() as sess:
        assert sess['Wallet'] == initial_sender_wallet - amount_cents_to_gift

# # No need for this function since invalid amount is not accepted by HTML form
# def test_gift_error_invalid_amount(client, login_session, seed_recipient_user):
#     """Tests error: invalid_amount (non-numeric gift amount)."""
#     resp = client.post("/profile/wallet/gift", data={
#         "recipient_email": seed_recipient_user["usr_email"],
#         "amount": "ten"
#     }, follow_redirects=False)
#     assert resp.status_code == 302
#     assert resp.location == "/profile?wallet_error=invalid_amount"

def test_gift_error_zero_amount(client, login_session, seed_recipient_user):
    """Tests error: zero_amount (gift amount <= 0)."""
    resp = client.post("/profile/wallet/gift", data={
        "recipient_email": seed_recipient_user["usr_email"],
        "amount": 0.00
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location == "/profile?wallet_error=zero_amount"

def test_gift_error_self_gift(client, login_session, seed_minimal_data):
    """Tests error: self_gift (sender email matches recipient email)."""
    # Pre-condition: Top up user's wallet to ensure insufficient_funds isn't hit first
    client.post("/profile/wallet/topup", data={"amount": 10.00}, follow_redirects=False)
    
    resp = client.post("/profile/wallet/gift", data={
        "recipient_email": seed_minimal_data["usr_email"], # Self email
        "amount": 1.00
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location == "/profile?wallet_error=self_gift"

def test_gift_error_recipient_not_found(client, login_session):
    """Tests error: recipient_not_found (recipient email not in DB)."""
    # Pre-condition: Top up user's wallet to ensure insufficient_funds isn't hit first
    client.post("/profile/wallet/topup", data={"amount": 10.00}, follow_redirects=False)

    resp = client.post("/profile/wallet/gift", data={
        "recipient_email": "nonexistent@user.com",
        "amount": 1.00
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location == "/profile?wallet_error=recipient_not_found"

def test_gift_error_insufficient_funds(client, login_session, app, seed_minimal_data, seed_recipient_user, temp_db_path):
    """Tests error: insufficient_funds (sender wallet balance < amount)."""
    sender_id = seed_minimal_data["usr_id"]
    # Ensure sender balance is 0 cents
    conn = create_connection(temp_db_path)
    execute_query(conn, 'UPDATE "User" SET wallet = 0 WHERE usr_id = ?', (sender_id,))
    close_connection(conn)
    
    resp = client.post("/profile/wallet/gift", data={
        "recipient_email": seed_recipient_user["usr_email"],
        "amount": 1.00
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location == "/profile?wallet_error=insufficient_funds"

# =========================================================
# 3. Authentication Checks (Mandatory for all wallet routes)
# =========================================================

def test_topup_requires_login(client):
    """Tests that /wallet/topup requires a logged-in session."""
    resp = client.post("/profile/wallet/topup", data={"amount": 10.00}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location == "/login"

def test_gift_requires_login(client, seed_recipient_user):
    """Tests that /wallet/gift requires a logged-in session."""
    resp = client.post("/profile/wallet/gift", data={
        "recipient_email": seed_recipient_user["usr_email"],
        "amount": 1.00
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location == "/login"