"""
Migration: add the PlanEdit table, the history of plain-English plan edits.

Each request typed into the calendar's edit box gets a row: what was typed, what happened
(proposed, accepted, discarded, clarify, refused, impossible or error) and a short detail.
The calendar shows a user's last 5. Idempotent: does nothing if the table exists.

Run (from app/):
    python migrations/add_plan_edit_table.py
"""

import os
import sqlite3
import sys

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS "PlanEdit" (
    edit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    usr_id INTEGER NOT NULL,
    request TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usr_id) REFERENCES User(usr_id)
);
CREATE INDEX IF NOT EXISTS idx_plan_edit_usr_id ON PlanEdit(usr_id, edit_id DESC);
"""


def get_db_path():
    """Path to the app's database file, app/CSC510_DB.db."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "CSC510_DB.db"))


def migrate(db_file=None):
    """
    Create PlanEdit if it is missing.
    Returns:
        bool: True if the table was created, False if it already existed.
    Raises:
        FileNotFoundError: The database file does not exist.
    """
    db_file = db_file or get_db_path()
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"Database not found at {db_file}")
    conn = sqlite3.connect(db_file)
    try:
        existed = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'PlanEdit'"
        ).fetchone()
        conn.executescript(CREATE_SQL)
        conn.commit()
    finally:
        conn.close()
    return existed is None


if __name__ == "__main__":
    try:
        created = migrate()
    except (FileNotFoundError, sqlite3.Error) as e:
        print(f"✗ {e}")
        sys.exit(1)
    print("✓ Created PlanEdit" if created else "⚠ PlanEdit already exists. Nothing to do.")
