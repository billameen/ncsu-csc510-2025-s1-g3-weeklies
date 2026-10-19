"""daily_calories on its own: every day lands within 10% of the target."""

import pytest
from menu_factory import item, menu, request

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
