"""Unit tests for POST /profile/change-password.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``proj2/CSC510_DB.db``.

Each test creates its own user because ``temp_db_path`` is session-scoped and
these tests mutate the stored password hash.
"""
from werkzeug.security import check_password_hash, generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


def _make_user(temp_db_path, email, password=PASSWORD):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Uc11","Tester",?,"9195550400",?,0,"","")''',
            (email, generate_password_hash(password)),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _stored_hash(temp_db_path, usr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(conn, 'SELECT password_HS FROM "User" WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)


def _login(client, email, password=PASSWORD):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def test_changing_the_password_rehashes_the_new_value_and_lets_it_log_in(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc11-happy@example.test")
    assert _login(client, "uc11-happy@example.test").status_code == 302
    original_hash = _stored_hash(temp_db_path, usr_id)

    response = client.post(
        "/profile/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "brandnew99",
            "confirm_password": "brandnew99",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile?pw_updated=1" in response.headers["Location"]
    new_hash = _stored_hash(temp_db_path, usr_id)
    assert new_hash != original_hash
    assert check_password_hash(new_hash, "brandnew99")
    client.get("/logout")
    assert _login(client, "uc11-happy@example.test", "brandnew99").status_code == 302


# This proves a correct current password produces a fresh hash for the new password and that the new password is what actually authenticates afterwards.


def test_a_wrong_current_password_is_rejected_without_touching_the_stored_hash(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc11-wrong@example.test")
    assert _login(client, "uc11-wrong@example.test").status_code == 302
    original_hash = _stored_hash(temp_db_path, usr_id)

    response = client.post(
        "/profile/change-password",
        data={
            "current_password": "not-my-password",
            "new_password": "brandnew99",
            "confirm_password": "brandnew99",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile?pw_error=incorrect_current" in response.headers["Location"]
    assert _stored_hash(temp_db_path, usr_id) == original_hash
    client.get("/logout")
    assert _login(client, "uc11-wrong@example.test", PASSWORD).status_code == 302


# This proves the current-password check is enforced against the stored hash and that a failed attempt leaves the account's original password working -- the documented failure path behaves as specified.


def test_a_new_password_with_surrounding_whitespace_is_silently_stripped_before_hashing(
    client, temp_db_path
):
    """The change-password route strips every field it reads:

        new_password = (request.form.get('new_password') or '').strip()

    Neither ``/register`` nor ``/login`` strips the password, so the value
    that gets hashed here is not the value the user typed, and the value they
    typed no longer authenticates.
    """
    _make_user(temp_db_path, "uc11-space@example.test")
    assert _login(client, "uc11-space@example.test").status_code == 302

    response = client.post(
        "/profile/change-password",
        data={
            "current_password": PASSWORD,
            "new_password": "  spaced99  ",
            "confirm_password": "  spaced99  ",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile?pw_updated=1" in response.headers["Location"]
    client.get("/logout")

    typed = _login(client, "uc11-space@example.test", "  spaced99  ")
    assert typed.status_code == 200
    assert "Invalid credentials" in typed.get_data(as_text=True)

    stripped = _login(client, "uc11-space@example.test", "spaced99")
    assert stripped.status_code == 302


# This proves the route reports success while storing a password different from the one submitted, locking the user out with the exact string they just chose -- /register and /login do not strip, so only this route disagrees, a real defect.
