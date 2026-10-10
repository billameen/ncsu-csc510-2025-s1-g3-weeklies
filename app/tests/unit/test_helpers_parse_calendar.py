import types
import Flask_app as Flask_app

def test_money_and_cents_helpers():
    assert Flask_app._money(1.234) == 1.23
    assert Flask_app._money(float("2.0")) == 2.00
    assert Flask_app._money(float(0)) == 0.0
    assert Flask_app._cents_to_dollars(0) == 0.0
    assert Flask_app._cents_to_dollars(199) == 1.99
    assert Flask_app._cents_to_dollars(None) == 0.0

def test_parse_generated_menu_new_and_old_formats():
    s = "[2025-11-01,10,1][2025-11-01,11,2][2025-11-02,12]"
    m = Flask_app.parse_generated_menu(s)
    assert set(m.keys()) == {"2025-11-01", "2025-11-02"}
    day1 = sorted(m["2025-11-01"], key=lambda e: e["meal"])
    assert day1[0]["meal"] == 1 and day1[0]["itm_id"] == 10
    assert day1[1]["meal"] == 2 and day1[1]["itm_id"] == 11
    # old format defaults to Dinner(3)
    assert m["2025-11-02"][0]["meal"] == 3

def test_build_calendar_cells_orders_meals_in_day():
    gen_map = {"2025-11-02": [{"itm_id": 5, "meal": 3}, {"itm_id": 6, "meal": 1}]}
    items_by_id = {5: {"itm_id": 5, "name": "Dinner"}, 6: {"itm_id": 6, "name": "Breakfast"}}
    cells = Flask_app.build_calendar_cells(gen_map, 2025, 11, items_by_id)
    # find the cell for day 2
    cell = next(c for c in cells if c.get("day") == 2)
    meals = cell["meals"]
    assert meals[0]["meal"] == 1  # Breakfast first
    assert meals[1]["meal"] == 3  # Dinner second
