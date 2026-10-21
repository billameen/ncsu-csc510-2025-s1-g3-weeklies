import pytest
import json
from datetime import datetime, timedelta
# Assuming the root path is set correctly by conftest.py
from app.sqlQueries import create_connection, close_connection, fetch_one, execute_query


@pytest.fixture
def seed_rating_order(temp_db_path, seed_minimal_data):
    """
    Creates minimal data, including two distinct restaurants.
    
    Returns a dict with:
    - reviewable_ord_id_1: An order for rtr_id 1 in 'Delivered' status.
    - rtr_id_2: A second, unrated restaurant ID.
    """
    conn = create_connection(temp_db_path)
    usr_id = seed_minimal_data['usr_id']
    rtr_id_1 = seed_minimal_data['rtr_id']

    order_details = json.dumps({
        "placed_at": datetime.now().isoformat(),
        "restaurant_id": rtr_id_1,
        "items": [{"itm_id": 1, "name": "Pasta", "qty": 1, "unit_price": 12.99, "line_total": 12.99}],
        "charges": {"total": 15.00}
    })
    
    # Order 1: Ready for rating
    execute_query(conn, '''
        INSERT INTO "Order" (rtr_id, usr_id, details, status)
        VALUES (?, ?, ?, 'Delivered')
    ''', (rtr_id_1, usr_id, order_details))
    ord_id_1 = fetch_one(conn, 'SELECT last_insert_rowid()')[0]
    
    # Restaurant 2: Create a second restaurant for multi-rating tests
    execute_query(conn, '''
      INSERT INTO "Restaurant"(name,address,city,state,zip,status)
      VALUES ("Cafe Two","456 Oak","Raleigh","NC","27607","open")
    ''')
    rtr_id_2 = fetch_one(conn, "SELECT rtr_id FROM Restaurant WHERE name = 'Cafe Two'")[0]

    # Order 2: Order for the second restaurant
    order_details_2 = json.dumps({
        "placed_at": datetime.now().isoformat(),
        "restaurant_id": rtr_id_2,
        "items": [{"itm_id": 3, "name": "Taco", "qty": 2, "unit_price": 4.99, "line_total": 9.98}],
        "charges": {"total": 12.00}
    })
    execute_query(conn, '''
        INSERT INTO "Order" (rtr_id, usr_id, details, status)
        VALUES (?, ?, ?, 'Delivered')
    ''', (rtr_id_2, usr_id, order_details_2))
    ord_id_2 = fetch_one(conn, 'SELECT last_insert_rowid()')[0]

    close_connection(conn)
    
    return {
        "usr_id": usr_id,
        "rtr_id_1": rtr_id_1,
        "rtr_id_2": rtr_id_2,
        "ord_id_1": ord_id_1,
        "ord_id_2": ord_id_2,
    }


# ----------------------------------------------------------------------
# Additional Test Cases for Rating Submission Logic
# ----------------------------------------------------------------------

class TestRatingSubmission:
    
    URL = "/review/submit"
    

    def test_submit_rating_missing_order_id(self, client, login_session, seed_rating_order):
        """Should fail with 400 if the required order_id field is missing in the payload."""
        data = seed_rating_order

        # Test 1: order_id is missing entirely
        resp_missing = client.post(self.URL, json={
            "restaurant_id": data['rtr_id_1'], "rating": 5, "title": "T", "comment": "C"
        })
        # Missing/non-numeric fields are validated before any DB work and reported as a client error.
        assert resp_missing.status_code == 400
        assert resp_missing.get_json()["error"] == "Invalid rating or restaurant ID"

    def test_submit_rating_invalid_order_id_nonexistent(self, client, login_session, seed_rating_order):
        """Should fail if the order_id is a valid integer but does not exist in the DB (403)."""
        data = seed_rating_order
        non_existent_id = data['ord_id_1'] + 1000 # Assume this is a non-existent ID
        
        resp_non_existent = client.post(self.URL, json={
            "restaurant_id": data['rtr_id_1'], "rating": 5, "title": "T", "comment": "C", "order_id": non_existent_id
        })
        
        # If order not found, `order_row` is None, failing the eligibility check.
        assert resp_non_existent.status_code == 403
        assert resp_non_existent.get_json()["error"] == "Order not delivered or unauthorized"
        
    def test_submit_rating_multi_restaurant_flow(self, client, login_session, temp_db_path, seed_rating_order):
        """
        Verifies that rating one restaurant does NOT prevent a user from rating a 
        different, unrated restaurant.
        """
        data = seed_rating_order
        
        # 1. Submit rating for Restaurant 1 (rtr_id_1)
        resp_1 = client.post(self.URL, json={
            "restaurant_id": data['rtr_id_1'], "rating": 5, "title": "R1 Rating", "comment": "C", "order_id": data['ord_id_1']
        })
        assert resp_1.status_code == 201
        
        # 2. Submit rating for Restaurant 2 (rtr_id_2) - Should succeed
        resp_2 = client.post(self.URL, json={
            "restaurant_id": data['rtr_id_2'], "rating": 4, "title": "R2 Rating", "comment": "C", "order_id": data['ord_id_2']
        })
        assert resp_2.status_code == 201
        
        # 3. Verify two distinct ratings exist in the DB
        conn = create_connection(temp_db_path)
        try:
            r1_rating = fetch_one(conn, 'SELECT rating FROM "Review" WHERE rtr_id = ? AND usr_id = ?', (data['rtr_id_1'], data['usr_id']))
            r2_rating = fetch_one(conn, 'SELECT rating FROM "Review" WHERE rtr_id = ? AND usr_id = ?', (data['rtr_id_2'], data['usr_id']))
        finally:
            close_connection(conn)
            
        assert r1_rating[0] == 5
        assert r2_rating[0] == 4


# ----------------------------------------------------------------------
# Additional Test Cases for Rating Aggregation Logic
# ----------------------------------------------------------------------

class TestRatingAggregation:
    
    URL = "/restaurants"

    def test_restaurants_no_rating_aggregation(self, client, login_session, seed_rating_order):
        """
        Verifies a restaurant with no ratings renders correctly without errors 
        (implicitly should have an average of 0 and count of 0).
        """
        # Note: Cafe Two exists but has no ratings in the DB currently
        resp = client.get(self.URL)
        assert resp.status_code == 200
        
        content = resp.data.decode('utf-8')
        
        # Verify the existence of the unrated restaurant
        assert "Cafe Two" in content
        
        # We cannot assert a 0 average directly from HTML, but successful rendering 
        # and non-error status confirms the logic handles the zero-rating case gracefully.