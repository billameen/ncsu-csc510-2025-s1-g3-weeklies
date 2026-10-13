"""Unit tests for POST /profile/wallet/topup.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``app/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``app/CSC510_DB.db``.

Wallet balances are stored as integer cents. Each test creates its own user
because ``temp_db_path`` is session-scoped and these tests assert on exact
balances.
"""
from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


def _make_user(temp_db_path, email, wallet_cents=0):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Uc12","Tester",?,"9195550500",?,?,"","")''',
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


def _login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 302


def test_a_valid_top_up_credits_the_wallet_and_the_session_by_the_same_amount(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc12-happy@example.test", wallet_cents=500)
    _login(client, "uc12-happy@example.test")

    response = client.post("/profile/wallet/topup", data={"amount": "15.50"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_updated=topup"
    assert _wallet_cents(temp_db_path, usr_id) == 500 + 1550
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 2050


# This proves a well-formed top-up converts dollars to cents, applies the credit atomically, and keeps the session balance in step with the database.


def test_a_non_numeric_amount_reports_invalid_amount(client, temp_db_path):
    """Regression (M2, bug 1 follow-on): non-numeric input used to be coerced
    to $0.00 by ``_money`` and misreported as ``zero_amount``. Amounts are now
    parsed with ``money.parse_cents``, which rejects garbage outright.
    """
    usr_id = _make_user(temp_db_path, "uc12-garbage@example.test", wallet_cents=500)
    _login(client, "uc12-garbage@example.test")

    response = client.post("/profile/wallet/topup", data={"amount": "abc"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_error=invalid_amount"
    assert _wallet_cents(temp_db_path, usr_id) == 500


def test_a_29_cent_top_up_credits_exactly_29_cents(client, temp_db_path):
    """Regression (M2, bug 1): ``_dollars_to_cents`` used to compute
    ``int(0.29 * 100)``, i.e. ``int(28.999999999999996) == 28``, losing a cent
    on 4,586 of the first 100,000 cent amounts. Amounts are now parsed with
    ``Decimal`` and rounded half up.
    """
    usr_id = _make_user(temp_db_path, "uc12-cent@example.test", wallet_cents=0)
    _login(client, "uc12-cent@example.test")

    response = client.post("/profile/wallet/topup", data={"amount": "0.29"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_updated=topup"
    assert _wallet_cents(temp_db_path, usr_id) == 29
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 29
