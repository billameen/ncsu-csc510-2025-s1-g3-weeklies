"""day_limit on its own: each covered day's cost or calories within a bound."""

from datetime import timedelta

import pytest
from menu_factory import MONDAY, item, menu, request

from planner.registry import get
from planner.scope import MealScope
from planner.solver import Status, plan_week

OneItemPerMeal, DailyCalories = get("one_item_per_meal"), get("daily_calories")
DayLimit, PreferMeals = get("day_limit"), get("prefer_meals")
CHEAP = item(1, price_cents=500, calories=600)
DEAR = item(2, price_cents=2000, calories=900)
MENU = menu([CHEAP, DEAR])


def picks(result):
    return [m.itm_id for m in result.meals]


def test_a_cost_cap_holds_against_a_pull_the_other_way():
    cap = 2 * DEAR.cost_cents + CHEAP.cost_cents
    result = plan_week(
        request(),
        MENU,
        rules=[OneItemPerMeal(), PreferMeals("more_calories"), DayLimit("cost", "<=", cap)],
    )
    assert sorted(picks(result)) == [1, 2, 2]


def test_a_calorie_floor_holds_against_a_pull_the_other_way():
    result = plan_week(
        request(),
        MENU,
        rules=[OneItemPerMeal(), PreferMeals("cheaper"), DayLimit("calories", ">=", 2200)],
    )
    assert sorted(picks(result)) == [1, 2, 2]


def test_only_the_covered_days_are_limited():
    tuesday = MONDAY + timedelta(days=1)
    result = plan_week(
        request(days=2),
        MENU,
        rules=[
            OneItemPerMeal(),
            PreferMeals("more_calories"),
            DayLimit("cost", "<=", 3 * CHEAP.cost_cents, days={tuesday}),
        ],
    )
    assert picks(result) == [2, 2, 2, 1, 1, 1]


def test_a_cost_cap_below_the_cheapest_valid_day_is_explained():
    result = plan_week(
        request(), MENU, rules=[OneItemPerMeal(), DailyCalories(), DayLimit("cost", "<=", 400)]
    )
    assert result.status is Status.INFEASIBLE
    cheapest = 3 * CHEAP.cost_cents
    assert (
        f"The cheapest day that meets your calorie target costs ${cheapest / 100:,.2f} with "
        "tax and fees; you asked for at most $4.00 a day."
    ) in result.explanation


@pytest.mark.parametrize(
    "op, value, words",
    [("<=", 1000, "needs at least 1,620 kcal"), (">=", 3000, "allows at most 1,980 kcal")],
)
def test_a_calorie_limit_outside_the_target_band_is_explained(op, value, words):
    result = plan_week(
        request(), MENU, rules=[OneItemPerMeal(), DailyCalories(), DayLimit("calories", op, value)]
    )
    assert result.status is Status.INFEASIBLE and words in result.explanation


def test_soften_gets_as_close_as_it_can_and_unmet_names_the_days():
    rule = DayLimit("cost", "<=", 400)
    result = plan_week(
        request(), MENU, rules=[OneItemPerMeal(), PreferMeals("more_calories"), rule.soften()]
    )
    assert picks(result) == [1, 1, 1]
    plan = {m.slot: m.item for m in result.meals}
    cost = 3 * CHEAP.cost_cents / 100
    assert rule.unmet(plan) == f"Mon Oct 19 costs ${cost:,.2f} (you asked for at most $4.00 a day)"
    assert DayLimit("cost", "<=", 10_000).unmet(plan) is None


@pytest.mark.parametrize(
    "args", [("protein", "<=", 10), ("cost", "<", 10), ("cost", "<=", 0), ("calories", ">=", 1.5)]
)
def test_bad_limits_are_rejected(args):
    with pytest.raises(ValueError):
        DayLimit(*args)


def test_the_soft_version_needs_the_rule():
    with pytest.raises(ValueError):
        get("prefer_day_limit")()


def test_unmet_groups_days_with_the_same_total():
    tuesday, wednesday = MONDAY + timedelta(days=1), MONDAY + timedelta(days=2)
    result = plan_week(
        request(days=3),
        MENU,
        rules=[
            OneItemPerMeal(),
            PreferMeals("cheaper", MealScope(days={MONDAY, tuesday})),
            PreferMeals("more_calories", MealScope(days={wednesday})),
        ],
    )
    plan = {m.slot: m.item for m in result.meals}
    cheap_day = f"${3 * CHEAP.cost_cents / 100:,.2f}"
    assert DayLimit("cost", "<=", 400, days={MONDAY, tuesday}).unmet(plan) == (
        f"Every day costs {cheap_day} (you asked for at most $4.00 a day)"
    )
    dear_day = f"${3 * DEAR.cost_cents / 100:,.2f}"
    assert DayLimit("cost", "<=", 400).unmet(plan) == (
        f"Mon Oct 19, Tue Oct 20 cost {cheap_day}; Wed Oct 21 costs {dear_day} "
        "(you asked for at most $4.00 a day)"
    )
    assert DayLimit("calories", ">=", 2500, days={MONDAY}).unmet(plan) == (
        "Mon Oct 19 has 1,800 kcal (you asked for at least 2,500 kcal a day)"
    )
