"""daily_calories on its own: every day lands within 10% of the target."""

import pytest
from menu_factory import OPEN_ALL_DAY, item, menu, request, restaurant

from planner.context import PlanContext
from planner.registry import get
from planner.rules.daily_calories import calorie_band
from planner.solver import Status, plan_week

OneItemPerMeal, DailyCalories = get("one_item_per_meal"), get("daily_calories")


def plan(items, kcal, **kw):
    return plan_week(
        request(kcal=kcal, **kw), menu(items), rules=[OneItemPerMeal(), DailyCalories()]
    )


@pytest.mark.parametrize(
    "target, band", [(2000, (1800, 2200)), (2105, (1895, 2315)), (1850, (1665, 2035))]
)
def test_the_band_is_ten_percent_either_way_in_whole_calories(target, band):
    assert calorie_band(target) == band


def test_every_day_lands_inside_the_band():
    items = [item(1, calories=300), item(2, calories=600), item(3, calories=900)]
    result = plan(items, kcal=2400, days=7)

    assert result.ok
    for kcal in result.kcal_by_day().values():
        assert 2160 <= kcal <= 2640


@pytest.mark.parametrize("kcal, feasible", [(2000, True), (1637, True), (1636, False)])
def test_the_band_edges_are_included(kcal, feasible):
    # Three 600 kcal meals make 1,800 a day: inside the band of 1,637 (up to 1,800.7) but
    # not of 1,636 (up to 1,799.6).
    assert plan([item(1, calories=600)], kcal=kcal).ok is feasible


def test_an_unreachable_target_is_infeasible():
    result = plan([item(1, calories=300)], kcal=3000)
    assert result.status is Status.INFEASIBLE


def test_too_few_calories_is_explained_with_the_closest_total():
    result = plan([item(1, calories=300), item(2, calories=500)], kcal=3000, days=7)
    assert result.explanation == (
        "Your daily target of 3,000 kcal needs each day to total 2,700-3,300 kcal, but no "
        "combination of the available meals gets there. The closest is 1,500 kcal on any day."
    )


def test_too_many_calories_names_only_the_days_that_cannot_make_it():
    # Weekend restaurant only sells 1,200 kcal items; weekdays have a light option.
    weekend = {"Sat": (600, 2300), "Sun": (600, 2300)}
    weekdays = {d: t for d, t in OPEN_ALL_DAY.items() if d not in weekend}
    result = plan_week(
        request(kcal=2000, days=7),
        menu(
            [item(1, calories=1200, rtr_id=1), item(2, calories=600, rtr_id=2)],
            [restaurant(1, hours=weekend), restaurant(2, hours=weekdays)],
        ),
        rules=[OneItemPerMeal(), get("restaurant_open")(), DailyCalories()],
    )
    assert result.explanation == (
        "Your daily target of 2,000 kcal needs each day to total 1,800-2,200 kcal, but no "
        "combination of the available meals gets there. The closest is 3,600 kcal on "
        "Sat Oct 24, Sun Oct 25."
    )


def test_calories_defer_to_the_empty_meal_explanation():
    result = plan_week(
        request(kcal=2000),
        menu([item(1, in_stock=False)]),
        rules=[get("in_stock")(), OneItemPerMeal(), DailyCalories()],
    )
    assert "kcal" not in result.explanation
    assert "out of stock" in result.explanation


def test_no_calorie_explanation_when_every_day_can_reach_the_band():
    ctx = PlanContext(request(kcal=1800), menu([item(1, calories=600)]))
    assert DailyCalories().explain(ctx) is None
