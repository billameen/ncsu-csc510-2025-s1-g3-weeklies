"""POST /generate_plan with PLANNER=solver (the default) and PLANNER=llm (v1)."""

import json
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import Flask_app
from Flask_app import replace_menu_days
from planner.solver import PlannerError
from sqlQueries import close_connection, create_connection, execute_query, fetch_one

PASSWORD = "secret123"
OPEN_ALL_DAY = json.dumps(
    {d: [600, 2300] for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}
)


@pytest.fixture()
def solver_menu(temp_db_path):
    """A restaurant open all day with enough items for a varied week (idempotent)."""
    conn = create_connection(temp_db_path)
    try:
        if not fetch_one(conn, "SELECT 1 FROM Restaurant WHERE name = 'Solver Diner'"):
            execute_query(
                conn,
                "INSERT INTO Restaurant(name, status, hours) VALUES ('Solver Diner', 'Open', ?)",
                (OPEN_ALL_DAY,),
            )
            rtr_id = fetch_one(conn, "SELECT rtr_id FROM Restaurant WHERE name = 'Solver Diner'")[0]
            for n in range(20):
                execute_query(
                    conn,
                    """INSERT INTO MenuItem(rtr_id, name, description, price, calories, instock,
                                            allergens)
                       VALUES (?, ?, 'test dish', ?, ?, 1, ?)""",
                    (rtr_id, f"Dish {n}", 800 + 25 * n, 500 + 10 * n, "Eggs" if n % 5 == 0 else ""),
                )
    finally:
        close_connection(conn)


@pytest.fixture()
def user(client, temp_db_path, request):
    """A logged-in user with targets; returns (usr_id, email)."""
    email = f"plan-{request.node.name}"[:60] + "@example.test"
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            """INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,
                                  allergies,generated_menu,daily_calorie_target,weekly_budget_cents)
               VALUES ('Plan','Route',?,?,?,0,'',?,?,1800,60000)""",
            (email, email, generate_password_hash(PASSWORD), "Egg", "[2000-01-01,1,1]"),
        )
        usr_id = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)
    assert client.post("/login", data={"email": email, "password": PASSWORD}).status_code == 302
    return usr_id


def _set(temp_db_path, usr_id, **cols):
    conn = create_connection(temp_db_path)
    try:
        for col, value in cols.items():
            execute_query(conn, f'UPDATE "User" SET {col} = ? WHERE usr_id = ?', (value, usr_id))
    finally:
        close_connection(conn)


def _menu(temp_db_path, usr_id):
    conn = create_connection(temp_db_path)
    try:
        return fetch_one(conn, 'SELECT generated_menu FROM "User" WHERE usr_id = ?', (usr_id,))[0]
    finally:
        close_connection(conn)


def test_solver_plans_the_next_seven_days_within_the_targets(
    client, temp_db_path, solver_menu, user, monkeypatch
):
    monkeypatch.delenv("PLANNER", raising=False)  # solver is the default

    resp = client.post("/generate_plan")

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] and body["planner"] == "solver"
    assert body["total_cost_cents"] <= 60000
    tomorrow = date.today() + timedelta(days=1)
    assert list(body["kcal_per_day"]) == [
        (tomorrow + timedelta(days=i)).isoformat() for i in range(7)
    ]
    assert all(1620 <= kcal <= 1980 for kcal in body["kcal_per_day"].values())

    saved = Flask_app.parse_generated_menu(_menu(temp_db_path, user))
    assert "2000-01-01" in saved  # days outside the plan are kept
    assert sum(len(v) for d, v in saved.items() if d != "2000-01-01") == 21


def test_solver_never_plans_an_allergen_even_spelled_differently(
    client, temp_db_path, solver_menu, user
):
    client.post("/generate_plan")
    saved = Flask_app.parse_generated_menu(_menu(temp_db_path, user))
    ids = [e["itm_id"] for d, entries in saved.items() if d != "2000-01-01" for e in entries]
    items = Flask_app.fetch_menu_items_by_ids(ids)
    assert ids and not any("egg" in (items[i]["allergens"] or "").lower() for i in ids)


def test_planning_again_replaces_the_week_instead_of_adding_to_it(
    client, temp_db_path, solver_menu, user
):
    client.post("/generate_plan")
    client.post("/generate_plan")
    saved = Flask_app.parse_generated_menu(_menu(temp_db_path, user))
    assert sum(len(v) for d, v in saved.items() if d != "2000-01-01") == 21


def test_an_impossible_budget_gets_a_specific_explanation_not_a_500(
    client, temp_db_path, solver_menu, user
):
    _set(temp_db_path, user, weekly_budget_cents=100)

    resp = client.post("/generate_plan")

    assert resp.status_code == 422
    body = resp.get_json()
    assert body["ok"] is False and body["status"] == "infeasible"
    assert "your weekly budget is $1.00" in body["error"]
    assert body["reasons"] == [body["error"]]
    assert _menu(temp_db_path, user) == "[2000-01-01,1,1]"  # nothing saved


def test_missing_targets_send_the_user_to_their_profile(client, temp_db_path, solver_menu, user):
    _set(temp_db_path, user, daily_calorie_target=None, weekly_budget_cents=None)

    resp = client.post("/generate_plan")

    assert resp.status_code == 400
    body = resp.get_json()
    assert "Set your daily calorie target and weekly budget" in body["error"]
    assert body["fix_url"] == "/profile/edit"


def test_planner_llm_keeps_the_v1_generator(client, solver_menu, user, monkeypatch):
    calls = []

    class FakeV1:
        def __init__(self, tokens=500):
            pass

        def update_menu(self, menu, preferences, allergens, date, meal_numbers, number_of_days):
            calls.append(number_of_days)
            return menu

    monkeypatch.setenv("PLANNER", "llm")
    monkeypatch.setattr(Flask_app, "MenuGenerator", FakeV1)

    resp = client.post("/generate_plan")

    assert resp.status_code == 200 and resp.get_json() == {"ok": True}
    assert calls == [7]


def test_an_unknown_planner_setting_is_reported(client, user, monkeypatch):
    monkeypatch.setenv("PLANNER", "magic")
    resp = client.post("/generate_plan")
    assert resp.status_code == 500
    assert "use one of solver, llm" in resp.get_json()["error"]


def test_generate_plan_requires_login(client):
    with client.session_transaction() as sess:
        sess.clear()
    assert client.post("/generate_plan").status_code == 401


def test_replace_menu_days_keeps_other_days_exactly():
    old = "[2026-10-19,5,1],[2026-10-20,6,2],[2026-10-21, 7]"
    new = replace_menu_days(old, [date(2026, 10, 20)], ["[2026-10-20,9,1]", "[2026-10-20,8,3]"])
    assert new == "[2026-10-19,5,1],[2026-10-21, 7],[2026-10-20,9,1],[2026-10-20,8,3]"
    assert replace_menu_days(None, [], ["[2026-10-20,9,1]"]) == "[2026-10-20,9,1]"


@pytest.mark.parametrize(
    "error",
    [PlannerError("invalid model"), KeyError("unknown rule"), FileNotFoundError("no db")],
)
def test_a_planner_failure_is_a_json_500_not_an_html_page(
    client, temp_db_path, solver_menu, user, monkeypatch, error
):
    """Found in review: the page calls res.json(), so an HTML 500 showed "Network error"."""

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(Flask_app, "plan_week", broken)

    resp = client.post("/generate_plan")

    assert resp.status_code == 500 and resp.is_json
    body = resp.get_json()
    assert body["ok"] is False
    assert type(error).__name__ in body["error"]
    assert _menu(temp_db_path, user) == "[2000-01-01,1,1]"  # nothing saved
