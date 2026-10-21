from sqlQueries import create_connection, execute_query, fetch_one

# def test_submit_review_success(client, temp_db_path, seed_minimal_data, login_session):
#     """Test posting a valid review for a delivered order."""
#     # Create a 'Delivered' order
#     conn = create_connection(temp_db_path)
#     execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Delivered")', 
#                  (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"]))
#     ord_id = fetch_one(conn, "SELECT last_insert_rowid()")[0]
#     conn.close()

#     resp = client.post("/review/submit", json={
#         "restaurant_id": seed_minimal_data["rtr_id"],
#         "order_id": ord_id,
#         "rating": 5,
#         "title": "Great",
#         "comment": "Yum"
#     })
#     assert resp.status_code == 201
#     assert resp.json["ok"] is True

def test_submit_review_not_delivered_fails(client, temp_db_path, seed_minimal_data, login_session):
    """Test review fails if order is not yet delivered."""
    conn = create_connection(temp_db_path)
    execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Preparing")', 
                 (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"]))
    ord_id = fetch_one(conn, "SELECT last_insert_rowid()")[0]
    conn.close()

    resp = client.post("/review/submit", json={
        "restaurant_id": seed_minimal_data["rtr_id"],
        "order_id": ord_id,
        "rating": 5
    })
    assert resp.status_code == 403

# def test_submit_duplicate_review_fails(client, temp_db_path, seed_minimal_data, login_session):
#     """Test user cannot review the same restaurant twice."""
#     conn = create_connection(temp_db_path)
#     # Pre-insert a review
#     execute_query(conn, 'INSERT INTO "Review" (rtr_id, usr_id, rating) VALUES (?, ?, 5)',
#                   (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"]))
    
#     # Create valid order
#     execute_query(conn, 'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, "{}", "Delivered")', 
#                  (seed_minimal_data["rtr_id"], seed_minimal_data["usr_id"]))
#     ord_id = fetch_one(conn, "SELECT last_insert_rowid()")[0]
#     conn.close()

#     resp = client.post("/review/submit", json={
#         "restaurant_id": seed_minimal_data["rtr_id"],
#         "order_id": ord_id,
#         "rating": 5
#     })
#     assert resp.status_code == 409
#     assert "already reviewed" in resp.json["error"]

def test_submit_review_invalid_rating(client, seed_minimal_data, login_session):
    """Test rating bounds (1-5)."""
    resp = client.post("/review/submit", json={
        "restaurant_id": seed_minimal_data["rtr_id"],
        "order_id": 1,
        "rating": 6 # Invalid
    })
    assert resp.status_code == 400

def test_submit_review_unauthorized(client):
    """Test anonymous review submission."""
    resp = client.post("/review/submit", json={})
    assert resp.status_code == 401