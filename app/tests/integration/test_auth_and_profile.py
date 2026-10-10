import re
from werkzeug.security import check_password_hash
from sqlQueries import create_connection, close_connection, fetch_one

def test_register_login_profile_flow(client):
    # GET register
    r = client.get("/register")
    assert r.status_code == 200

    # POST invalid email
    r = client.post("/register", data={
        "fname":"A","lname":"B","email":"bad","phone":"1234567",
        "password":"abcdef","confirm_password":"abcdef"
    })
    assert b"valid email" in r.data

    # POST valid registration
    r = client.post("/register", data={
        "fname":"A","lname":"B","email":"ab@x.com","phone":"5557777",
        "password":"abcdef","confirm_password":"abcdef"
    }, follow_redirects=False)
    assert r.status_code in (302, 303) and "/login" in r.location

    # Wrong password
    r = client.post("/login", data={"email":"ab@x.com","password":"wrong"})
    assert r.status_code == 200
    assert b"Invalid credentials" in r.data

    # Correct login
    r = client.post("/login", data={"email":"ab@x.com","password":"abcdef"}, follow_redirects=False)
    assert r.status_code in (302, 303)

    # Profile requires session (simulate logged in by following redirect from login)
    r = client.get("/profile", follow_redirects=True)
    assert r.status_code == 200
    assert b"email" in r.data or b"orders" in r.data

def test_change_password_validations(client, seed_minimal_data):
    # login seeded user
    r = client.post("/login", data={"email":"test@x.com","password":"secret123"}, follow_redirects=False)
    assert r.status_code in (302, 303)

    # missing current
    r = client.post("/profile/change-password", data={
        "current_password":"",
        "new_password":"newpass",
        "confirm_password":"newpass"
    }, follow_redirects=False)
    assert "/profile?pw_error=missing_current" in r.location

    # too short
    r = client.post("/profile/change-password", data={
        "current_password":"secret123",
        "new_password":"123",
        "confirm_password":"123"
    }, follow_redirects=False)
    assert "/profile?pw_error=too_short" in r.location

    # mismatch
    r = client.post("/profile/change-password", data={
        "current_password":"secret123",
        "new_password":"abcdef",
        "confirm_password":"xyz"
    }, follow_redirects=False)
    assert "/profile?pw_error=mismatch" in r.location

    # incorrect current
    r = client.post("/profile/change-password", data={
        "current_password":"nope",
        "new_password":"abcdef",
        "confirm_password":"abcdef"
    }, follow_redirects=False)
    assert "/profile?pw_error=incorrect_current" in r.location

    # success
    r = client.post("/profile/change-password", data={
        "current_password":"secret123",
        "new_password":"abcdef",
        "confirm_password":"abcdef"
    }, follow_redirects=False)
    assert "/profile?pw_updated=1" in r.location
