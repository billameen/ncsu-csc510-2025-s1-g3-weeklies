"""Unit tests for POST /profile/wallet/topup.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``app/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``app/CSC510_DB.db``.

Wallet balances are stored as integer cents. Each test creates its own user
because ``temp_db_path`` is session-scoped and these tests assert on exact
balances.
"""
import pytest
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


@pytest.mark.parametrize("amount", ["abc", "nan", "inf", "1e999", "12.5.0"])
def test_a_non_numeric_amount_reports_invalid_amount(client, temp_db_path, amount):
    """``_money`` swallows conversion errors and returns 0.0, so the route used to
    misreport garbage input as ``zero_amount``. Top-up now parses strictly with
    ``_parse_amount_cents``, which raises on anything that is not a finite number.
    """
    email = f"uc12-invalid-{amount.replace('.', '-')}@example.test"
    usr_id = _make_user(temp_db_path, email, wallet_cents=500)
    _login(client, email)

    response = client.post("/profile/wallet/topup", data={"amount": amount}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_error=invalid_amount"
    assert _wallet_cents(temp_db_path, usr_id) == 500


# This proves non-numeric, non-finite and out-of-range input is reported as invalid_amount and leaves the wallet unchanged.


@pytest.mark.parametrize("amount", ["0", "-5", "0.001"])
def test_a_zero_or_negative_amount_reports_zero_amount(client, temp_db_path, amount):
    email = f"uc12-zero-{amount.replace('.', '-')}@example.test"
    usr_id = _make_user(temp_db_path, email, wallet_cents=500)
    _login(client, email)

    response = client.post("/profile/wallet/topup", data={"amount": amount}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_error=zero_amount"
    assert _wallet_cents(temp_db_path, usr_id) == 500


# This proves well-formed amounts that round to zero cents or below are still rejected as zero_amount.


@pytest.mark.parametrize("amount,cents", [("0.29", 29), ("0.57", 57), ("1.13", 113), ("1.005", 101)])
def test_dollar_amounts_convert_to_the_exact_number_of_cents(client, temp_db_path, amount, cents):
    """``int(0.29 * 100)`` floors 28.999999999999996 to 28. Amounts are now
    parsed as ``Decimal`` and rounded half-up, so no cent is lost.
    """
    email = f"uc12-cent-{amount.replace('.', '-')}@example.test"
    usr_id = _make_user(temp_db_path, email, wallet_cents=0)
    _login(client, email)

    response = client.post("/profile/wallet/topup", data={"amount": amount}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_updated=topup"
    assert _wallet_cents(temp_db_path, usr_id) == cents
    with client.session_transaction() as sess:
        assert sess["Wallet"] == cents


# This proves amounts that used to lose a cent to float truncation are credited exactly.


def test_a_top_up_resyncs_a_stale_session_wallet_with_the_database(client, temp_db_path):
    """The session balance used to be updated by arithmetic on its own value, so
    a stale session stayed stale. It is now re-read from the database.
    """
    usr_id = _make_user(temp_db_path, "uc12-stale@example.test", wallet_cents=5000)
    _login(client, "uc12-stale@example.test")
    with client.session_transaction() as sess:
        sess["Wallet"] = 0  # e.g. a gift arrived after login

    response = client.post("/profile/wallet/topup", data={"amount": "1.00"}, follow_redirects=False)

    assert response.status_code == 302
    assert _wallet_cents(temp_db_path, usr_id) == 5100
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 5100


# This proves a top-up corrects a stale session balance to the database value instead of compounding the error.
