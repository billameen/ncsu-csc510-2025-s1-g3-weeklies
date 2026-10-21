"""Unit tests for POST /register.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed.  The shared ``app`` fixture in
``app/tests/conftest.py`` points Flask at a disposable SQLite database, so
these tests do not modify ``app/CSC510_DB.db``.
"""

import pytest
from werkzeug.security import check_password_hash

from sqlQueries import close_connection, create_connection, fetch_one


def _registration_data(**overrides):
    """Return valid registration form data, optionally overridden per test."""
    data = {
        "fname": "Ada",
        "lname": "Lovelace",
        "email": "ada.lovelace@example.test",
        "phone": "(919) 555-0123",
        "password": "secret123",
        "confirm_password": "secret123",
        "preferences": "vegetarian",
        "allergies": "peanuts",
    }
    data.update(overrides)
    return data


def _user_by_email(temp_db_path, email):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(
            conn,
            '''SELECT first_name, last_name, email, phone, password_HS, wallet,
                      preferences, allergies
               FROM "User" WHERE email = ?''',
            (email,),
        )
    finally:
        close_connection(conn)


def test_registering_with_valid_details_creates_a_hashed_user_record(client, temp_db_path):
    form = _registration_data()

    response = client.post("/register", data=form, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    user = _user_by_email(temp_db_path, form["email"])
    assert user is not None
    assert user[:4] == ("Ada", "Lovelace", form["email"], "9195550123")
    assert check_password_hash(user[4], form["password"])
    assert user[4] != form["password"]
    assert user[5:] == (0, "vegetarian", "peanuts")


# This proves a valid registration hashes its password and stores the expected user data before redirecting to login.


@pytest.mark.parametrize("allergies", ["peenuts", "Peanuts,Sulphites", "Dairy"])
def test_registering_with_an_unknown_allergy_is_rejected(client, temp_db_path, allergies):
    """Allergies feed meal-plan filtering, so only the selectable allergens are
    accepted. "Sulphites" is no longer offered (no menu data tracks it), and
    "Dairy" is a menu tag rather than a selectable allergy (users pick Milk/Lactose).
    """
    form = _registration_data(
        email=f"unknown-allergy-{allergies.lower().replace(',', '-')}@example.test",
        allergies=allergies,
    )

    response = client.post("/register", data=form, follow_redirects=False)

    assert response.status_code == 200
    assert "Unknown allergy" in response.get_data(as_text=True)
    assert _user_by_email(temp_db_path, form["email"]) is None


# This proves a misspelled or unsupported allergy is refused at registration instead of being stored and then matching nothing.


def test_registering_with_known_allergies_in_any_case_is_accepted(client, temp_db_path):
    form = _registration_data(email="known-allergies@example.test", allergies="tree nuts,MILK")

    response = client.post("/register", data=form, follow_redirects=False)

    assert response.status_code == 302
    assert _user_by_email(temp_db_path, form["email"])[7] == "tree nuts,MILK"


# This proves selectable allergens are accepted regardless of case.

def test_registering_with_an_unverified_but_well_formed_email_creates_the_account(client, temp_db_path):
    form = _registration_data(email="address-not-owned@unverified.example")

    response = client.post("/register", data=form, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert _user_by_email(temp_db_path, form["email"]) is not None


# This proves registration accepts a well-formed email address without an email-verification step.
