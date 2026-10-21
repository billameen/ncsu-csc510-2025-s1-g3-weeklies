from flask import session
from datetime import date

def test_login_sets_session_fields(client, seed_minimal_data):
    resp = client.post(
        "/login",
        data={"email": "test@x.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)  # redirect to index
    with client.session_transaction() as s:
        assert s.get("Email") == "test@x.com"
        assert s.get("Username")
        assert s.get("usr_id")

def test_profile_redirects_to_logout_when_email_missing(client, login_session):
    # simulate broken session with no Email
    with client.session_transaction() as s:
        s.pop("Email", None)
    r = client.get("/profile", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/logout" in r.headers.get("Location","")

def test_change_password_resolves_usr_id_by_email(client, login_session):
    # drop usr_id to force code path that resolves by email
    with client.session_transaction() as s:
        s.pop("usr_id", None)
    r = client.post("/profile/change-password", data={
        "current_password":"secret123",
        "new_password":"newpass1",
        "confirm_password":"newpass1",
    }, follow_redirects=False)
    # should redirect back to /profile?pw_updated=1 on success
    assert r.status_code in (302, 303)
    assert "pw_updated=1" in r.headers.get("Location","")

def test_index_specific_year_month_ok(client, login_session):
    today = date.today()
    # target previous month explicitly
    month = today.month - 1 or 12
    year = today.year if today.month > 1 else today.year - 1
    r = client.get(f"/{year}/{month}")
    assert r.status_code == 200
