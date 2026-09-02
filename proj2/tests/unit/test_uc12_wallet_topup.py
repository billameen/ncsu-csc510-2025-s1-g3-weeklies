"""Unit tests for POST /profile/wallet/topup.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``proj2/CSC510_DB.db``.

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


def test_a_non_numeric_amount_reports_zero_amount_because_the_invalid_amount_branch_is_unreachable(
    client, temp_db_path
):
    """The route wraps the conversion in try/except and redirects with
    ``wallet_error=invalid_amount`` on failure. But ``_money`` already
    swallows the failure itself::

        try:    return round(float(x) + 1e-9, 2)
        except Exception: return 0.0

    so ``_money("abc")`` returns 0.0 rather than raising, the except branch is
    never entered, and control falls through to the ``amount_cents <= 0``
    check instead. The team's own suite has a commented-out
    ``test_topup_error_invalid_amount`` attributing this to HTML form
    validation; the real cause is that the branch cannot be reached at all.
    """
    usr_id = _make_user(temp_db_path, "uc12-invalid@example.test", wallet_cents=500)
    _login(client, "uc12-invalid@example.test")

    response = client.post("/profile/wallet/topup", data={"amount": "abc"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_error=zero_amount"
    assert "invalid_amount" not in response.headers["Location"]
    assert _wallet_cents(temp_db_path, usr_id) == 500


# This proves the invalid_amount error the route defines is dead code: garbage input is silently coerced to $0.00 and misreported as a zero-amount error, so the user is told the wrong thing about their own input -- a real defect.


def test_certain_exact_dollar_amounts_lose_a_cent_to_float_truncation(client, temp_db_path):
    """``_dollars_to_cents`` truncates instead of rounding::

        return int(_money(dollars) * 100)

    0.29 is not exactly representable in binary floating point, so
    ``0.29 * 100`` evaluates to 28.999999999999996 and ``int()`` floors it to
    28. Roughly 1,145 of the 20,000 cent-values between $0.01 and $200.00
    are short by one cent for the same reason. The same helper is used by the
    gift and order routes.
    """
    usr_id = _make_user(temp_db_path, "uc12-cent@example.test", wallet_cents=0)
    _login(client, "uc12-cent@example.test")

    response = client.post("/profile/wallet/topup", data={"amount": "0.29"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?wallet_updated=topup"
    assert _wallet_cents(temp_db_path, usr_id) == 28
    with client.session_transaction() as sess:
        assert sess["Wallet"] == 28


# This proves a $0.29 top-up credits 28 cents, because dollars are floored rather than rounded into cents -- money is silently lost on every affected amount, a real defect.
