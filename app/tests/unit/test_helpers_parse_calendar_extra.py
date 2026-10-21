# tests/unit/test_helpers_parse_calendar_extra.py
import calendar as _calendar
from datetime import date as _date

import Flask_app as Flask_app


def test_parse_generated_menu_empty():
    assert Flask_app.parse_generated_menu("") == {}


def test_parse_generated_menu_ignores_bad_tokens():
    s = "not_a_pair [2025-10-27, 5, 2] [2025-99-99,abc] [2025-10-28, 6 , 3] junk"
    m = Flask_app.parse_generated_menu(s)
    assert "2025-10-27" in m and "2025-10-28" in m
    assert all(isinstance(e["itm_id"], int) for e in m["2025-10-27"])


def test_parse_generated_menu_spaces_and_legacy():
    s = "[ 2025-10-27 , 5 ] [2025-10-27,6,1]"
    m = Flask_app.parse_generated_menu(s)
    assert len(m["2025-10-27"]) == 2
    meals = sorted(e["meal"] for e in m["2025-10-27"])
    assert meals == [1, 3]


def test_palette_for_item_ids_empty():
    assert Flask_app.palette_for_item_ids([]) == {}


def test_palette_deterministic_for_same_ids():
    p1 = Flask_app.palette_for_item_ids([1, 2, 3])
    p2 = Flask_app.palette_for_item_ids([1, 2, 3])
    assert p1 == p2
    assert all(
        isinstance(c, str) and len(c) == 7 and c.startswith("#")
        for c in p1.values()
    )


def test_build_calendar_cells_empty_month_structure():
    today = _date.today()
    cells = Flask_app.build_calendar_cells({}, today.year, today.month, {})
    weeks = _calendar.Calendar(firstweekday=6).monthdayscalendar(
        today.year, today.month
    )
    assert len(cells) == len(weeks) * 7
    zero_days = [c for c in cells if c.get("day") == 0]
    assert len(zero_days) == sum(1 for w in weeks for d in w if d == 0)


def test_build_calendar_cells_meal_sort_order():
    items_by_id = {
        1: {"itm_id": 1, "name": "Breakfast"},
        2: {"itm_id": 2, "name": "Dinner"},
    }
    gen_map = {
        "2025-10-27": [
            {"itm_id": 2, "meal": 3},
            {"itm_id": 1, "meal": 1},
        ]
    }
    cells = Flask_app.build_calendar_cells(gen_map, 2025, 10, items_by_id)
    target = next(c for c in cells if c.get("day") == 27)
    meals = [m["meal"] for m in target["meals"]]
    assert meals == [1, 3]


def test_money_and_cents_helpers_extra_cases():
    # Extra cases on top of tests/unit/test_helpers_parse_calendar.py
    assert Flask_app._cents_to_dollars(12568) == 125.68
    assert Flask_app._cents_to_dollars(None) == 0.0
    assert Flask_app._money("bad") == 0.0


def test_fetch_menu_items_by_ids_empty_returns_empty():
    # Guard that an empty list input returns an empty dict
    assert Flask_app.fetch_menu_items_by_ids([]) == {}
