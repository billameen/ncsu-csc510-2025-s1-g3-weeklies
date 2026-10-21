"""Checkout charges each restaurant's own fees (M4), through the M2 wallet ledger."""
import json

from werkzeug.security import generate_password_hash

from sqlQueries import close_connection, create_connection, execute_query, fetch_one
from wallet_helpers import wallet_cents

PASSWORD = "secret123"


def _user(db, email, phone, cents):
    conn = create_connection(db)
    try:
        execute_query(conn, '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
                               VALUES ("Fee","Tester",?,?,?,?,"","")''',
                      (email, phone, generate_password_hash(PASSWORD), cents))
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _restaurant(db, name, delivery_fee_cents=None):
    conn = create_connection(db)
    try:
        execute_query(conn, '''INSERT INTO "Restaurant"(name,address,city,state,zip,status)
                               VALUES (?, "1 Way", "Raleigh", "NC", "27606", "open")''', (name,))
        rtr_id = fetch_one(conn, 'SELECT rtr_id FROM "Restaurant" WHERE name = ?', (name,))[0]
        execute_query(conn, '''INSERT INTO "MenuItem"(rtr_id,name,description,price,calories,instock,allergens)
                               VALUES (?, ?, "x", 1000, 100, 1, "")''', (rtr_id, name + " Plate"))
        itm_id = fetch_one(conn, 'SELECT max(itm_id) FROM "MenuItem" WHERE rtr_id = ?', (rtr_id,))[0]
        if delivery_fee_cents is not None:
            execute_query(conn, 'INSERT INTO "RestaurantFee" VALUES (?, ?, NULL)', (rtr_id, delivery_fee_cents))
        return rtr_id, itm_id
    finally:
        close_connection(conn)


def _order(client, rtr_id, itm_id, delivery_type="delivery"):
    resp = client.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": itm_id}],
                                       "delivery_type": delivery_type})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["ord_id"]


def _charges(db, ord_id):
    conn = create_connection(db)
    try:
        return json.loads(fetch_one(conn, 'SELECT details FROM "Order" WHERE ord_id = ?', (ord_id,))[0])["charges_cents"]
    finally:
        close_connection(conn)


def _login(client, email):
    assert client.post("/login", data={"email": email, "password": PASSWORD}).status_code == 302


def test_checkout_charges_the_restaurants_own_delivery_fee(client, temp_db_path):
    usr = _user(temp_db_path, "fee-own@example.test", "9195552001", 5000)
    rtr_id, itm_id = _restaurant(temp_db_path, "Cheap Delivery Cafe", delivery_fee_cents=199)
    _login(client, "fee-own@example.test")

    charges = _charges(temp_db_path, _order(client, rtr_id, itm_id))

    assert charges["delivery_fee"] == 199 and charges["service_fee"] == 149
    assert charges["total"] == 1000 + 73 + 199 + 149
    assert wallet_cents(temp_db_path, usr) == 5000 - charges["total"]


def test_a_restaurant_without_its_own_fees_charges_the_defaults(client, temp_db_path):
    _user(temp_db_path, "fee-default@example.test", "9195552002", 5000)
    rtr_id, itm_id = _restaurant(temp_db_path, "Default Fee Cafe")
    _login(client, "fee-default@example.test")

    charges = _charges(temp_db_path, _order(client, rtr_id, itm_id))

    assert (charges["delivery_fee"], charges["service_fee"], charges["total"]) == (399, 149, 1621)


def test_pickup_at_checkout_skips_the_restaurants_delivery_fee(client, temp_db_path):
    _user(temp_db_path, "fee-pickup@example.test", "9195552003", 5000)
    rtr_id, itm_id = _restaurant(temp_db_path, "Pricey Delivery Cafe", delivery_fee_cents=599)
    _login(client, "fee-pickup@example.test")

    charges = _charges(temp_db_path, _order(client, rtr_id, itm_id, "pickup"))

    assert charges["delivery_fee"] == 0 and charges["total"] == 1000 + 73 + 149
