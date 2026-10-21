"""
Migration: move wallet balances from the old User.wallet column into the ledger (M2).

Before M2 a wallet was one editable integer column, User.wallet. Now a balance is
the sum of the user's LedgerEntry rows (see ledger.py). This migration:

- creates the LedgerTransaction / LedgerEntry tables, indexes and append-only
  triggers if they do not exist yet;
- gives every user with money in User.wallet an "opening_balance" transaction
  for exactly that amount (from the account external:opening);
- verifies that every user's opening balance equals their old User.wallet value,
  that the openings add up to the column's total, and that the ledger balances.

It is idempotent: each user's opening transaction has a fixed idempotency key
(opening:user:<id>), so running it again changes nothing. Users whose wallet
the app already touched were opened automatically then and are only verified.
After this migration nothing reads User.wallet any more.

Run (from app/):
    python migrations/add_wallet_ledger.py            # migrate + verify
    python migrations/add_wallet_ledger.py --check    # verify only, write nothing
    python migrations/add_wallet_ledger.py path/to/other.db

Exit code is 0 when everything matches and 1 otherwise.
"""

import os
import sqlite3
import sys
from dataclasses import dataclass, field

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import ledger  # noqa: E402
from money import format_cents  # noqa: E402


def get_db_path():
    """Path of the app's database file."""
    return os.path.join(APP_DIR, "CSC510_DB.db")


@dataclass
class MigrationReport:
    """What one run moved into the ledger, and anything that did not match."""
    users: int = 0
    opened: int = 0             # opening transactions written by this run
    already_open: int = 0       # users that already had an opening transaction
    empty: int = 0              # users with $0.00 in the old column: nothing to move
    column_total_cents: int = 0
    opening_total_cents: int = 0
    mismatches: list = field(default_factory=list)   # (usr_id, column_cents, opening_cents)
    errors: list = field(default_factory=list)       # (usr_id, message)
    ledger_ok: bool = False

    @property
    def ok(self):
        """True when the ledger balances and every old balance matches its opening entry."""
        return (self.ledger_ok and not self.mismatches and not self.errors
                and self.opening_total_cents == self.column_total_cents)


def _opening_cents(conn, usr_id):
    """Amount the user's opening transaction put into their wallet (0 if none)."""
    row = conn.execute(
        '''SELECT COALESCE(SUM(e.amount_cents), 0)
           FROM "LedgerTransaction" t JOIN "LedgerEntry" e ON e.txn_id = t.txn_id
           WHERE t.idempotency_key = ? AND e.account = ?''',
        (ledger.opening_key(usr_id), ledger.user_account(usr_id)),
    ).fetchone()
    return row[0]


def _has_opening(conn, usr_id):
    return conn.execute('SELECT 1 FROM "LedgerTransaction" WHERE idempotency_key = ?',
                        (ledger.opening_key(usr_id),)).fetchone() is not None


def migrate(conn, write=True):
    """Open every user's legacy balance in the ledger (unless write=False), then verify."""
    if write:
        ledger.ensure_schema(conn)
    report = MigrationReport()
    users = conn.execute('SELECT usr_id, wallet FROM "User" ORDER BY usr_id').fetchall()
    report.users = len(users)

    for usr_id, column in users:
        report.column_total_cents += column if type(column) is int else 0
        if not column:
            report.empty += 1
        if _has_opening(conn, usr_id):
            report.already_open += 1
            continue
        if not write or not column:
            continue
        try:
            ledger.open_legacy_wallet(conn, usr_id)
            report.opened += 1
        except ledger.LedgerError as e:
            report.errors.append((usr_id, str(e)))

    for usr_id, column in users:
        if any(u == usr_id for u, _ in report.errors):
            continue
        opening = _opening_cents(conn, usr_id)
        report.opening_total_cents += opening
        if opening != (column or 0):
            report.mismatches.append((usr_id, column, opening))

    report.ledger_ok = ledger.check_ledger(conn).ok
    return report


def print_report(report, write=True):
    """Print a MigrationReport; `write=False` labels it as a --check run."""
    print("✓ Ledger tables ready" if write else "(check only: nothing written)")
    print(f"  Users:                     {report.users}")
    print(f"  Opening balances written:  {report.opened}")
    print(f"  Already in the ledger:     {report.already_open}")
    print(f"  $0.00 wallets (skipped):   {report.empty}")
    print(f"  Old User.wallet total:     {format_cents(report.column_total_cents)}")
    print(f"  Ledger opening total:      {format_cents(report.opening_total_cents)}")
    for usr_id, column, opening in report.mismatches[:20]:
        print(f"  ✗ user {usr_id}: old column {column!r} cents, ledger opening {opening} cents")
    for usr_id, message in report.errors[:20]:
        print(f"  ✗ user {usr_id}: {message}")
    print(f"  Ledger balanced:           {'✓' if report.ledger_ok else '✗'}")
    print("✓ Migration verified: every balance matches." if report.ok
          else "✗ Migration check FAILED: see the lines above.")


def main(argv=None):
    """
    Migrate and verify the database given as an argument, or the app's. `--check` only
    verifies and writes nothing. Returns the exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    write = "--check" not in args
    paths = [a for a in args if not a.startswith("--")]
    db_path = paths[0] if paths else get_db_path()
    if not os.path.exists(db_path):
        print(f"✗ Database not found: {db_path}")
        return 1

    print(f"Wallet ledger migration on {db_path}")
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        if not write and not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='LedgerEntry'").fetchone():
            print("✗ The ledger tables do not exist yet; run without --check first.")
            return 1
        report = migrate(conn, write=write)
    finally:
        conn.close()
    print_report(report, write=write)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
