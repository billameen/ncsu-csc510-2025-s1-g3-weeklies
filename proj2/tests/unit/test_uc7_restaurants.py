"""Unit tests for GET /restaurants.

Environment assumptions: pytest is run from the repository root with the
project's Python dependencies installed. The shared ``app``/``client``
fixtures in ``proj2/tests/conftest.py`` point Flask at a disposable SQLite
database that is SESSION-scoped, i.e. shared across every test in this
file (and the rest of the suite). To keep each test's counts exact and
independent of test order, every test here creates its OWN restaurant
(and reuses ``seed_minimal_data``'s user only as a valid usr_id / for
login) rather than reusing ``seed_minimal_data``'s shared restaurant.
``login_session`` logs that seeded user in (test@x.com / secret123).
Nothing here touches ``proj2/CSC510_DB.db``. No LLM or network call is
involved in this route, so nothing needed mocking.

Claims under test (from reading Flask_app.py's restaurants() handler,
lines ~1250-1330):
  1. The Review query has no LIMIT/pagination — every review row for every
     restaurant is fetched every request.
  2. The server computes only {total_rating, count}, never an average — the
     divide (total_rating / count) happens in restaurants.html's client-side
     JS (`rev.count > 0 ? ... : '-'`), guarded there, NOT on the server. So
     a restaurant with zero reviews cannot crash the route (Python never
     divides), but the server itself enforces no guard — it just ships
     count=0 to the client and trusts the template's guard.
  3. review_rows uses `JOIN "User" u ON r.usr_id = u.usr_id`, a plain
     (inner) join. A review whose usr_id has no matching User row is
     dropped from review_rows entirely, so it is silently excluded from
     both the rating aggregate (total_rating, count) and the rendered
     review list for that restaurant.
"""

from sqlQueries import close_connection, create_connection, execute_query


def _insert_restaurant(temp_db_path, name):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "Restaurant"(name,address,city,state,zip,status)
               VALUES (?, "1 Test St", "Raleigh", "NC", "27606", "open")''',
            (name,),
        )
        from sqlQueries import fetch_one
        return fetch_one(conn, 'SELECT rtr_id FROM "Restaurant" WHERE name = ?', (name,))[0]
    finally:
        close_connection(conn)


def _insert_review(temp_db_path, rtr_id, usr_id, title, rating, description="test review"):
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            '''INSERT INTO "Review"(rtr_id, usr_id, title, rating, description)
               VALUES (?, ?, ?, ?, ?)''',
            (rtr_id, usr_id, title, rating, description),
        )
    finally:
        close_connection(conn)


def test_browsing_restaurants_while_logged_in_shows_the_restaurant_and_its_review_aggregate(
    client, seed_minimal_data, login_session, temp_db_path
):
    rtr_id = _insert_restaurant(temp_db_path, "Happy Path Bistro")
    _insert_review(temp_db_path, rtr_id, seed_minimal_data["usr_id"], "Great food", 5)

    response = client.get("/restaurants")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Happy Path Bistro" in page
    assert "Great food" in page
    assert '"total_rating": 5' in page or '"total_rating":5' in page
    assert '"count": 1' in page or '"count":1' in page


# This proves an authenticated GET /restaurants renders 200 with the restaurant and a correct server-side {total_rating, count} aggregate built from its reviews.


def test_a_restaurant_with_zero_reviews_never_divides_on_the_server_it_only_ships_a_zero_count(
    client, seed_minimal_data, login_session, temp_db_path
):
    _insert_restaurant(temp_db_path, "Zero Reviews Diner")  # no reviews inserted for it

    response = client.get("/restaurants")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Zero Reviews Diner" in page
    assert '"total_rating": 0' in page or '"total_rating":0' in page
    assert '"count": 0' in page or '"count":0' in page


# This proves the zero-review case is real but does not crash the server: restaurants() never computes an average itself (no total_rating/count division appears in Flask_app.py), it just hands raw count=0 data to the template, whose client-side JS is the only thing guarding the divide.


def test_a_review_from_a_deleted_users_id_silently_vanishes_from_the_rating_aggregate(
    client, seed_minimal_data, login_session, temp_db_path
):
    rtr_id = _insert_restaurant(temp_db_path, "Orphan Review Grill")
    surviving_user = seed_minimal_data["usr_id"]
    deleted_user_id = surviving_user + 9999  # no matching row in "User"

    _insert_review(temp_db_path, rtr_id, surviving_user, "From a real user", 4)
    _insert_review(temp_db_path, rtr_id, deleted_user_id, "From a deleted user", 1)

    response = client.get("/restaurants")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "From a real user" in page
    assert "From a deleted user" not in page
    # Only the surviving review is counted -- the inner join dropped the other one.
    assert '"total_rating": 4' in page or '"total_rating":4' in page
    assert '"count": 1' in page or '"count":1' in page


# This proves the plain JOIN "User" on the Review query is an inner join: a review whose usr_id has no matching User row is dropped entirely, silently shrinking that restaurant's review count and rating total instead of surfacing as e.g. an "Unknown user" entry.
