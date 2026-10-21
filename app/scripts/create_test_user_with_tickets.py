"""
Script to create a test user with orders and support tickets.

Creates:
- 1 test user
- 4 orders for that user
- 2 support tickets for 2 different orders
"""

import sqlite3
import os
import sys
import json
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash


def get_db_path():
    """Get the path to the database file."""
    db_file = os.path.join(os.path.dirname(__file__), '..', 'CSC510_DB.db')
    return os.path.abspath(db_file)


def create_test_user(conn):
    """Create a test user and return the user ID."""
    cursor = conn.cursor()
    
    # Check if test user already exists
    test_email = "testuser@weeklies.com"
    cursor.execute("SELECT usr_id FROM User WHERE email = ?", (test_email,))
    existing_user = cursor.fetchone()
    
    if existing_user:
        print(f"⚠ Test user already exists with ID: {existing_user[0]}")
        return existing_user[0]
    
    # Create new test user
    password_hash = generate_password_hash("test123")
    
    cursor.execute('''
        INSERT INTO User (first_name, last_name, email, phone, password_HS, wallet, is_admin)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', ("Test", "User", test_email, "555-1234", password_hash, 5000, 0))
    
    usr_id = cursor.lastrowid
    print(f"✓ Created test user:")
    print(f"  - User ID: {usr_id}")
    print(f"  - Email: {test_email}")
    print(f"  - Password: test123")
    print(f"  - Name: Test User")
    
    return usr_id


def create_orders(conn, usr_id):
    """Create 4 orders for the test user and return order IDs."""
    cursor = conn.cursor()
    
    # Get some restaurants
    cursor.execute("SELECT rtr_id, name FROM Restaurant LIMIT 4")
    restaurants = cursor.fetchall()
    
    if len(restaurants) < 4:
        print("⚠ Not enough restaurants in database. Using available restaurants.")
        while len(restaurants) < 4:
            restaurants.append(restaurants[0])  # Duplicate if needed
    
    order_ids = []
    statuses = ["Delivered", "Delivered", "Preparing", "Ordered"]
    
    for i, (rtr_id, rst_name) in enumerate(restaurants[:4]):
        # Create order details JSON
        placed_time = datetime.now() - timedelta(days=i+1, hours=2)
        
        order_details = {
            "placed_at": placed_time.strftime("%Y-%m-%dT%H:%M:%S-05:00"),
            "restaurant_id": rtr_id,
            "restaurant_name": rst_name,
            "items": [
                {
                    "itm_id": 100 + i,
                    "name": f"Test Item {i+1}",
                    "qty": 1,
                    "unit_price": 15.00 + i,
                    "line_total": 15.00 + i
                },
                {
                    "itm_id": 200 + i,
                    "name": f"Test Item {i+2}",
                    "qty": 2,
                    "unit_price": 10.00,
                    "line_total": 20.00
                }
            ],
            "charges": {
                "subtotal": 35.00 + i,
                "tax": round((35.00 + i) * 0.0725, 2),
                "delivery_fee": 3.99,
                "service_fee": 1.49,
                "tip": 5.00,
                "total": round(35.00 + i + (35.00 + i) * 0.0725 + 3.99 + 1.49 + 5.00, 2)
            },
            "delivery_type": "delivery",
            "eta_minutes": 30 + i * 5,
            "notes": f"Test order {i+1}"
        }
        
        cursor.execute('''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, json.dumps(order_details, indent=2), statuses[i]))
        
        ord_id = cursor.lastrowid
        order_ids.append(ord_id)
        
        print(f"✓ Created order #{ord_id}:")
        print(f"  - Restaurant: {rst_name}")
        print(f"  - Status: {statuses[i]}")
        print(f"  - Total: ${order_details['charges']['total']}")
    
    return order_ids


def create_tickets(conn, usr_id, order_ids):
    """Create 2 support tickets for 2 different orders."""
    cursor = conn.cursor()
    
    # Create ticket for first order (Delivered)
    ticket_messages = [
        "My order arrived cold and the food quality was poor. I would like a refund or replacement.",
        "I was charged twice for this order. Please check my account and refund the duplicate charge."
    ]
    
    ticket_ids = []
    
    for i in range(2):
        cursor.execute('''
            INSERT INTO Ticket (usr_id, ord_id, message, status)
            VALUES (?, ?, ?, ?)
        ''', (usr_id, order_ids[i], ticket_messages[i], "Open"))
        
        ticket_id = cursor.lastrowid
        ticket_ids.append(ticket_id)
        
        print(f"✓ Created ticket #{ticket_id}:")
        print(f"  - Order: #{order_ids[i]}")
        print(f"  - Status: Open")
        print(f"  - Message: {ticket_messages[i][:50]}...")
    
    return ticket_ids


def verify_data(conn, usr_id, order_ids, ticket_ids):
    """Verify that all data was created successfully."""
    cursor = conn.cursor()
    
    print("\n" + "=" * 60)
    print("Verification:")
    print("=" * 60)
    
    # Verify user
    cursor.execute("SELECT usr_id, first_name, last_name, email FROM User WHERE usr_id = ?", (usr_id,))
    user = cursor.fetchone()
    if user:
        print(f"✓ User #{user[0]}: {user[1]} {user[2]} ({user[3]})")
    else:
        print("✗ User not found!")
        return False
    
    # Verify orders
    cursor.execute('SELECT COUNT(*) FROM "Order" WHERE usr_id = ?', (usr_id,))
    order_count = cursor.fetchone()[0]
    print(f"✓ Orders: {order_count} orders found")
    
    for ord_id in order_ids:
        cursor.execute('SELECT ord_id, status FROM "Order" WHERE ord_id = ?', (ord_id,))
        order = cursor.fetchone()
        if order:
            print(f"  - Order #{order[0]}: {order[1]}")
    
    # Verify tickets
    cursor.execute('SELECT COUNT(*) FROM Ticket WHERE usr_id = ?', (usr_id,))
    ticket_count = cursor.fetchone()[0]
    print(f"✓ Tickets: {ticket_count} tickets found")
    
    for ticket_id in ticket_ids:
        cursor.execute('SELECT ticket_id, ord_id, status FROM Ticket WHERE ticket_id = ?', (ticket_id,))
        ticket = cursor.fetchone()
        if ticket:
            print(f"  - Ticket #{ticket[0]} for Order #{ticket[1]}: {ticket[2]}")
    
    return True


def main():
    """Run the script to create test data."""
    db_file = get_db_path()
    
    print("Creating test user with orders and tickets")
    print("=" * 60)
    print(f"Database: {db_file}\n")
    
    if not os.path.exists(db_file):
        print(f"Error: Database file not found at {db_file}")
        sys.exit(1)
    
    conn = None
    try:
        # Connect to database
        conn = sqlite3.connect(db_file)
        print("✓ Connected to database\n")
        
        # Create test user
        usr_id = create_test_user(conn)
        print()
        
        # Create orders
        order_ids = create_orders(conn, usr_id)
        print()
        
        # Create tickets
        ticket_ids = create_tickets(conn, usr_id, order_ids)
        
        # Commit all changes
        conn.commit()
        print("\n✓ All changes committed")
        
        # Verify data
        verify_data(conn, usr_id, order_ids, ticket_ids)
        
        print("\n" + "=" * 60)
        print("Test data created successfully! ✓")
        print("\nLogin credentials:")
        print("  Email: testuser@weeklies.com")
        print("  Password: test123")
        print("\nYou can now:")
        print("  1. Log in as the test user to view orders and tickets")
        print("  2. Log in as admin to respond to tickets")
        
    except sqlite3.Error as e:
        print(f"\n✗ Database error: {e}")
        if conn:
            conn.rollback()
            print("✓ Changes rolled back")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        if conn:
            conn.rollback()
            print("✓ Changes rolled back")
        sys.exit(1)
        
    finally:
        if conn:
            conn.close()
            print("✓ Database connection closed")


if __name__ == '__main__':
    main()
