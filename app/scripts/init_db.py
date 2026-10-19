"""
Build the local SQLite database (CSC510_DB.db) from db/seed.sql.

The .db file is not tracked in git; db/seed.sql (a `sqlite3 .dump` of the schema and
demo data) is the source of truth. Run this after cloning, or with --force to reset
your local DB back to the seed data.

The seed's User.wallet balances are then moved into the wallet ledger by
migrations/add_wallet_ledger.py, so a new DB starts with a balanced ledger.

Usage (from app/):
    python scripts/init_db.py           # create the DB if it does not exist
    python scripts/init_db.py --force   # overwrite an existing DB

To refresh the seed after changing the schema or demo data:
    sqlite3 CSC510_DB.db .dump > db/seed.sql
"""

import os
import re
import sqlite3
import sys

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
DB_FILE = os.path.join(APP_DIR, "CSC510_DB.db")
SEED_FILE = os.path.join(APP_DIR, "db", "seed.sql")

# Newer sqlite3 CLIs (3.50+) write text containing control characters, such as the
# newlines in Restaurant.hours, as unistr('...\u000a...') in .dump output. Older SQLite
# builds (including the one bundled with many Python installs) lack unistr(), so the
# seed fails with "no such function: unistr". _unistr reimplements it in Python.
_UNISTR_ESCAPE = re.compile(
    r"\\(?:\\|u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|\+([0-9a-fA-F]{6})|([0-9a-fA-F]{4}))"
)


def _unistr(text):
    """Python version of SQLite's unistr(): decode backslash escapes to characters."""
    if text is None:
        return None

    def decode(match):
        code = next((g for g in match.groups() if g), None)
        return "\\" if code is None else chr(int(code, 16))

    return _UNISTR_ESCAPE.sub(decode, text)


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
    conn.create_function("unistr", 1, _unistr, deterministic=True)
    try:
        conn.executescript(seed_sql)
        # Move the seed's User.wallet balances into the wallet ledger (M2).
        from migrations.add_wallet_ledger import migrate

        report = migrate(conn)
        if not report.ok:
            raise RuntimeError(f"wallet ledger migration failed: {report}")
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
