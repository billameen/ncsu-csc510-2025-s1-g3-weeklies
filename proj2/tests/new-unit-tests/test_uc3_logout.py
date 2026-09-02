"""Unit tests for GET /logout.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``app``/``client``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database seeded by ``seed_minimal_data`` (user test@x.com / secret123), so
these tests do not touch ``proj2/CSC510_DB.db``.
"""

SESSION_KEYS = [
    "Username", "Fname", "Lname", "Email", "Phone",
    "Wallet", "Preferences", "Allergies", "GeneratedMenu",
    "is_admin", "usr_id",
]


def test_logging_out_of_a_full_session_clears_every_identity_key(client, seed_minimal_data):
    client.post(
        "/login",
        data={"email": "test@x.com", "password": "secret123"},
        follow_redirects=False,
    )
    with client.session_transaction() as sess:
        assert sess["Email"] == "test@x.com"

    response = client.get("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        for key in SESSION_KEYS:
            assert key not in sess


# This proves logging out of a fully populated session pops every identity/profile/wallet/admin key and redirects to /login.


def test_logging_out_of_a_session_missing_some_keys_does_not_error(client):
    with client.session_transaction() as sess:
        sess["Username"] = "Partial User"
        # Fname, Lname, Wallet, is_admin, etc. are deliberately absent.

    response = client.get("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert "Username" not in sess


# This proves session.pop(k, None) tolerates a session missing most of the expected keys instead of raising KeyError.


def test_logging_out_twice_in_a_row_behaves_the_same_both_times(client, seed_minimal_data):
    client.post(
        "/login",
        data={"email": "test@x.com", "password": "secret123"},
        follow_redirects=False,
    )

    first = client.get("/logout", follow_redirects=False)
    second = client.get("/logout", follow_redirects=False)

    assert first.status_code == 302
    assert second.status_code == 302
    assert first.headers["Location"] == second.headers["Location"]
    with client.session_transaction() as sess:
        for key in SESSION_KEYS:
            assert key not in sess


# This proves logging out an already-empty session is idempotent — it redirects the same way and raises no error on the second call.
