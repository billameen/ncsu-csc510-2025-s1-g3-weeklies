"""
Migration script to add is_admin column to User table and create admin user.

This migration adds:
- is_admin column to User table (INTEGER, default 0)
- Creates a default admin user with credentials
- Updates existing user to admin if specified
"""

import sqlite3
import os
import sys
from werkzeug.security import generate_password_hash


def get_db_path():
    """Get the path to the database file."""
    db_file = os.path.join(os.path.dirname(__file__), '..', 'CSC510_DB.db')
    return os.path.abspath(db_file)


def add_admin_column(conn):
    """Add is_admin column to User table."""
    cursor = conn.cursor()
    
    # Check if column already exists
    cursor.execute("PRAGMA table_info(User)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    
    if 'is_admin' in column_names:
        print("⚠ is_admin column already exists. Skipping column creation.")
        return False
    
    # Add is_admin column with default value 0 (not admin)
    cursor.execute('''
        ALTER TABLE User ADD COLUMN is_admin INTEGER DEFAULT 0
    ''')
    
    print("✓ is_admin column added to User table")
    return True


def create_admin_user(conn):
    """Create a default admin user or promote existing user."""
    cursor = conn.cursor()
    
    # Check if any admin users already exist
    cursor.execute("SELECT COUNT(*) FROM User WHERE is_admin = 1")
    admin_count = cursor.fetchone()[0]
    
    if admin_count > 0:
        print(f"⚠ {admin_count} admin user(s) already exist. Skipping admin creation.")
        return
    
    # Check if there are any existing users
    cursor.execute("SELECT usr_id, email, first_name, last_name FROM User LIMIT 1")
    first_user = cursor.fetchone()
    
    if first_user:
        # Promote the first user to admin
        usr_id = first_user[0]
        email = first_user[1]
        name = f"{first_user[2]} {first_user[3]}"
        
        cursor.execute("UPDATE User SET is_admin = 1 WHERE usr_id = ?", (usr_id,))
        print(f"✓ Promoted existing user to admin:")
        print(f"  - User ID: {usr_id}")
        print(f"  - Name: {name}")
        print(f"  - Email: {email}")
    else:
        # Create a new admin user
        admin_email = "admin@weeklies.com"
        admin_password = "admin123"  # Change this in production!
        admin_first = "Admin"
        admin_last = "User"
        admin_phone = "555-0000"
        
        # Hash the password
        password_hash = generate_password_hash(admin_password)
        
        cursor.execute('''
            INSERT INTO User (first_name, last_name, email, phone, password_HS, wallet, is_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (admin_first, admin_last, admin_email, admin_phone, password_hash, 10000, 1))
        
        print("✓ Created new admin user:")
        print(f"  - Email: {admin_email}")
        print(f"  - Password: {admin_password}")
        print(f"  - Name: {admin_first} {admin_last}")
        print(f"  ⚠ IMPORTANT: Change the admin password after first login!")


def verify_migration(conn):
    """Verify that the migration was successful."""
    cursor = conn.cursor()
    
    # Verify column exists
    cursor.execute("PRAGMA table_info(User)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    
    if 'is_admin' not in column_names:
        raise Exception("is_admin column was not added successfully")
    
    print("\n✓ Migration verification:")
    
    # Check admin users
    cursor.execute("""
        SELECT usr_id, first_name, last_name, email, is_admin 
        FROM User 
        WHERE is_admin = 1
    """)
    admin_users = cursor.fetchall()
    
    if not admin_users:
        raise Exception("No admin users found after migration")
    
    print(f"  Admin users ({len(admin_users)}):")
    for admin in admin_users:
        print(f"    - ID: {admin[0]}, Name: {admin[1]} {admin[2]}, Email: {admin[3]}")
    
    # Check total users
    cursor.execute("SELECT COUNT(*) FROM User")
    total_users = cursor.fetchone()[0]
    print(f"  Total users: {total_users}")


def migrate():
    """Run the complete migration."""
    db_file = get_db_path()
    
    print(f"Starting admin migration for database: {db_file}")
    print("=" * 60)
    
    if not os.path.exists(db_file):
        print(f"Error: Database file not found at {db_file}")
        sys.exit(1)
    
    conn = None
    try:
        # Connect to database
        conn = sqlite3.connect(db_file)
        print("✓ Connected to database")
        
        # Run migration steps
        add_admin_column(conn)
        create_admin_user(conn)
        
        # Commit all changes
        conn.commit()
        print("\n✓ All changes committed")
        
        # Verify the migration
        verify_migration(conn)
        
        print("\n" + "=" * 60)
        print("Migration completed successfully! ✓")
        print("\nYou can now log in with admin credentials to access /admin")
        
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
    migrate()
