"""
Migration script to add Ticket table for support ticket system.

This migration adds:
- Ticket table with all required columns and constraints
- Foreign key constraints for usr_id and ord_id
- Database indexes for performance (usr_id, status, created_at)
- Trigger for automatic updated_at timestamp updates
"""

import sqlite3
import os
import sys


def get_db_path():
    """Get the path to the database file."""
    # Database is in the root directory
    db_file = os.path.join(os.path.dirname(__file__), '..', 'CSC510_DB.db')
    return os.path.abspath(db_file)


def verify_prerequisites(conn):
    """Verify that User and Order tables exist."""
    cursor = conn.cursor()
    
    # Check if User table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='User'
    """)
    if not cursor.fetchone():
        raise Exception("User table does not exist. Cannot create Ticket table.")
    
    # Check if Order table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='Order'
    """)
    if not cursor.fetchone():
        raise Exception("Order table does not exist. Cannot create Ticket table.")
    
    print("✓ Prerequisites verified: User and Order tables exist")


def create_ticket_table(conn):
    """Create the Ticket table with all required columns and constraints."""
    cursor = conn.cursor()
    
    # Check if table already exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='Ticket'
    """)
    
    if cursor.fetchone():
        print("⚠ Ticket table already exists. Skipping table creation.")
        return False
    
    # Create Ticket table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Ticket (
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
        )
    ''')
    
    print("✓ Ticket table created successfully")
    return True


def create_indexes(conn):
    """Create database indexes for performance."""
    cursor = conn.cursor()
    
    # Create index on usr_id for fast user ticket lookups
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_ticket_usr_id 
        ON Ticket(usr_id)
    ''')
    print("✓ Index created: idx_ticket_usr_id")
    
    # Create index on status for fast status-based queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_ticket_status 
        ON Ticket(status)
    ''')
    print("✓ Index created: idx_ticket_status")
    
    # Create index on created_at for sorting by date (descending)
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_ticket_created_at 
        ON Ticket(created_at DESC)
    ''')
    print("✓ Index created: idx_ticket_created_at")


def create_trigger(conn):
    """Create trigger for automatic updated_at timestamp updates."""
    cursor = conn.cursor()
    
    # Drop trigger if it exists (for idempotency)
    cursor.execute('''
        DROP TRIGGER IF EXISTS update_ticket_timestamp
    ''')
    
    # Create trigger to automatically update updated_at on any UPDATE
    cursor.execute('''
        CREATE TRIGGER update_ticket_timestamp 
        AFTER UPDATE ON Ticket
        FOR EACH ROW
        BEGIN
            UPDATE Ticket SET updated_at = CURRENT_TIMESTAMP
            WHERE ticket_id = NEW.ticket_id;
        END
    ''')
    
    print("✓ Trigger created: update_ticket_timestamp")


def verify_table_structure(conn):
    """Verify that the Ticket table was created with correct structure."""
    cursor = conn.cursor()
    
    # Get table info
    cursor.execute("PRAGMA table_info(Ticket)")
    columns = cursor.fetchall()
    
    if not columns:
        raise Exception("Ticket table was not created successfully")
    
    print("\n✓ Table structure verification:")
    print("  Columns:")
    expected_columns = {
        'ticket_id': 'INTEGER',
        'usr_id': 'INTEGER',
        'ord_id': 'INTEGER',
        'message': 'TEXT',
        'response': 'TEXT',
        'status': 'TEXT',
        'created_at': 'TIMESTAMP',
        'updated_at': 'TIMESTAMP'
    }
    
    for col in columns:
        col_name = col[1]
        col_type = col[2]
        is_pk = col[5] == 1
        pk_marker = " (PRIMARY KEY)" if is_pk else ""
        print(f"    - {col_name}: {col_type}{pk_marker}")
        
        # Verify expected columns
        if col_name in expected_columns:
            del expected_columns[col_name]
    
    if expected_columns:
        raise Exception(f"Missing columns: {', '.join(expected_columns.keys())}")
    
    # Verify foreign keys
    cursor.execute("PRAGMA foreign_key_list(Ticket)")
    foreign_keys = cursor.fetchall()
    
    print("  Foreign Keys:")
    if len(foreign_keys) < 2:
        raise Exception("Expected 2 foreign keys, found fewer")
    
    for fk in foreign_keys:
        print(f"    - {fk[3]} -> {fk[2]}({fk[4]})")
    
    # Verify indexes
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='Ticket'
    """)
    indexes = cursor.fetchall()
    
    print("  Indexes:")
    for idx in indexes:
        print(f"    - {idx[0]}")
    
    # Verify trigger
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='trigger' AND tbl_name='Ticket'
    """)
    triggers = cursor.fetchall()
    
    print("  Triggers:")
    for trigger in triggers:
        print(f"    - {trigger[0]}")
    
    if not triggers:
        raise Exception("Trigger was not created successfully")


def migrate():
    """Run the complete migration."""
    db_file = get_db_path()
    
    print(f"Starting migration for database: {db_file}")
    print("=" * 60)
    
    if not os.path.exists(db_file):
        print(f"Error: Database file not found at {db_file}")
        sys.exit(1)
    
    conn = None
    try:
        # Connect to database
        conn = sqlite3.connect(db_file)
        print("✓ Connected to database")
        
        # Enable foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON")
        
        # Run migration steps
        verify_prerequisites(conn)
        create_ticket_table(conn)
        create_indexes(conn)
        create_trigger(conn)
        
        # Commit all changes
        conn.commit()
        print("\n✓ All changes committed")
        
        # Verify the migration
        verify_table_structure(conn)
        
        print("\n" + "=" * 60)
        print("Migration completed successfully! ✓")
        
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
