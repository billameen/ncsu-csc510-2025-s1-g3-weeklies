"""
Migration: add the weekly planner's targets to the User table.

Adds two nullable INTEGER columns:
- daily_calorie_target: calories per day the planner aims for (within 10%).
- weekly_budget_cents: most the planned week may cost, tax and fees included, in cents.

Existing users get NULL for both, which means "not set yet": /generate_plan asks them to set
the targets on their profile before the solver plans a week. Idempotent: columns that already
exist are skipped.

Run add_admin_column.py first. Login reads User by position and expects is_admin at index 10;
adding these columns before is_admin would put daily_calorie_target there and make anyone with
a calorie target an admin. So this migration refuses to run until is_admin exists.

Run (from app/):
    python migrations/add_plan_targets.py
"""

import os
import sqlite3
import sys

COLUMNS = (
    ("daily_calorie_target", "INTEGER"),
    ("weekly_budget_cents", "INTEGER"),
)


def get_db_path():
    """Path to the app's database file, app/CSC510_DB.db."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "CSC510_DB.db"))


class MigrationOrderError(RuntimeError):
    """A migration this one must follow has not been applied yet."""


def add_plan_target_columns(conn):
    """
    Add the planner target columns that are missing from User.
    Args:
        conn (sqlite3.Connection): Open connection; the caller commits.
    Returns:
        list[str]: Names of the columns added (empty if all already existed).
    Raises:
        MigrationOrderError: User has no is_admin column yet (run add_admin_column.py first).
    """
    existing = {row[1] for row in conn.execute('PRAGMA table_info("User")')}
    if "is_admin" not in existing:
        raise MigrationOrderError(
            "User has no is_admin column. Run migrations/add_admin_column.py first: login reads "
            "is_admin by position, and adding these columns before it would grant admin rights."
        )
    added = []
    for name, sql_type in COLUMNS:
        if name not in existing:
            conn.execute(f'ALTER TABLE "User" ADD COLUMN {name} {sql_type}')
            added.append(name)
    return added


def migrate(db_file=None):
    """
    Apply the migration to db_file (default: the app's database) in one transaction.
    Returns:
        list[str]: Names of the columns added.
    Raises:
        FileNotFoundError: The database file does not exist.
    """
    db_file = db_file or get_db_path()
    if not os.path.exists(db_file):
        # sqlite3.connect would silently create an empty database instead.
        raise FileNotFoundError(f"Database not found at {db_file}")
    conn = sqlite3.connect(db_file)
    try:
        added = add_plan_target_columns(conn)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()
    return added


if __name__ == "__main__":
    try:
        added = migrate()
    except (FileNotFoundError, MigrationOrderError, sqlite3.Error) as e:
        print(f"✗ {e}")
        sys.exit(1)
    if added:
        print(f"✓ Added {', '.join(added)} to User")
    else:
        print("⚠ Planner target columns already exist. Nothing to do.")
