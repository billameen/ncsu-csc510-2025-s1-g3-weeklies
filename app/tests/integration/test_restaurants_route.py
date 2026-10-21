def test_restaurants_requires_login_redirects(client):
    resp = client.get("/restaurants", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("Location", "")


def test_restaurants_renders_for_logged_in_user(client, seed_minimal_data, login_session):
    resp = client.get("/restaurants")
    assert resp.status_code == 200
    # Seeded restaurant name should appear
    assert b"Cafe One" in resp.data
