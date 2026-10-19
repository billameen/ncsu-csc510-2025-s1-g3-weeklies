"""Edit Profile saves the planner's daily calorie target and weekly budget, or explains why not."""

import pytest
from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


@pytest.fixture()
def user(client, temp_db_path, request):
    """A fresh logged-in user (the test DB is shared by the whole session)."""
    email = f"targets-{request.node.name}@example.test"[:120]
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            """INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,
                                  preferences,allergies,daily_calorie_target,weekly_budget_cents)
               VALUES ("Plan","Tester",?,?,?,0,"vegetarian","Peanuts",2000,15000)""",
            (email, f"919{abs(hash(email)) % 10_000_000:07d}", generate_password_hash(PASSWORD)),
        )
        usr_id = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)
    resp = client.post("/login", data={"email": email, "password": PASSWORD})
    assert resp.status_code == 302
    return usr_id


def _targets(temp_db_path, usr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(
            conn,
            'SELECT daily_calorie_target, weekly_budget_cents FROM "User" WHERE usr_id = ?',
            (usr_id,),
        )
    finally:
        close_connection(conn)


def _edit(client, **fields):
    data = {"phone": "9195550000", "preferences": "vegetarian", "allergies": "Peanuts"}
    data.update(fields)
    return client.post("/profile/edit", data=data)


def test_valid_targets_are_saved_with_the_budget_in_cents(client, temp_db_path, user):
    resp = _edit(client, daily_calorie_target="2,400", weekly_budget="$175.50")

    assert resp.status_code == 302
    assert _targets(temp_db_path, user) == (2400, 17550)


def test_blank_targets_clear_them(client, temp_db_path, user):
    resp = _edit(client, daily_calorie_target="", weekly_budget="")

    assert resp.status_code == 302
    assert _targets(temp_db_path, user) == (None, None)


def test_a_form_without_the_target_fields_keeps_the_stored_targets(client, temp_db_path, user):
    assert _edit(client).status_code == 302
    assert _targets(temp_db_path, user) == (2000, 15000)


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"daily_calorie_target": "lots"}, "whole number"),
        ({"daily_calorie_target": "99999"}, "between"),
        ({"weekly_budget": "cheap"}, "dollars"),
        ({"weekly_budget": "0"}, "between"),
    ],
)
def test_bad_targets_are_rejected_and_nothing_is_saved(client, temp_db_path, user, fields, message):
    resp = _edit(client, phone="9195551111", **fields)

    assert resp.status_code == 400
    page = resp.get_data(as_text=True)
    assert message in page
    assert 'aria-invalid="true"' in page
    # What the user typed stays in the box so they can fix it.
    assert f'value="{next(iter(fields.values()))}"' in page
    assert _targets(temp_db_path, user) == (2000, 15000)
    conn = create_connection(temp_db_path)
    try:
        phone = fetch_one(conn, 'SELECT phone FROM "User" WHERE usr_id = ?', (user,))[0]
    finally:
        close_connection(conn)
    assert phone != "9195551111"  # the rest of the form is not saved either


def test_edit_form_and_profile_page_show_the_current_targets(client, user):
    form = client.get("/profile/edit").get_data(as_text=True)
    assert 'name="daily_calorie_target"' in form and 'value="2000"' in form
    assert 'name="weekly_budget"' in form and 'value="150.00"' in form

    page = client.get("/profile").get_data(as_text=True)
    assert "2,000" in page and "$ 150.00" in page


def test_a_superscript_digit_is_a_form_error_not_a_500(client, temp_db_path, user):
    """Found in review: "2000²".isdigit() is True but int() rejects it."""
    resp = _edit(client, daily_calorie_target="2000²")
    assert resp.status_code == 400
    assert _targets(temp_db_path, user) == (2000, 15000)
