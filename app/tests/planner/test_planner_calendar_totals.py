"""The calendar shows each day's calories and delivered cost, and the month's total."""

from datetime import date

from werkzeug.security import generate_password_hash

import Flask_app
from planner.menu import meal_cost_cents
from sqlQueries import close_connection, create_connection, execute_query, fetch_one


def test_cells_total_calories_and_delivered_cost_per_day():
    items = {
        5: {"itm_id": 5, "name": "Oats", "price": 500, "calories": 400},
        6: {"itm_id": 6, "name": "Curry", "price": 1200, "calories": 900},
    }
    gen_map = {"2026-10-19": [{"itm_id": 5, "meal": 1}, {"itm_id": 6, "meal": 3}]}

    cells = Flask_app.build_calendar_cells(gen_map, 2026, 10, items)

    day = next(c for c in cells if c["day"] == 19)
    assert day["kcal"] == 1300
    assert day["cost_cents"] == meal_cost_cents(500) + meal_cost_cents(1200)
    empty = next(c for c in cells if c["day"] == 20)
    assert empty["kcal"] == 0 and empty["cost_cents"] == 0


def test_the_calendar_page_shows_day_totals_and_the_month_total(client, temp_db_path):
    today = date.today()
    conn = create_connection(temp_db_path)
    try:
        execute_query(
            conn,
            "INSERT INTO Restaurant(name, status, hours) VALUES ('Totals Cafe', 'Open', '{}')",
        )
        rtr_id = fetch_one(conn, "SELECT rtr_id FROM Restaurant WHERE name = 'Totals Cafe'")[0]
        execute_query(
            conn,
            """INSERT INTO MenuItem(rtr_id, name, price, calories, instock)
               VALUES (?, 'Totals Bowl', 1000, 650, 1)""",
            (rtr_id,),
        )
        itm_id = fetch_one(conn, "SELECT itm_id FROM MenuItem WHERE name = 'Totals Bowl'")[0]
        email = "calendar-totals@example.test"
        execute_query(
            conn,
            """INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,
                                  generated_menu)
               VALUES ('Cal','Totals',?,'9195550777',?,0,?)""",
            (
                email,
                generate_password_hash("secret123"),
                f"[{today.isoformat()},{itm_id},1],[{today.isoformat()},{itm_id},2]",
            ),
        )
    finally:
        close_connection(conn)
    client.post("/login", data={"email": email, "password": "secret123"})

    page = client.get("/").get_data(as_text=True)

    day_cost = 2 * meal_cost_cents(1000)
    assert f"1,300 kcal · ${day_cost / 100:.2f}" in page
    assert f"Planned this month: <strong>${day_cost / 100:,.2f}</strong>" in page
    assert "1,300 kcal/day on average" in page
