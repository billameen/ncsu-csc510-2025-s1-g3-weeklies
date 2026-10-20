import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wallet_helpers
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import json
import tempfile
import contextlib
import types
import pytest
import sqlite3

# from playwright.sync_api import sync_playwright

# Import your app module
import Flask_app as Flask_app

# Import your DB helpers
from sqlQueries import create_connection, close_connection, execute_query, fetch_one, fetch_all

from typing import Any, Optional, Sequence, Tuple

def expect_one(row: Optional[Sequence[Any]], err: str) -> Any:
    """Assert there is exactly one row and return first column; helpful for type checkers."""
    if row is None:
        raise AssertionError(err)
    return row[0]

# ---- SCHEMA (from your __main__ docstring) ----
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS "User" (
  usr_id INTEGER PRIMARY KEY AUTOINCREMENT,
  first_name TEXT, last_name TEXT, email TEXT UNIQUE, phone TEXT,
  password_HS TEXT, wallet INTEGER, preferences TEXT, allergies TEXT, generated_menu TEXT,
  is_admin INTEGER DEFAULT 0, daily_calorie_target INTEGER, weekly_budget_cents INTEGER
);

CREATE TABLE IF NOT EXISTS "Restaurant" (
  rtr_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, description TEXT, phone TEXT, email TEXT, password_HS TEXT,
  address TEXT, city TEXT, state TEXT, zip TEXT, hours TEXT, status TEXT
);

CREATE TABLE IF NOT EXISTS "MenuItem" (
  itm_id INTEGER PRIMARY KEY AUTOINCREMENT,
  rtr_id INTEGER, name TEXT, description TEXT, price INTEGER, calories INTEGER,
  instock INTEGER NOT NULL DEFAULT 1, restock TEXT, allergens TEXT
);

CREATE TABLE IF NOT EXISTS "Order" (
  ord_id INTEGER PRIMARY KEY AUTOINCREMENT,
  rtr_id INTEGER, usr_id INTEGER, details TEXT, status TEXT
);

CREATE TABLE IF NOT EXISTS "Review" (
  rev_id INTEGER PRIMARY KEY AUTOINCREMENT,
  rtr_id INTEGER, usr_id INTEGER, title TEXT, rating INTEGER, description TEXT
);

CREATE TABLE IF NOT EXISTS "Ticket" (
  ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
  usr_id INTEGER NOT NULL,
  ord_id INTEGER NOT NULL,
  message TEXT NOT NULL,
  response TEXT,
  status TEXT NOT NULL DEFAULT 'Open',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (usr_id) REFERENCES User(usr_id),
  FOREIGN KEY (ord_id) REFERENCES "Order"(ord_id)
);
"""

@pytest.fixture(scope="session")
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    with contextlib.suppress(OSError):
        os.remove(path)

@pytest.fixture(scope="session")
def app(temp_db_path):
    import Flask_app as Flask_app
    Flask_app.db_file = temp_db_path
    Flask_app.app.config["SECRET_KEY"] = "test-secret"
    Flask_app.app.config["TESTING"] = True

    # Build schema (supports multiple statements)
    conn = create_connection(temp_db_path)
    if conn is None:                      # <-- guard for type checker + safety
        conn = sqlite3.connect(temp_db_path)
    try:
        conn.executescript(SCHEMA_SQL)    # <-- executes all CREATE TABLEs
        import ledger
        ledger.ensure_schema(conn)       # wallet ledger tables (M2)
        conn.commit()
    finally:
        close_connection(conn)

    return Flask_app.app

@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c

# ---------- Seeding helpers ----------

def _hash_pw(raw="password"):
    # re-use werkzeug imported inside Flask_app
    from werkzeug.security import generate_password_hash
    return generate_password_hash(raw)

@pytest.fixture()
def seed_minimal_data(temp_db_path):
    """Create one restaurant, two items in stock, and one user. Idempotent across tests."""
    conn = create_connection(temp_db_path)
    try:
        # --- Restaurant (insert if missing) ---
        # Looked up by name: other fixtures add restaurants to the shared DB, and picking
        # whichever came first would make the seeded items depend on test order.
        rtr_row = fetch_one(conn, "SELECT rtr_id FROM Restaurant WHERE name = 'Cafe One' ORDER BY rtr_id LIMIT 1")
        if rtr_row is None:
            execute_query(conn, '''
              INSERT INTO "Restaurant"(name,address,city,state,zip,status)
              VALUES ("Cafe One","123 Main","Raleigh","NC","27606","open")
            ''')
            rtr_row = fetch_one(conn, "SELECT rtr_id FROM Restaurant WHERE name = 'Cafe One' ORDER BY rtr_id LIMIT 1")
        rtr_id = expect_one(rtr_row, "Expected at least one Restaurant row after seeding")

        # --- Menu items (ensure two exist for that restaurant) ---
        count_row = fetch_one(conn, 'SELECT COUNT(*) FROM "MenuItem" WHERE rtr_id=?', (rtr_id,))
        count = (count_row[0] if count_row else 0) or 0
        if count < 2:
            # Insert only the missing ones
            execute_query(conn, '''
              INSERT INTO "MenuItem"(rtr_id,name,description,price,calories,instock,allergens)
              VALUES (?, "Pasta", "Delicious", 1299, 600, 1, "wheat")
            ''', (rtr_id,))
            execute_query(conn, '''
              INSERT INTO "MenuItem"(rtr_id,name,description,price,calories,instock,allergens)
              VALUES (?, "Salad", "Fresh", 899, 250, 1, "nuts")
            ''', (rtr_id,))

        # --- User (upsert: create if missing; else ensure known password) ---
        email = "test@x.com"
        usr_row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email=?', (email,))
        if usr_row is None:
            execute_query(conn, '''
              INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies,generated_menu)
              VALUES ("Test","User",?, "5551234", ?, 0, "", "", "[2025-11-02,1,3]")
            ''', (email, _hash_pw("secret123")))
            usr_row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email=?', (email,))
        else:
            # make sure password matches what tests use
            execute_query(conn, 'UPDATE "User" SET password_HS=? WHERE email=?',
                          (_hash_pw("secret123"), email))

        usr_id = expect_one(usr_row, "Expected seeded user 'test@x.com'")

    finally:
        close_connection(conn)

    return {"usr_email": "test@x.com", "usr_id": usr_id, "rtr_id": rtr_id}

@pytest.fixture()
def login_session(client, seed_minimal_data):
    """Log in the seeded user by simulating POST /login."""
    resp = client.post("/login", data={"email": "test@x.com", "password": "secret123"}, follow_redirects=False)
    assert resp.status_code in (302, 303)
    return True

@pytest.fixture()
def admin_session(client, seed_minimal_data, temp_db_path):
    """Log in as an admin user."""
    conn = create_connection(temp_db_path)
    try:
        # Create admin user if doesn't exist
        admin_email = "admin@test.com"
        admin_row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email=?', (admin_email,))
        if admin_row is None:
            execute_query(conn, '''
              INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,is_admin)
              VALUES ("Admin","User",?, "5550000", ?, 10000, 1)
            ''', (admin_email, _hash_pw("admin123")))
        else:
            # Ensure user is admin
            execute_query(conn, 'UPDATE "User" SET is_admin=1, password_HS=? WHERE email=?',
                          (_hash_pw("admin123"), admin_email))
    finally:
        close_connection(conn)
    
    # Log in as admin
    resp = client.post("/login", data={"email": admin_email, "password": "admin123"}, follow_redirects=False)
    assert resp.status_code in (302, 303)
    return True

@pytest.fixture(autouse=True)
def monkeypatch_pdf(monkeypatch):
    """Avoid calling real PDF generator; return dummy bytes."""
    def fake_pdf(db_path, ord_id):
        return b"%PDF-1.4\n%fake\n"
    monkeypatch.setattr("app.Flask_app.generate_order_receipt_pdf", fake_pdf, raising=True)

# =========================================================
# E2E Fixtures (Required for Playwright tests)
# =========================================================

# Note: These fixtures use standard pytest-playwright patterns.
# The 'browser' and 'browser_context' fixtures ensure the browser environment
# is set up once per test session or as needed.

@pytest.fixture(scope="session")
def browser():
    """Launches a Playwright Chromium browser instance once per test session."""
    # Note: Headless is typically True for CI. Set to False for local debugging.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()

@pytest.fixture(scope="session")
def browser_context(browser):
    """Creates a new isolated browser context for the session."""
    context = browser.new_context()
    yield context
    context.close()

@pytest.fixture(scope="function")
def page(browser_context):
    """
    The main fixture for E2E testing. Returns a Playwright Page instance
    for interacting with the web application for a single test function.
    """
    page = browser_context.new_page()
    yield page
    page.close()
    
# NOTE ON base_url: The E2E tests require a 'base_url' fixture.
# If you are using pytest-flask, the 'live_server' fixture usually provides this.
# If you are running your Flask app separately, uncomment and define the base_url manually:
@pytest.fixture(scope="session")
def base_url():
    # Ensure this matches the host:port where your Flask app is running (e.g., in a separate terminal)
    return "http://127.0.0.1:5000"
