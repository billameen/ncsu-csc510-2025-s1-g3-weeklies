"""M1, the solver, behind the eval's planner interface, on a small menu."""

import json
import sqlite3

import pytest

from eval.catalog import load_catalog
from eval.feasibility import is_feasible
from eval.planners import NoValidWeek, m1_solver, menu_from_catalog
from eval.profiles import Profile, generate_profiles
from eval.validate import WEEKDAYS, validate_week


@pytest.fixture
def catalog(tmp_path):
    db = tmp_path / "menu.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE Restaurant (rtr_id INTEGER, hours TEXT, status TEXT);
        CREATE TABLE MenuItem (itm_id INTEGER, rtr_id INTEGER, price INTEGER,
                               calories INTEGER, instock INTEGER, allergens TEXT);
        """
    )
    hours = json.dumps({day: [600, 2300] for day in WEEKDAYS})
    conn.execute("INSERT INTO Restaurant VALUES (1, ?, 'Open')", (hours,))
    conn.executemany(
        "INSERT INTO MenuItem VALUES (?, 1, ?, ?, 1, ?)",
        [(n, 400 + 50 * n, 300 + 30 * n, "Egg" if n % 5 == 0 else None) for n in range(1, 31)],
    )
    conn.commit()
    conn.close()
    return load_catalog(db)


def test_m1_plans_a_valid_week_for_every_feasible_user_and_explains_the_rest(catalog):
    profiles = generate_profiles(510)[:5]
    for profile in profiles:
        answer = m1_solver(profile, catalog, 510)
        if is_feasible(profile, catalog):
            assert validate_week(answer, profile, catalog) == []
        else:
            assert isinstance(answer, NoValidWeek) and answer.reason


def test_m1_avoids_allergens_spelled_differently_in_the_menu(catalog):
    profile = Profile(1, 2000, 600, ("Eggs",), hard=False)  # the menu says "Egg"
    answer = m1_solver(profile, catalog, 510)
    assert all(m.itm_id % 5 for m in answer)


def test_m1_explains_a_budget_that_is_too_low(catalog):
    answer = m1_solver(Profile(1, 2000, 50, (), hard=False), catalog, 510)
    assert isinstance(answer, NoValidWeek)
    assert "your weekly budget is $50.00" in answer.reason


def test_menu_from_catalog_keeps_prices_calories_allergens_and_hours(catalog):
    menu = menu_from_catalog(catalog)
    assert set(menu.items) == set(catalog.items)
    item, source = menu.items[5], catalog.items[5]
    assert (item.price_cents, item.calories, item.allergens) == (
        source.price_cents,
        source.calories,
        source.allergens,
    )
    assert item.in_stock and menu.restaurants[1].hours == catalog.restaurants[1].hours
