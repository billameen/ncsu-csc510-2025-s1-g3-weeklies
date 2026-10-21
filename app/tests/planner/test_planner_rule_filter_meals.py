"""filter_meals on its own: every meal in the scope meets the condition."""

import pytest
from menu_factory import item, menu, request

from planner.match import Condition
from planner.registry import get
from planner.scope import MealScope
from planner.solver import Status, plan_week

OneItemPerMeal, FilterMeals = get("one_item_per_meal"), get("filter_meals")
UNDER_10 = Condition("price", "<=", 1000)


def test_only_matching_items_inside_the_scope():
    result = plan_week(
        request(),
        menu([item(1, price_cents=1000), item(2, price_cents=1001)]),
        rules=[OneItemPerMeal(), FilterMeals(UNDER_10, MealScope(meals={3}))],
    )
    assert [m.itm_id for m in result.meals if m.meal == 3] == [1]


def test_meals_outside_the_scope_are_left_alone():
    result = plan_week(
        request(meals=(1,)),
        menu([item(2, price_cents=1500)]),
        rules=[OneItemPerMeal(), FilterMeals(UNDER_10, MealScope(meals={3}))],
    )
    assert result.ok and [m.itm_id for m in result.meals] == [2]


def test_nothing_matching_is_explained_with_the_condition():
    result = plan_week(
        request(meals=(2,)),
        menu([item(1, price_cents=1500)]),
        rules=[OneItemPerMeal(), FilterMeals(UNDER_10)],
    )
    assert result.status is Status.INFEASIBLE
    assert "1 are over $10.00" in result.explanation


def test_soften_and_unmet_describe_the_closest_option():
    rule = FilterMeals(Condition("tag", "is", "vegetarian"))
    assert rule.soften().name == "prefer_edits"
    result = plan_week(request(), menu([item(1, name="Beef Plate")]), rules=[OneItemPerMeal()])
    plan = {m.slot: m.item for m in result.meals}
    assert rule.unmet(plan) == "3 of 3 meals (every day) are not vegetarian"


def test_a_condition_is_required():
    with pytest.raises(ValueError):
        FilterMeals("vegetarian")
