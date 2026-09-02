"""Unit tests for GET /orders.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``app``/``client``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database. ``seed_minimal_data`` seeds one restaurant ("Cafe One") and two
in-stock items (Pasta, Salad) under it, and ``login_session`` logs in that
seeded user (test@x.com / secret123). These tests do not touch
``proj2/CSC510_DB.db``.
"""

from sqlQueries import close_connection, create_connection, execute_query


def _insert_item(temp_db_path, rtr_id, name, instock):
    """Insert one MenuItem row under rtr_id with the given instock value
    (pass None to leave the column NULL)."""
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "MenuItem"(rtr_id,name,description,price,calories,instock,allergens)
               VALUES (?, ?, "test item", 500, 100, ?, "")''',
            (rtr_id, name, instock),
        )
    finally:
        close_connection(conn)


def test_browsing_orders_while_logged_in_lists_the_seeded_restaurant_and_its_in_stock_items(
    client, seed_minimal_data, login_session
):
    response = client.get("/orders")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Cafe One" in page
    assert "Pasta" in page
    assert "Salad" in page


# This proves an authenticated GET /orders renders 200 with the seeded restaurant and its in-stock menu items.


def test_an_item_with_instock_explicitly_zero_is_left_off_the_orders_page(
    client, seed_minimal_data, login_session, temp_db_path
):
    _insert_item(temp_db_path, seed_minimal_data["rtr_id"], "Out of Stock Burger", 0)

    response = client.get("/orders")

    assert response.status_code == 200
    assert "Out of Stock Burger" not in response.get_data(as_text=True)


# This proves the WHERE instock IS NULL OR instock = 1 clause excludes an item whose instock is explicitly 0.


def test_an_item_with_a_null_instock_value_is_treated_as_in_stock_and_shown(
    client, seed_minimal_data, login_session, temp_db_path
):
    _insert_item(temp_db_path, seed_minimal_data["rtr_id"], "Mystery NULL-Stock Wrap", None)

    response = client.get("/orders")

    assert response.status_code == 200
    assert "Mystery NULL-Stock Wrap" in response.get_data(as_text=True)


# This proves a NULL instock value is treated as in-stock (per the "instock IS NULL OR instock = 1" clause) and the item is shown, not hidden by default.
