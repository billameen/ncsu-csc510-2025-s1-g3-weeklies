"""
The solver on the real seed data (app/db/seed.sql), checked by the M0 validator: the week it
plans is valid, the same every time, and impossible requests are explained.
"""

from datetime import date

import pytest
from menu_factory import MONDAY

from eval.catalog import load_catalog
from eval.profiles import Profile
from eval.validate import WEEKDAYS, Meal, validate_week
from planner.menu import load_menu
from planner.request import PlanRequest
from planner.solver import plan_week
from scripts.init_db import SEED_FILE, init_db


@pytest.fixture(scope="module")
def seed_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("seed") / "seed.db"
    init_db(db_file=str(path), seed_file=SEED_FILE)
    return path


@pytest.fixture(scope="module")
def seed_menu(seed_db):
    return load_menu(seed_db)


def _validate(result, kcal, budget_dollars, allergens, db):
    meals = [Meal(WEEKDAYS[m.day.weekday()], m.meal, m.itm_id) for m in result.meals]
    profile = Profile(0, kcal, budget_dollars, tuple(allergens), hard=False)
    return validate_week(meals, profile, load_catalog(db))


def _request(kcal=2200, budget_dollars=450, allergens=("Eggs", "Soy")):
    return PlanRequest(
        daily_calorie_target=kcal,
        weekly_budget_cents=budget_dollars * 100,
        start=MONDAY,
        allergens=allergens,
    )


def test_the_planned_week_on_the_seed_db_passes_the_m0_validator(seed_db, seed_menu):
    result = plan_week(_request(), seed_menu)

    assert result.ok, result.explanation
    assert len(result.meals) == 21
    assert _validate(result, 2200, 450, ("Eggs", "Soy"), seed_db) == []
    assert result.total_cost_cents <= 45_000
    assert len({m.itm_id for m in result.meals}) >= 14  # H2's target


def test_allergen_spellings_in_the_profile_still_pass_the_validator(seed_db, seed_menu):
    # The seed data tags some items "Egg" and others "Eggs"; the profile says "egg".
    result = plan_week(_request(allergens=("egg",)), seed_menu)
    assert _validate(result, 2200, 450, ("Eggs",), seed_db) == []


def test_the_same_request_always_gets_the_same_plan(seed_menu):
    first = plan_week(_request(), seed_menu)
    second = plan_week(_request(), seed_menu)
    assert first.menu_entries() == second.menu_entries()


def test_out_of_stock_items_on_the_seed_db_are_never_planned(seed_menu):
    result = plan_week(_request(), seed_menu)
    assert all(m.item.in_stock for m in result.meals)


def test_weeks_can_start_on_any_day(seed_db, seed_menu):
    request = PlanRequest(
        daily_calorie_target=2200, weekly_budget_cents=45_000, start=date(2026, 10, 22)
    )
    result = plan_week(request, seed_menu)
    assert result.ok and result.meals[0].slot.weekday == "Thu"
