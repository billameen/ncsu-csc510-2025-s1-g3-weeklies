"""
Build the local SQLite database (CSC510_DB.db) from db/seed.sql.

The .db file is not tracked in git; db/seed.sql (a `sqlite3 .dump` of the schema and
demo data) is the source of truth. Run this after cloning, or with --force to reset
your local DB back to the seed data.

Usage (from app/):
    python scripts/init_db.py           # create the DB if it does not exist
    python scripts/init_db.py --force   # overwrite an existing DB

To refresh the seed after changing the schema or demo data:
    sqlite3 CSC510_DB.db .dump > db/seed.sql
"""

import os
import sqlite3
import sys

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_FILE = os.path.join(APP_DIR, "CSC510_DB.db")
SEED_FILE = os.path.join(APP_DIR, "db", "seed.sql")


def init_db(db_file=DB_FILE, seed_file=SEED_FILE, force=False):
    """Create db_file from seed_file. Returns False if the DB exists and force is False."""
    if os.path.exists(db_file):
        if not force:
            return False
        os.remove(db_file)

    with open(seed_file, encoding="utf-8") as f:
        seed_sql = f.read()

    # Inserting rows into AUTOINCREMENT tables already populates sqlite_sequence, so clear
    # it before the dump's own sqlite_sequence rows to avoid duplicate entries.
    seq_insert = "INSERT INTO sqlite_sequence"
    seed_sql = seed_sql.replace(seq_insert, f"DELETE FROM sqlite_sequence;\n{seq_insert}", 1)

    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(seed_sql)
    finally:
        conn.close()
    return True


def main():
    force = "--force" in sys.argv
    if init_db(force=force):
        print(f"Created {DB_FILE} from {SEED_FILE}")
    else:
        print(f"{DB_FILE} already exists; use --force to overwrite it")


if __name__ == "__main__":
    main()
