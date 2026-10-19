"""Regression tests for M2 bug 4: concurrent gifts can overdraw the sender.

``/profile/wallet/gift`` read the sender's balance, compared it to the
amount, and then ran an unguarded ``UPDATE ... SET wallet = wallet - ?``.
Two gifts sent at once can both pass the check before either debits, so a
$10.00 balance can send two $6.00 gifts and end at -$2.00.

``test_interleaved_gifts_cannot_overdraw`` reproduces that interleaving
deterministically: it pauses the first gift right after its balance check
and runs the second gift to completion in the gap.
"""
import threading

import pytest
from werkzeug.security import generate_password_hash

import Flask_app
from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"


def _make_user(db, email, phone, wallet_cents):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Gift","Tester",?,?,?,?,"","")''',
            (email, phone, generate_password_hash(PASSWORD), wallet_cents),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _wallet(db, usr_id):
    conn = create_connection(db)
    try:
        return fetch_one(conn, 'SELECT wallet FROM "User" WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)


def _login(c, email):
    assert c.post("/login", data={"email": email, "password": PASSWORD}).status_code == 302


def _gift(c, to_email, amount):
    return c.post("/profile/wallet/gift", data={"recipient_email": to_email, "amount": amount})


def test_interleaved_gifts_cannot_overdraw(app, client, temp_db_path, monkeypatch):
    sender = _make_user(temp_db_path, "race-sender@example.test", "9195558001", 1000)
    alice = _make_user(temp_db_path, "race-alice@example.test", "9195558002", 0)
    bob = _make_user(temp_db_path, "race-bob@example.test", "9195558003", 0)
    _login(client, "race-sender@example.test")

    second_device = app.test_client()
    _login(second_device, "race-sender@example.test")

    real_fetch_one = Flask_app.fetch_one
    state = {"fired": False, "second_location": None}

    def fetch_one_then_race(conn, query, params=()):
        row = real_fetch_one(conn, query, params)
        # The first gift has just read the sender's balance: run the second
        # gift to completion before the first one reaches its debit.
        if not state["fired"] and query.startswith('SELECT wallet FROM "User"'):
            state["fired"] = True
            state["second_location"] = _gift(second_device, "race-bob@example.test", "6.00").headers["Location"]
        return row

    monkeypatch.setattr(Flask_app, "fetch_one", fetch_one_then_race)

    first = _gift(client, "race-alice@example.test", "6.00")

    assert state["fired"]
    outcomes = sorted([first.headers["Location"], state["second_location"]])
    assert outcomes == ["/profile?wallet_error=insufficient_funds", "/profile?wallet_updated=gift"]
    assert _wallet(temp_db_path, sender) == 400
    assert _wallet(temp_db_path, alice) + _wallet(temp_db_path, bob) == 600


def test_many_concurrent_gifts_never_overdraw_or_lose_money(app, temp_db_path):
    sender = _make_user(temp_db_path, "race-many@example.test", "9195558010", 1000)
    receivers = [
        _make_user(temp_db_path, f"race-many-{i}@example.test", f"91955581{i:02d}", 0)
        for i in range(8)
    ]
    clients = [app.test_client() for _ in receivers]
    for c in clients:
        _login(c, "race-many@example.test")

    barrier = threading.Barrier(len(clients))
    locations = []

    def send(c, i):
        barrier.wait()
        locations.append(_gift(c, f"race-many-{i}@example.test", "3.00").headers["Location"])

    threads = [threading.Thread(target=send, args=(c, i)) for i, c in enumerate(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = locations.count("/profile?wallet_updated=gift")
    received = sum(_wallet(temp_db_path, r) for r in receivers)
    assert 1 <= successes <= 3                     # $10.00 covers at most three $3.00 gifts
    assert _wallet(temp_db_path, sender) >= 0
    assert _wallet(temp_db_path, sender) + received == 1000   # no money created or lost
    assert received == successes * 300


def test_gift_to_yourself_by_a_differently_cased_email_is_rejected(client, temp_db_path):
    me = _make_user(temp_db_path, "race-self@example.test", "9195558020", 1000)
    _login(client, "race-self@example.test")

    resp = _gift(client, "  RACE-Self@Example.TEST ", "1.00")

    assert resp.headers["Location"] == "/profile?wallet_error=self_gift"
    assert _wallet(temp_db_path, me) == 1000


def test_gift_refreshes_the_session_balance_from_the_database(app, client, temp_db_path):
    sender = _make_user(temp_db_path, "race-sync@example.test", "9195558030", 1000)
    _make_user(temp_db_path, "race-sync-to@example.test", "9195558031", 0)
    _login(client, "race-sync@example.test")
    with app.test_client() as other_device:
        _login(other_device, "race-sync@example.test")
        other_device.post("/profile/wallet/topup", data={"amount": "5.00"})

    _gift(client, "race-sync-to@example.test", "2.00")

    with client.session_transaction() as sess:
        assert sess["Wallet"] == _wallet(temp_db_path, sender) == 1300


def test_top_up_refreshes_the_session_balance_from_the_database(app, client, temp_db_path):
    me = _make_user(temp_db_path, "race-topup@example.test", "9195558040", 1000)
    _make_user(temp_db_path, "race-topup-to@example.test", "9195558041", 0)
    _login(client, "race-topup@example.test")
    with app.test_client() as other_device:
        _login(other_device, "race-topup@example.test")
        _gift(other_device, "race-topup-to@example.test", "4.00")

    client.post("/profile/wallet/topup", data={"amount": "1.00"})

    with client.session_transaction() as sess:
        assert sess["Wallet"] == _wallet(temp_db_path, me) == 700
