"""Test helpers for reading and setting wallet balances through the ledger.

Since M2, a wallet balance is the sum of the user's ledger entries; the old
``User.wallet`` column is only read once, as the user's opening balance. Tests
must therefore read and set balances here instead of touching the column.
"""
import uuid

import ledger
from sqlQueries import close_connection, create_connection, fetch_one


def wallet_cents(db_path, usr_id):
    """The user's current wallet balance in cents."""
    conn = create_connection(db_path)
    try:
        ledger.ensure_schema(conn)
        return ledger.wallet_balance(conn, usr_id)
    finally:
        close_connection(conn)


def wallet_cents_by_email(db_path, email):
    conn = create_connection(db_path)
    try:
        usr_id = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)
    return wallet_cents(db_path, usr_id)


def set_wallet_cents(db_path, usr_id, cents):
    """Set a user's balance by posting a test adjustment to the ledger."""
    conn = create_connection(db_path)
    try:
        ledger.ensure_schema(conn)
        delta = cents - ledger.wallet_balance(conn, usr_id)
        if delta:
            ledger.post_transaction(
                conn, "test_adjustment",
                [(ledger.user_account(usr_id), delta), ("external:test", -delta)],
                f"test:{uuid.uuid4().hex}",
            )
    finally:
        close_connection(conn)
