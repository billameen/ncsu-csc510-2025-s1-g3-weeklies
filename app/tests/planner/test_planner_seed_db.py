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
from planner.solver import Status, plan_week
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


def test_hitting_the_limit_returns_the_best_valid_plan_marked_not_optimal(seed_db, seed_menu):
    result = plan_week(_request(), seed_menu, work_limit=0.3)

    assert result.status is Status.FEASIBLE
    assert result.ok and not result.optimal
    assert _validate(result, 2200, 450, ("Eggs", "Soy"), seed_db) == []


def test_running_out_of_time_before_any_plan_is_reported(seed_menu):
    result = plan_week(_request(), seed_menu, time_limit_s=0.001)

    assert result.status is Status.TIMED_OUT and not result.ok
    assert "stopped after 0.001 seconds" in result.explanation


def test_a_budget_below_the_cheapest_valid_week_is_explained_with_both_amounts(seed_menu):
    result = plan_week(_request(budget_dollars=150), seed_menu)

    assert result.status is Status.INFEASIBLE
    assert result.explanation.startswith("The cheapest week that meets your other requirements")
    assert result.explanation.endswith("your weekly budget is $150.00.")


def test_out_of_stock_items_on_the_seed_db_are_never_planned(seed_menu):
    result = plan_week(_request(), seed_menu)
    assert all(m.item.in_stock for m in result.meals)


def test_weeks_can_start_on_any_day(seed_db, seed_menu):
    request = PlanRequest(
        daily_calorie_target=2200, weekly_budget_cents=45_000, start=date(2026, 10, 22)
    )
    result = plan_week(request, seed_menu)
    assert result.ok and result.meals[0].slot.weekday == "Thu"


def test_a_budget_just_below_the_cheapest_week_is_proven_quickly(seed_menu):
    """Found in review: one solver worker used to time out here instead of proving it."""
    request = PlanRequest(
        daily_calorie_target=1200,
        weekly_budget_cents=20_000,
        start=date(2026, 10, 20),
        allergens=("Sesame", "Milk"),
    )
    result = plan_week(request, seed_menu)

    assert result.status is Status.INFEASIBLE
    assert result.seconds < 2
    assert "costs $227.71 with tax and fees; your weekly budget is $200.00" in result.explanation
