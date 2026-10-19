"""Loading the menu and pricing a meal."""

import sqlite3

import pytest

from planner.menu import Restaurant, load_menu, meal_cost_cents, parse_hours


def test_load_menu_reads_every_item_and_restaurant_including_unavailable_ones(tmp_path):
    db = tmp_path / "menu.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE Restaurant (rtr_id INTEGER, name TEXT, status TEXT, hours TEXT);
        CREATE TABLE MenuItem (itm_id INTEGER, rtr_id INTEGER, name TEXT, description TEXT,
            price INTEGER, calories INTEGER, allergens TEXT, instock INTEGER);
        INSERT INTO Restaurant VALUES (1, 'Open Cafe', 'Open', '{"Mon": [900, 2100]}');
        INSERT INTO Restaurant VALUES (2, 'Shut Diner', 'Closed', NULL);
        INSERT INTO MenuItem VALUES (5, 1, 'Omelette', 'Eggs', 899, 450, 'Egg, Dairy', 1);
        INSERT INTO MenuItem VALUES (6, 2, 'Pie', NULL, 500, 300, NULL, 0);
        """
    )
    conn.close()

    menu = load_menu(db)

    assert list(menu.items) == [5, 6]
    assert menu.items[5].allergens == ("Egg", "Dairy")
    assert menu.items[5].in_stock and not menu.items[6].in_stock
    assert menu.items[6].description == ""
    assert menu.restaurants[1].status_open and not menu.restaurants[2].status_open
    assert menu.restaurants[2].hours == {}


def test_load_menu_refuses_a_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_menu(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_meal_cost_adds_tax_rounded_half_up_and_both_fees():
    # 1000 * 7.25% = 72.5 -> 73; fees $3.99 + $1.49 = 548.
    assert meal_cost_cents(1000) == 1000 + 73 + 548
    assert meal_cost_cents(0) == 548


def test_restaurant_hours_include_both_ends_and_treat_odd_lists_as_closed():
    r = Restaurant(1, "R", True, {"Mon": (1000, 1400, 1700, 2100), "Tue": (900,)})
    assert r.is_open_at("Mon", 1000) and r.is_open_at("Mon", 2100)
    assert not r.is_open_at("Mon", 1500)
    assert not r.is_open_at("Tue", 900)  # odd number of times: unreadable
    assert not r.is_open_at("Wed", 1200)  # no entry
    assert not Restaurant(2, "R", False, {"Mon": (0, 2359)}).is_open_at("Mon", 1200)


@pytest.mark.parametrize("raw", [None, "", "not json", "[1, 2]"])
def test_unreadable_hours_mean_no_opening_times(raw):
    assert parse_hours(raw) == {}


def test_hours_with_non_integer_times_drop_that_day():
    assert parse_hours('{"Mon": [900, "late"], "Tue": [900, 1700]}') == {"Tue": (900, 1700)}
