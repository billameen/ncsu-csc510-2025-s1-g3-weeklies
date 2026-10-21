"""Unit tests for POST /profile/edit (phone, preferences, allergies).

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``client``/``temp_db_path``
fixtures in ``app/tests/conftest.py`` point Flask at a disposable SQLite
database, so these tests never touch ``app/CSC510_DB.db``.

The route guards on ``session['usr_id']``. ``POST /login`` sets that key, so
no extra ``GET /profile`` round trip is needed before editing. Each test
creates its own user because ``temp_db_path`` is session-scoped.
"""
import pytest
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


def test_submitting_empty_allergies_and_preferences_clears_them(client, temp_db_path):
    """Fields used to be resolved with an ``or`` fallback to the current value,
    so an empty submission silently kept the old allergy. Only an absent field
    falls back now; a present-but-empty one clears the value.
    """
    usr_id = _make_user(temp_db_path, "uc10-clear@example.test", allergies="peanuts")
    _login(client, "uc10-clear@example.test")

    response = client.post(
        "/profile/edit",
        data={"phone": "9195550300", "preferences": "", "allergies": ""},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile" in response.headers["Location"]
    assert _profile_fields(temp_db_path, usr_id) == ("9195550300", "", "")
    with client.session_transaction() as sess:
        assert sess["Allergies"] == ""
        assert sess["Preferences"] == ""


# This proves a user can remove every allergy and preference, and the cleared values reach both the database and the session.


def test_omitted_fields_and_an_empty_phone_keep_their_stored_values(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc10-keep@example.test", allergies="peanuts")
    _login(client, "uc10-keep@example.test")

    response = client.post("/profile/edit", data={"phone": ""}, follow_redirects=False)

    assert response.status_code == 302
    assert _profile_fields(temp_db_path, usr_id) == ("9195550300", "vegetarian", "peanuts")


# This proves fields absent from the form keep their stored values, and an empty phone does not wipe the number collected at registration.


@pytest.mark.parametrize("allergies", ["peenuts", "Peanuts,Sulphites"])
def test_an_unknown_allergy_on_edit_is_rejected_and_nothing_is_saved(client, temp_db_path, allergies):
    email = f"uc10-unknown-{allergies.lower().replace(',', '-')}@example.test"
    usr_id = _make_user(temp_db_path, email, allergies="peanuts")
    _login(client, email)

    response = client.post(
        "/profile/edit",
        data={"phone": "9195550300", "preferences": "vegetarian", "allergies": allergies},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Unknown allergy" in response.get_data(as_text=True)
    assert _profile_fields(temp_db_path, usr_id)[2] == "peanuts"


# This proves an allergy the meal-plan filter cannot match is refused on edit instead of being saved and silently ignored.

@pytest.mark.parametrize("phone", ["not-a-phone", "555-12", "abc 123 def"])
def test_an_invalid_phone_is_rejected_on_edit_just_as_it_is_at_registration(client, temp_db_path, phone):
    """POST /register and POST /profile/edit share ``_normalize_phone``: both
    strip non-digits and require at least seven, with the same error message.
    """
    email = f"uc10-phone-{phone.replace(' ', '-')}@example.test"
    usr_id = _make_user(temp_db_path, email, phone="9195550300")
    _login(client, email)

    rejected_at_registration = client.post(
        "/register",
        data={
            "fname": "Uc10",
            "lname": "Tester",
            "email": f"reg-{email}",
            "phone": phone,
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )
    assert rejected_at_registration.status_code == 200
    assert "Please enter a valid phone number" in rejected_at_registration.get_data(as_text=True)

    rejected_at_edit = client.post(
        "/profile/edit",
        data={"phone": phone, "preferences": "vegetarian", "allergies": "peanuts"},
        follow_redirects=False,
    )

    assert rejected_at_edit.status_code == 400
    assert "Please enter a valid phone number" in rejected_at_edit.get_data(as_text=True)
    assert _profile_fields(temp_db_path, usr_id)[0] == "9195550300"
    with client.session_transaction() as sess:
        assert sess["Phone"] == "9195550300"


# This proves a phone rejected at registration is also rejected on edit, with the same message, and the stored number is left alone.


def test_a_formatted_phone_on_edit_is_stored_as_digits_like_registration(client, temp_db_path):
    usr_id = _make_user(temp_db_path, "uc10-format@example.test", phone="9195550300")
    _login(client, "uc10-format@example.test")

    response = client.post(
        "/profile/edit",
        data={"phone": "(919) 555-0123", "preferences": "vegetarian", "allergies": "peanuts"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert _profile_fields(temp_db_path, usr_id)[0] == "9195550123"
    with client.session_transaction() as sess:
        assert sess["Phone"] == "9195550123"


# This proves a phone edited with punctuation is saved in the same digits-only format /register uses, in both the database and the session.
