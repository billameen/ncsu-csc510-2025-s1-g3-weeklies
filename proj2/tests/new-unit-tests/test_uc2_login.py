"""Unit tests for POST /login.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``app``/``client``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database seeded by ``seed_minimal_data`` (user test@x.com / secret123), so
these tests do not touch ``proj2/CSC510_DB.db``.
"""


def test_logging_in_with_valid_credentials_populates_the_session(client, seed_minimal_data):
    response = client.post(
        "/login",
        data={"email": "test@x.com", "password": "secret123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/") or "index" in response.headers["Location"] or response.headers["Location"] == "/"
    with client.session_transaction() as sess:
        assert sess["Email"] == "test@x.com"
        assert sess["usr_id"] == seed_minimal_data["usr_id"]
        assert sess["is_admin"] is False


# This proves a correct email/password pair authenticates and fully populates the session.


def test_logging_in_with_the_wrong_password_shows_a_generic_error(client, seed_minimal_data):
    response = client.post(
        "/login",
        data={"email": "test@x.com", "password": "not-the-right-password"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert b"Invalid credentials" in response.data
    with client.session_transaction() as sess:
        assert "usr_id" not in sess


# This proves a wrong password is rejected with a generic error and never populates the session.


def test_repeated_failed_login_attempts_are_never_throttled(client, seed_minimal_data):
    """There is no rate limiting, lockout, or delay on /login in the current
    code, so ten consecutive wrong-password attempts should behave
    identically to a single attempt: no lockout status code, no escalating
    error, and the account remains loggable-into on the next correct try."""
    for _ in range(10):
        response = client.post(
            "/login",
            data={"email": "test@x.com", "password": "wrong"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert b"Invalid credentials" in response.data

    # The account must still be usable — proves nothing locked it.
    response = client.post(
        "/login",
        data={"email": "test@x.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert response.status_code == 302


# This proves ten consecutive failed attempts are not throttled, locked out, or delayed in any way — a real gap, not a defended design choice.
