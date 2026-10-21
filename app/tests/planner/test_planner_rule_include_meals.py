"""include_meals on its own: at least `times` meals in the scope meet the condition."""

import pytest
from menu_factory import item, menu, request

from planner.match import Condition
from planner.registry import get
from planner.scope import MealScope
from planner.solver import Status, plan_week

OneItemPerMeal, PreferLowCost = get("one_item_per_meal"), get("prefer_low_cost")
IncludeMeals, FilterMeals = get("include_meals"), get("filter_meals")
PIZZA = Condition("dish", "is", "pizza", ids={2})
MENU = menu([item(1, name="Toast", price_cents=500), item(2, name="Pizza", price_cents=1500)])


def picks(result):
    return [m.itm_id for m in result.meals]


@pytest.mark.parametrize("times", [1, 2])
def test_exactly_as_many_matching_meals_as_asked_when_they_cost_more(times):
    result = plan_week(
        request(),
        MENU,
        rules=[OneItemPerMeal(), PreferLowCost(), IncludeMeals(PIZZA, times=times)],
    )
    assert picks(result).count(2) == times


def test_the_match_lands_inside_the_scope():
    result = plan_week(
        request(),
        MENU,
        rules=[OneItemPerMeal(), PreferLowCost(), IncludeMeals(PIZZA, MealScope(meals={3}))],
    )
    assert picks(result) == [1, 1, 2]


def test_no_matching_item_available_is_explained():
    result = plan_week(
        request(),
        MENU,
        rules=[OneItemPerMeal(), FilterMeals(Condition("price", "<=", 1000)), IncludeMeals(PIZZA)],
    )
    assert result.status is Status.INFEASIBLE
    assert 'No item that is "pizza" can be planned for every day' in result.explanation


def test_too_few_meals_in_the_scope_is_explained():
    result = plan_week(
        request(),
        MENU,
        rules=[OneItemPerMeal(), IncludeMeals(PIZZA, MealScope(meals={3}), times=2)],
    )
    assert result.status is Status.INFEASIBLE
    assert "Only 1 of the meals" in result.explanation and "you asked for 2" in result.explanation


def test_soften_plans_as_many_as_possible_and_unmet_says_what_is_missing():
    rule = IncludeMeals(PIZZA, MealScope(meals={3}), times=2)
    result = plan_week(request(), MENU, rules=[OneItemPerMeal(), PreferLowCost(), rule.soften()])
    assert picks(result) == [1, 1, 2]
    plan = {m.slot: m.item for m in result.meals}
    assert rule.unmet(plan) == 'Only 1 of the 2 meals you asked for (every day dinner) are "pizza"'
    toast_only = {slot: MENU.items[1] for slot in plan}
    assert rule.unmet(toast_only) == 'No meal (every day dinner) is "pizza"'


@pytest.mark.parametrize("times", [0, 22, 1.5, True])
def test_times_must_be_1_to_21(times):
    with pytest.raises(ValueError):
        IncludeMeals(PIZZA, times=times)


def test_the_soft_version_needs_the_rule():
    with pytest.raises(ValueError):
        get("prefer_include")()
