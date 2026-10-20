"""M4 in the web app: fee settings, planning with batching, the calendar, and batch orders."""
import json
import sqlite3
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import Flask_app
import ledger
from fee_prefs import FeePrefs, ensure_fee_prefs_schema, load_fee_prefs, save_fee_prefs
from planner.fees import DEFAULT_FEES, FeeSchedule, RestaurantFees
from planner.menu import WEEKDAYS, Menu, MenuItem, Restaurant
from sqlQueries import close_connection, create_connection, execute_query, fetch_one
from wallet_helpers import set_wallet_cents, wallet_cents

PASSWORD = "secret123"
OPEN_ALL_DAY = {d: (600, 2300) for d in WEEKDAYS}


def _user(db, email, phone, kcal=1800, budget=60000):
    conn = create_connection(db)
    try:
        execute_query(conn, '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,
                                   allergies,generated_menu,daily_calorie_target,weekly_budget_cents)
                               VALUES ("M4","Web",?,?,?,0,"","","",?,?)''',
                      (email, phone, generate_password_hash(PASSWORD), kcal, budget))
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _login(c, email):
    assert c.post("/login", data={"email": email, "password": PASSWORD}).status_code == 302


def _restaurant(db, name, delivery_fee=None, items=((1000, 600),)):
    conn = create_connection(db)
    try:
        execute_query(conn, '''INSERT INTO "Restaurant"(name,address,city,state,zip,status,hours)
                               VALUES (?, "1 Way", "Raleigh", "NC", "27606", "Open", ?)''',
                      (name, json.dumps({d: [600, 2300] for d in WEEKDAYS})))
        rtr_id = fetch_one(conn, 'SELECT rtr_id FROM "Restaurant" WHERE name = ?', (name,))[0]
        ids = []
        for n, (price, kcal) in enumerate(items):
            execute_query(conn, '''INSERT INTO "MenuItem"(rtr_id,name,description,price,calories,instock,allergens)
                                   VALUES (?, ?, "x", ?, ?, 1, "")''', (rtr_id, f"{name} dish {n}", price, kcal))
            ids.append(fetch_one(conn, 'SELECT max(itm_id) FROM "MenuItem"')[0])
        if delivery_fee is not None:
            execute_query(conn, 'INSERT INTO "RestaurantFee" VALUES (?, ?, NULL)', (rtr_id, delivery_fee))
        return rtr_id, ids
    finally:
        close_connection(conn)


# --- fee_prefs ----------------------------------------------------------------

def test_fee_prefs_default_to_batching_off_and_no_pickup(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p.db"))
    assert load_fee_prefs(conn, 1) == FeePrefs()                       # no table at all
    ensure_fee_prefs_schema(conn)
    assert load_fee_prefs(conn, 1) == FeePrefs()                       # no row
    assert FeePrefs().plan_options() == {"fee_cost": {"batching": False, "pickup_restaurants": [], "pickup_days": []}}


def test_fee_prefs_round_trip_and_normalize(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p.db"))
    save_fee_prefs(conn, 7, FeePrefs(True, (5, 3, 5), ("Sun", "Mon")))
    assert load_fee_prefs(conn, 7) == FeePrefs(True, (3, 5), ("Mon", "Sun"))
    save_fee_prefs(conn, 7, FeePrefs())                                # overwrite
    assert load_fee_prefs(conn, 7) == FeePrefs()


@pytest.mark.parametrize("kwargs", [{"pickup_days": ("Funday",)}, {"pickup_restaurants": (0,)},
                                    {"batching": "yes"}])
def test_invalid_fee_prefs_are_refused(kwargs):
    with pytest.raises(ValueError):
        FeePrefs(**kwargs)


def test_unreadable_stored_prefs_fall_back_to_the_defaults(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p.db"))
    ensure_fee_prefs_schema(conn)
    conn.execute('INSERT INTO "UserFeePrefs" VALUES (1, 1, \'not json\', \'["Mon"]\')')
    assert load_fee_prefs(conn, 1) == FeePrefs()


# --- Settings page ------------------------------------------------------------

def test_the_settings_page_needs_login(app):
    with app.test_client() as anonymous:
        assert anonymous.get("/profile/fees").status_code == 302


def test_saving_settings(client, temp_db_path):
    usr = _user(temp_db_path, "m4-settings@example.test", "9195551101")
    rtr_id, _ = _restaurant(temp_db_path, "M4 Settings Cafe", delivery_fee=249)
    _login(client, "m4-settings@example.test")

    page = client.get("/profile/fees").get_data(as_text=True)
    assert "M4 Settings Cafe" in page and "delivery $2.49" in page and "synthetic" in page

    resp = client.post("/profile/fees", data={"batching": "on", "pickup_days": ["Sat", "Sun"],
                                              "pickup_restaurants": [str(rtr_id)]})
    assert resp.status_code == 302 and "saved=1" in resp.headers["Location"]
    conn = create_connection(temp_db_path)
    try:
        assert load_fee_prefs(conn, usr) == FeePrefs(True, (rtr_id,), ("Sat", "Sun"))
    finally:
        close_connection(conn)
    again = client.get("/profile/fees?saved=1").get_data(as_text=True)
    assert 'id="feeSaved"' in again and 'name="batching" id="batching" checked' in again


@pytest.mark.parametrize("form", [{"pickup_days": ["Funday"]}, {"pickup_restaurants": ["987654"]},
                                  {"pickup_restaurants": ["abc"]}])
def test_invalid_settings_are_rejected_and_not_saved(client, temp_db_path, form):
    usr = _user(temp_db_path, f"m4-bad-{abs(hash(str(form)))}@example.test", f"91955{abs(hash(str(form))) % 10**5:05d}")
    _login(client, f"m4-bad-{abs(hash(str(form)))}@example.test")

    resp = client.post("/profile/fees", data=form)

    assert resp.status_code == 400
    conn = create_connection(temp_db_path)
    try:
        assert load_fee_prefs(conn, usr) == FeePrefs()
    finally:
        close_connection(conn)


@pytest.mark.parametrize("half", ["days", "restaurants"])
def test_pickup_needs_both_days_and_restaurants(client, temp_db_path, half):
    usr = _user(temp_db_path, f"m4-half-{half}@example.test", f"91955512{len(half):02d}")
    rtr_id, _ = _restaurant(temp_db_path, f"M4 Half {half}", delivery_fee=299)
    _login(client, f"m4-half-{half}@example.test")
    form = {"batching": "on"}
    if half == "days":
        form["pickup_days"] = ["Sat"]
    else:
        form["pickup_restaurants"] = [str(rtr_id)]

    resp = client.post("/profile/fees", data=form)

    assert resp.status_code == 400
    assert "Pickup needs at least one day and at least one restaurant" in resp.get_data(as_text=True)
    conn = create_connection(temp_db_path)
    try:
        assert load_fee_prefs(conn, usr) == FeePrefs()
    finally:
        close_connection(conn)


def test_the_profile_links_to_the_settings(client, temp_db_path):
    _user(temp_db_path, "m4-link@example.test", "9195551102")
    _login(client, "m4-link@example.test")
    assert 'href="/profile/fees"' in client.get("/profile").get_data(as_text=True)


# --- /generate_plan and the calendar ------------------------------------------

def _one_restaurant_menu(rtr_id, item_ids):
    items = {i: MenuItem(i, rtr_id, f"Dish {n}", "", 900 + 40 * n, 600, (), True)
             for n, i in enumerate(item_ids)}
    return Menu(items=items, restaurants={rtr_id: Restaurant(rtr_id, "M4 Plan Cafe", True, OPEN_ALL_DAY)},
                fees=DEFAULT_FEES)


@pytest.fixture()
def planned(client, temp_db_path, monkeypatch):
    """Plan a week with batching on, against a small fixed menu from one restaurant."""
    usr = _user(temp_db_path, "m4-plan@example.test", "9195551103")
    rtr_id, ids = _restaurant(temp_db_path, "M4 Plan Cafe", items=[(900 + 40 * n, 600) for n in range(8)])
    monkeypatch.setattr(Flask_app, "load_menu", lambda db: _one_restaurant_menu(rtr_id, ids))
    monkeypatch.delenv("PLANNER", raising=False)
    _login(client, "m4-plan@example.test")
    client.post("/profile/fees", data={"batching": "on"})
    resp = client.post("/generate_plan")
    assert resp.status_code == 200, resp.get_json()
    return usr, rtr_id, resp.get_json()


def test_planning_with_batching_reports_fees_and_savings(planned):
    _, _, body = planned
    assert body["orders"] == 14 and body["batched_orders"] == 7
    assert body["fees_cents"] == 14 * DEFAULT_FEES.order_fee_cents()
    assert body["fee_savings_cents"] == 7 * DEFAULT_FEES.order_fee_cents()


def test_the_saved_plan_tags_batched_meals_and_the_calendar_groups_them(client, temp_db_path, planned):
    usr, _, body = planned
    conn = create_connection(temp_db_path)
    try:
        saved = fetch_one(conn, 'SELECT generated_menu FROM "User" WHERE usr_id = ?', (usr,))[0]
    finally:
        close_connection(conn)
    parsed = Flask_app.parse_generated_menu(saved)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tags = [e.get("order") for e in parsed[tomorrow]]
    assert sum(t is not None for t in tags) == 2 and len(set(t for t in tags if t)) == 1

    when = date.today() + timedelta(days=1)
    page = client.get(f"/{when.year}/{when.month}").get_data(as_text=True)
    assert "🔗 One delivery" in page and "Order together" in page
    assert 'id="feeSummary"' in page and "vs ordering separately" in page


def test_planning_with_the_default_settings_saves_no_tags(client, temp_db_path, monkeypatch):
    usr = _user(temp_db_path, "m4-plain@example.test", "9195551104")
    rtr_id, ids = _restaurant(temp_db_path, "M4 Plain Cafe", items=[(900 + 40 * n, 600) for n in range(8)])
    monkeypatch.setattr(Flask_app, "load_menu", lambda db: _one_restaurant_menu(rtr_id, ids))
    monkeypatch.delenv("PLANNER", raising=False)
    _login(client, "m4-plain@example.test")

    body = client.post("/generate_plan").get_json()

    assert body["orders"] == 21 and body["batched_orders"] == 0 and body["fee_savings_cents"] == 0
    conn = create_connection(temp_db_path)
    try:
        saved = fetch_one(conn, 'SELECT generated_menu FROM "User" WHERE usr_id = ?', (usr,))[0]
    finally:
        close_connection(conn)
    assert ",o" not in saved and ",p" not in saved


def test_parse_generated_menu_reads_order_tags_and_old_entries():
    parsed = Flask_app.parse_generated_menu("[2026-10-20,5,2,o3],[2026-10-20,6,3,o3],[2026-10-20,7,1],[2026-10-21,8,2,p9],[2026-10-22,9]")
    assert parsed["2026-10-20"] == [{"itm_id": 5, "meal": 2, "order": "o3"}, {"itm_id": 6, "meal": 3, "order": "o3"},
                                    {"itm_id": 7, "meal": 1}]
    assert parsed["2026-10-21"] == [{"itm_id": 8, "meal": 2, "order": "p9"}]
    assert parsed["2026-10-22"] == [{"itm_id": 9, "meal": 3}]


def _cal_meal(meal, itm_id, rtr_id, price, tag=None):
    return {"meal": meal, "item": {"itm_id": itm_id, "rtr_id": rtr_id, "price": price, "restaurant_name": f"R{rtr_id}"},
            "order_tag": tag}


def test_calendar_orders_price_fees_once_per_batch_and_skip_delivery_on_pickup():
    fees = FeeSchedule(overrides={1: RestaurantFees(199, 149)})
    meals = [_cal_meal(1, 10, 1, 1000), _cal_meal(2, 11, 1, 1000, "o1"), _cal_meal(3, 12, 1, 1000, "o1")]
    orders = Flask_app.calendar_day_orders(meals, fees)
    assert [len(o["meals"]) for o in orders] == [1, 2]
    assert sum(o["fee_cents"] for o in orders) == 2 * 348
    assert sum(o["separate_fee_cents"] - o["fee_cents"] for o in orders) == 348

    pickup = Flask_app.calendar_day_orders([_cal_meal(2, 11, 1, 1000, "p2")], fees)
    assert pickup[0]["pickup"] and pickup[0]["fee_cents"] == 149


def test_a_tag_across_restaurants_is_priced_as_separate_orders():
    meals = [_cal_meal(2, 11, 1, 1000, "o1"), _cal_meal(3, 12, 2, 1000, "o1")]
    orders = Flask_app.calendar_day_orders(meals)
    assert [len(o["meals"]) for o in orders] == [1, 1]
    assert sum(o["fee_cents"] for o in orders) == 2 * DEFAULT_FEES.order_fee_cents()


# --- Ordering a batch: one order, one wallet debit ----------------------------

def test_ordering_a_batch_places_one_order_with_one_debit(client, temp_db_path):
    usr = _user(temp_db_path, "m4-batch@example.test", "9195551105")
    rtr_id, (a, b) = _restaurant(temp_db_path, "M4 Batch Cafe", delivery_fee=249,
                                 items=[(1000, 600), (1200, 700)])
    set_wallet_cents(temp_db_path, usr, 10_000)
    _login(client, "m4-batch@example.test")

    resp = client.post("/order", json={
        "restaurant_id": rtr_id, "items": [{"itm_id": a}, {"itm_id": b}], "meals": [3, 2],
        "delivery_type": "delivery", "date": (date.today() + timedelta(days=1)).isoformat(),
        "idempotency_key": "m4-batch-order-key-1",
    })

    assert resp.status_code == 200, resp.get_json()
    conn = create_connection(temp_db_path)
    try:
        rows = conn.execute('SELECT details FROM "Order" WHERE usr_id = ?', (usr,)).fetchall()
        details = json.loads(rows[0][0])
        debits = [h for h in ledger.history(conn, ledger.user_account(usr)) if h["kind"] == "order"]
    finally:
        close_connection(conn)
    charges = details["charges_cents"]
    assert len(rows) == 1 and details["meals"] == [2, 3] and details["meal"] == 2
    assert (charges["delivery_fee"], charges["service_fee"]) == (249, 149)     # once, not twice
    assert charges["total"] == 2200 + 160 + 249 + 149
    assert len(debits) == 1 and -debits[0]["amount_cents"] == charges["total"]
    assert wallet_cents(temp_db_path, usr) == 10_000 - charges["total"]


@pytest.mark.parametrize("meals", [[], [4], [2, 2], ["2"], 2])
def test_a_batch_order_with_invalid_meals_is_refused(client, temp_db_path, meals):
    email = f"m4-badmeals-{abs(hash(str(meals)))}@example.test"
    usr = _user(temp_db_path, email, f"9196{abs(hash(str(meals))) % 10**6:06d}")
    rtr_id, (a,) = _restaurant(temp_db_path, f"M4 Bad Meals Cafe {abs(hash(str(meals)))}")
    set_wallet_cents(temp_db_path, usr, 10_000)
    _login(client, email)

    resp = client.post("/order", json={"restaurant_id": rtr_id, "items": [{"itm_id": a}], "meals": meals})

    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_meals"
    assert wallet_cents(temp_db_path, usr) == 10_000
