from sqlQueries import create_connection, close_connection, execute_query, fetch_one


def test_profile_requires_login_redirects(client):
    resp = client.get("/profile", follow_redirects=False)
    # Should redirect unauthenticated users to login
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("Location", "")


def test_logout_clears_identity_and_redirects(client, login_session):
    # Ensure the session has some of the expected keys
    with client.session_transaction() as s:
        s["ExtraKey"] = "value"
        assert s.get("Username")
        assert s.get("Email")

    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("Location", "")

    # After logout, identity-related keys should be gone.
    # We do NOT require that arbitrary keys (like ExtraKey) are removed.
    with client.session_transaction() as s:
        for key in [
            "Username",
            "Fname",
            "Lname",
            "Email",
            "Phone",
            "Wallet",
            "Preferences",
            "Allergies",
            "GeneratedMenu",
        ]:
            assert key not in s


def test_edit_profile_get_renders_for_logged_in_user(client, login_session):
    r = client.get("/profile/edit")
    assert r.status_code == 200


def test_edit_profile_requires_login(client):
    r = client.get("/profile/edit", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers.get("Location", "")


def test_edit_profile_missing_usr_id_redirects_logout(client, login_session):
    # Remove usr_id to trigger the guard
    with client.session_transaction() as s:
        s.pop("usr_id", None)
    r = client.get("/profile/edit", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/logout" in r.headers.get("Location", "")


def test_edit_profile_invalid_usr_id_row_redirects_logout(client, login_session, temp_db_path):
    # Point session usr_id to a non-existent user
    with client.session_transaction() as s:
        s["usr_id"] = 999999

    r = client.get("/profile/edit", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/logout" in r.headers.get("Location", "")


def test_edit_profile_post_updates_user_and_session(client, login_session, temp_db_path):
    new_phone = "9195551234"
    new_prefs = "Spicy, Vegan"
    new_allergies = "Peanuts"

    resp = client.post(
        "/profile/edit",
        data={
            "phone": new_phone,
            "preferences": new_prefs,
            "allergies": new_allergies,
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert "/profile" in resp.headers.get("Location", "")

    # Session should be updated with new values
    with client.session_transaction() as s:
        assert s.get("Phone") == new_phone
        assert s.get("Preferences") == new_prefs
        assert s.get("Allergies") == new_allergies
