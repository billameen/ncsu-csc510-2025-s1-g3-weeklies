"""prefer_meals on its own: soft goals inside a scope."""

import pytest
from menu_factory import item, menu, request

from planner.match import Condition
from planner.registry import get
from planner.scope import MealScope
from planner.solver import plan_week

OneItemPerMeal, PreferMeals = get("one_item_per_meal"), get("prefer_meals")
PreferLowCost = get("prefer_low_cost")
CHEAP = item(1, name="Beef Plate", price_cents=500, calories=900)
LIGHT = item(2, name="Garden Salad", price_cents=1500, calories=300)
MENU = menu([CHEAP, LIGHT])


def picks(*rules, **kw):
    result = plan_week(request(**kw), MENU, rules=[OneItemPerMeal(), *rules])
    assert result.ok
    return [m.itm_id for m in result.meals]


@pytest.mark.parametrize(
    "goal, expected",
    [("cheaper", 1), ("fewer_calories", 2), ("more_calories", 1)],
)
def test_goals_steer_every_covered_meal(goal, expected):
    assert picks(PreferMeals(goal)) == [expected] * 3


def test_a_goal_only_steers_its_scope():
    breakfast_lunch, dinner = MealScope(meals={1, 2}), MealScope(meals={3})
    chosen = picks(PreferMeals("cheaper", breakfast_lunch), PreferMeals("fewer_calories", dinner))
    assert chosen == [1, 1, 2]


def test_match_prefers_the_condition_but_never_requires_it():
    vegetarian = Condition("tag", "is", "vegetarian")
    # The salad costs more, but a match outweighs the plan's usual preference for lower cost.
    assert picks(PreferLowCost(), PreferMeals("match", condition=vegetarian)) == [2, 2, 2]
    beef_only = menu([CHEAP])
    result = plan_week(
        request(), beef_only, rules=[OneItemPerMeal(), PreferMeals("match", condition=vegetarian)]
    )
    assert result.ok


def test_variety_avoids_repeats_inside_the_scope():
    assert picks(PreferLowCost(), meals=(1, 2)) == [1, 1]
    assert sorted(picks(PreferLowCost(), PreferMeals("variety"), meals=(1, 2))) == [1, 2]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"goal": "tastier"},
        {"goal": "match"},  # needs a condition
        {"goal": "cheaper", "condition": Condition("tag", "is", "vegan")},
    ],
)
def test_bad_goals_are_rejected(kwargs):
    with pytest.raises(ValueError):
        PreferMeals(**kwargs)
