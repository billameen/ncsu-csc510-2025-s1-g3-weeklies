"""Unit tests for POST /profile/wallet/gift.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``proj2/CSC510_DB.db``.

Wallet balances are stored as integer cents. Each test creates its own sender
and recipient because ``temp_db_path`` is session-scoped and these tests
assert on exact balances.
"""
from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_all, fetch_one

PASSWORD = "secret123"


def _make_user(temp_db_path, email, wallet_cents=0):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Uc13","Tester",?,"9195550600",?,?,"","")''',
            (email, generate_password_hash(PASSWORD), wallet_cents),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _wallet_cents(temp_db_path, usr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(conn, 'SELECT wallet FROM "User" WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)


def _row_counts(temp_db_path):
    """Row count of every user table in the schema, keyed by table name."""
    conn = create_connection(temp_db_path)
    try:
        tables = [
            r[0]
            for r in fetch_all(
                conn,
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
            )
        ]
        return {t: fetch_one(conn, f'SELECT COUNT(*) FROM "{t}"')[0] for t in tables}
    finally:
        close_connection(conn)


def _login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 302


def test_a_gift_moves_the_exact_amount_from_sender_to_recipient(client, temp_db_path):
    sender_id = _make_user(temp_db_path, "uc13-sender@example.test", wallet_cents=5000)
    recipient_id = _make_user(temp_db_path, "uc13-recipient@example.test", wallet_cents=1000)
    _login(client, "uc13-sender@example.test")

    response = client.post(
        "/profile/wallet/gift",
        data={"recipient_email": "uc13-recipient@example.test", "amount": "10.00"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_updated=gift"
    assert _wallet_cents(temp_db_path, sender_id) == 5000 - 1000
    assert _wallet_cents(temp_db_path, recipient_id) == 1000 + 1000
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 4000


# This proves a funded gift debits the sender and credits the recipient by the same number of cents in one atomic transaction, leaving the sender's session balance correct.


def test_a_stale_session_wallet_survives_a_gift_and_diverges_further_from_the_database(
    client, temp_db_path
):
    """The route refreshes the session by arithmetic on the session's own
    value rather than re-reading the row it just wrote::

        session['Wallet'] = session['Wallet'] - amount_cents

    So a session balance that is already wrong stays wrong. That matters
    because POST /order gates affordability on the session value
    (``user_wallet_cents = session.get('Wallet', 0)``) before it reaches the
    database, so the divergence is load-bearing rather than cosmetic.
    """
    sender_id = _make_user(temp_db_path, "uc13-stale@example.test", wallet_cents=5000)
    _make_user(temp_db_path, "uc13-stale-recipient@example.test", wallet_cents=0)
    _login(client, "uc13-stale@example.test")
    with client.session_transaction() as sess:
        sess["Wallet"] = 999_999

    response = client.post(
        "/profile/wallet/gift",
        data={"recipient_email": "uc13-stale-recipient@example.test", "amount": "10.00"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_updated=gift"
    assert _wallet_cents(temp_db_path, sender_id) == 4000
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 998_999
        assert sess["Wallet"] != _wallet_cents(temp_db_path, sender_id)


# This proves the gift route never reconciles the session against the row it just updated, so a wrong session balance is carried forward and compounded instead of corrected -- a real defect, and one the order route then trusts.


def test_a_completed_gift_leaves_no_audit_record_anywhere_in_the_schema(client, temp_db_path):
    """The transfer is two UPDATE statements on ``User.wallet`` and nothing
    else. The schema has no ledger or transaction table, so once the balances
    move there is no record of who sent what to whom, or when.
    """
    sender_id = _make_user(temp_db_path, "uc13-audit@example.test", wallet_cents=5000)
    recipient_id = _make_user(temp_db_path, "uc13-audit-recipient@example.test", wallet_cents=0)
    _login(client, "uc13-audit@example.test")
    before = _row_counts(temp_db_path)

    response = client.post(
        "/profile/wallet/gift",
        data={"recipient_email": "uc13-audit-recipient@example.test", "amount": "25.00"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_updated=gift"
    assert _wallet_cents(temp_db_path, sender_id) == 2500
    assert _wallet_cents(temp_db_path, recipient_id) == 2500
    assert _row_counts(temp_db_path) == before
    assert not any("transaction" in t.lower() or "ledger" in t.lower() for t in before)


# This proves a $25.00 transfer between two accounts writes no new row in any table -- there is no ledger to reverse, dispute or audit a mistaken or fraudulent gift against, a real defect.
