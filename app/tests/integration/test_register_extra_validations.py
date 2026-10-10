import re

def test_register_requires_first_and_last_name(client):
    resp = client.post(
        "/register",
        data={
            "fname": "",
            "lname": "",
            "email": "user@example.com",
            "phone": "1234567",
            "password": "abcdef",
            "confirm_password": "abcdef",
        },
    )
    assert resp.status_code == 200
    assert b"First and last name are required" in resp.data


def test_register_password_mismatch(client):
    resp = client.post(
        "/register",
        data={
            "fname": "A",
            "lname": "B",
            "email": "mismatch@example.com",
            "phone": "1234567",
            "password": "abcdef",
            "confirm_password": "zzzxxx",
        },
    )
    assert resp.status_code == 200
    assert b"Passwords do not match" in resp.data


def test_register_password_too_short(client):
    resp = client.post(
        "/register",
        data={
            "fname": "A",
            "lname": "B",
            "email": "short@example.com",
            "phone": "1234567",
            "password": "123",
            "confirm_password": "123",
        },
    )
    assert resp.status_code == 200
    assert b"Password must be at least 6 characters" in resp.data


def test_register_bad_phone_number(client):
    resp = client.post(
        "/register",
        data={
            "fname": "A",
            "lname": "B",
            "email": "phone@example.com",
            "phone": "12-34",  # fewer than 7 digits after stripping
            "password": "abcdef",
            "confirm_password": "abcdef",
        },
    )
    assert resp.status_code == 200
    assert b"Please enter a valid phone number" in resp.data


def test_register_duplicate_email_uses_exists_check(client, seed_minimal_data):
    # seed_minimal_data creates a user with email 'test@x.com'
    resp = client.post(
        "/register",
        data={
            "fname": "New",
            "lname": "User",
            "email": "test@x.com",
            "phone": "5557777",
            "password": "abcdef",
            "confirm_password": "abcdef",
        },
    )
    assert resp.status_code == 200
    assert b"Email already registered" in resp.data
