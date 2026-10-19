"""
Impossible requests under the default rules: every one gets a specific explanation, never a
generic error. (The seed-data versions, including the time limit, are in test_planner_seed_db.)
"""

import pytest
from menu_factory import OPEN_ALL_DAY, item, menu, request, restaurant

from planner.menu import meal_cost_cents
from planner.request import InvalidPlanRequest, PlanRequest
from planner.solver import Status, plan_week

LUNCH_AND_DINNER = {day: (1100, 2200) for day in OPEN_ALL_DAY}


def week(**kw):
    return request(days=7, **kw)


def assert_explained(result, *fragments):
    assert result.status is Status.INFEASIBLE and not result.ok and result.meals == ()
    for fragment in fragments:
        assert fragment in result.explanation


def test_budget_too_low():
    result = plan_week(week(kcal=1800, budget_cents=10_000), menu([item(1), item(2)]))
    cheapest = 21 * meal_cost_cents(1000)
    assert_explained(result, f"costs ${cheapest / 100:,.2f}", "your weekly budget is $100.00")


def test_all_breakfasts_blocked():
    result = plan_week(week(), menu([item(1)], [restaurant(1, hours=LUNCH_AND_DINNER)]))
    assert_explained(
        result,
        "No breakfast can be planned on any day",
        "1 come from restaurants closed at 10:00",
    )


def test_impossible_calorie_target():
    result = plan_week(week(kcal=5000), menu([item(1, calories=600), item(2, calories=900)]))
    assert_explained(result, "5,000 kcal", "4,500-5,500", "The closest is 2,700 kcal on any day")


def test_empty_menu():
    assert_explained(plan_week(week(), menu([])), "There are no menu items")


def test_everything_closed():
    result = plan_week(week(), menu([item(1)], [restaurant(1, status_open=False)]))
    assert_explained(
        result, "No breakfast, lunch or dinner can be planned on any day", "not taking orders"
    )


def test_everything_out_of_stock():
    result = plan_week(week(), menu([item(1, in_stock=False), item(2, in_stock=False)]))
    assert_explained(result, "2 are out of stock")


def test_every_item_has_an_allergen():
    result = plan_week(
        week(allergens=("Egg",)), menu([item(1, allergens=("Eggs",)), item(2, allergens=("EGG",))])
    )
    assert_explained(result, "2 contain your allergens (eggs)")


def test_calories_and_budget_both_impossible_reports_the_calories():
    # The budget cannot be priced while no week meets the calorie target, so only the
    # calorie problem is reported, not a misleading budget figure.
    result = plan_week(week(kcal=5000, budget_cents=100), menu([item(1, calories=600)]))
    assert_explained(result, "kcal")
    assert "budget" not in result.explanation


@pytest.mark.parametrize(
    "kcal, budget, message",
    [
        (None, 15_000, "Set your daily calorie target"),
        (2000, None, "Set your weekly budget"),
        (-5, 15_000, "Daily calorie target"),
        (2000, 0, "Weekly budget"),
    ],
)
def test_bad_profile_input_is_rejected_before_planning(kcal, budget, message):
    with pytest.raises(InvalidPlanRequest, match=message):
        PlanRequest.from_profile(
            daily_calorie_target=kcal,
            weekly_budget_cents=budget,
            allergies="",
            preferences="",
            start=request().start,
        )
