"""Unit tests for POST /profile/edit (phone, preferences, allergies).

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``proj2/CSC510_DB.db``.

The route guards on ``session['usr_id']``. ``POST /login`` sets that key, so
no extra ``GET /profile`` round trip is needed before editing. Each test
creates its own user because ``temp_db_path`` is session-scoped.
"""
from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


def _make_user(temp_db_path, email, phone="9195550300", preferences="vegetarian", allergies="peanuts"):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Uc10","Tester",?,?,?,0,?,?)''',
            (email, phone, generate_password_hash(PASSWORD), preferences, allergies),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _profile_fields(temp_db_path, usr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(
            conn, 'SELECT phone, preferences, allergies FROM "User" WHERE usr_id = ?', (usr_id,)
        )
    finally:
        close_connection(conn)


def _login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 302


def test_editing_the_profile_writes_the_new_values_to_both_the_database_and_the_session(
    client, temp_db_path
):
    usr_id = _make_user(temp_db_path, "uc10-happy@example.test")
    _login(client, "uc10-happy@example.test")

    response = client.post(
        "/profile/edit",
        data={"phone": "9195559999", "preferences": "vegan", "allergies": "shellfish"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile" in response.headers["Location"]
    assert _profile_fields(temp_db_path, usr_id) == ("9195559999", "vegan", "shellfish")
    with client.session_transaction() as sess:
        assert sess["Phone"] == "9195559999"
        assert sess["Preferences"] == "vegan"
        assert sess["Allergies"] == "shellfish"


# This proves a valid profile edit persists phone, preferences and allergies to the User row and mirrors them into the active session before redirecting.


def test_submitting_an_empty_allergies_field_silently_keeps_the_stored_allergy(client, temp_db_path):
    """Each field is resolved with an ``or`` fallback to the current value:

        new_allergies = request.form.get('allergies') or user['allergies']

    An empty submitted string is falsy, so it never reaches the UPDATE. The
    route reports success either way, so the form gives no sign the value was
    ignored.
    """
    usr_id = _make_user(temp_db_path, "uc10-clear@example.test", allergies="peanuts")
    _login(client, "uc10-clear@example.test")

    response = client.post(
        "/profile/edit",
        data={"phone": "9195550300", "preferences": "vegetarian", "allergies": ""},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile" in response.headers["Location"]
    assert _profile_fields(temp_db_path, usr_id)[2] == "peanuts"
    with client.session_transaction() as sess:
        assert sess["Allergies"] == "peanuts"


# This proves a user who clears the allergies box is told the edit succeeded while the old allergy stays on file -- there is no way to remove an allergy once entered, and allergies feed meal generation, so this is a safety-relevant defect.


def test_the_phone_validation_enforced_at_registration_is_not_enforced_on_edit(client, temp_db_path):
    """POST /register normalises phone with ``re.sub(r"\\D+", "", phone)`` and
    rejects anything under seven digits. POST /profile/edit applies neither
    rule and writes the raw submitted string.
    """
    usr_id = _make_user(temp_db_path, "uc10-phone@example.test", phone="9195550300")
    _login(client, "uc10-phone@example.test")

    rejected_at_registration = client.post(
        "/register",
        data={
            "fname": "Uc10",
            "lname": "Tester",
            "email": "uc10-phone-reg@example.test",
            "phone": "not-a-phone",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )
    assert rejected_at_registration.status_code == 200
    assert "valid phone number" in rejected_at_registration.get_data(as_text=True)

    accepted_at_edit = client.post(
        "/profile/edit",
        data={"phone": "not-a-phone", "preferences": "vegetarian", "allergies": "peanuts"},
        follow_redirects=False,
    )

    assert accepted_at_edit.status_code == 302
    assert _profile_fields(temp_db_path, usr_id)[0] == "not-a-phone"


# This proves the same phone string is rejected on the create path and stored verbatim on the update path, so registration validation can be bypassed by editing afterwards -- a real defect.
