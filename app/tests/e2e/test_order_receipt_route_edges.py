import sqlite3

from sqlQueries import create_connection, close_connection, execute_query, fetch_one


def test_order_receipt_requires_login_redirects(client, temp_db_path, seed_minimal_data):
    resp = client.get("/orders/1/receipt.pdf", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("Location", "")


def _insert_order_for_user(db_path, usr_id, rtr_id):
    conn = create_connection(db_path)
    try:
        execute_query(
            conn,
            'INSERT INTO "Order"(rtr_id, usr_id, details, status) VALUES (?,?,?,?)',
            (rtr_id, usr_id, "{}", "paid"),
        )
        row = fetch_one(conn, 'SELECT ord_id FROM "Order" WHERE usr_id = ? ORDER BY ord_id DESC', (usr_id,))
        return row[0]
    finally:
        close_connection(conn)


def test_order_receipt_404_when_order_missing(client, login_session):
    resp = client.get("/orders/999999/receipt.pdf", follow_redirects=False)
    assert resp.status_code == 404


def test_order_receipt_403_when_order_belongs_to_other_user(client, temp_db_path, seed_minimal_data, login_session):
    data = seed_minimal_data
    rtr_id = data["rtr_id"]

    # Create a second user directly in the DB
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            'INSERT INTO "User"(first_name, last_name, email, phone, password_HS, wallet, preferences, allergies) '
            'VALUES ("Other","User","other@example.com","5550000","x",0,"","")'
        )
        row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', ("other@example.com",))
        other_usr_id = row[0]
    finally:
        close_connection(conn)

    ord_id = _insert_order_for_user(temp_db_path, other_usr_id, rtr_id)

    # Logged-in seeded user should not be allowed to view this receipt
    resp = client.get(f"/orders/{ord_id}/receipt.pdf", follow_redirects=False)
    assert resp.status_code == 403


def test_order_receipt_403_when_usr_id_missing_and_email_mismatch(client, temp_db_path, seed_minimal_data, login_session):
    data = seed_minimal_data
    rtr_id = data["rtr_id"]

    # Create a second user and order for them
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            'INSERT INTO "User"(first_name, last_name, email, phone, password_HS, wallet, preferences, allergies) '
            'VALUES ("Third","User","third@example.com","5550001","x",0,"","")'
        )
        row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', ("third@example.com",))
        third_usr_id = row[0]
    finally:
        close_connection(conn)

    ord_id = _insert_order_for_user(temp_db_path, third_usr_id, rtr_id)

    # Drop usr_id from the session so the route resolves by email instead
    with client.session_transaction() as s:
        assert s.get("Email")
        s.pop("usr_id", None)

    resp = client.get(f"/orders/{ord_id}/receipt.pdf", follow_redirects=False)
    assert resp.status_code == 403
