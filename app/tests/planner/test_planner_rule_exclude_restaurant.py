"""exclude_restaurant on its own."""

import pytest
from menu_factory import MONDAY, item, menu, request

from planner.registry import get
from planner.scope import MealScope
from planner.solver import Status, plan_week

OneItemPerMeal, ExcludeRestaurant = get("one_item_per_meal"), get("exclude_restaurant")

TWO = menu([item(1, rtr_id=1), item(2, rtr_id=2)])


def test_items_from_an_excluded_restaurant_are_never_planned_in_scope():
    result = plan_week(
        request(days=2), TWO, rules=[OneItemPerMeal(), ExcludeRestaurant({1}, "Sorella's")]
    )
    assert {m.item.rtr_id for m in result.meals} == {2}


def test_outside_the_scope_the_restaurant_is_still_used():
    cheap_first = menu([item(1, rtr_id=1, price_cents=500), item(2, rtr_id=2, price_cents=900)])
    result = plan_week(
        request(days=2),
        cheap_first,
        rules=[
            OneItemPerMeal(),
            ExcludeRestaurant({1}, "Sorella's", MealScope(days={MONDAY})),
            get("prefer_low_cost")(),
        ],
    )
    by_day = {
        d: {m.item.rtr_id for m in result.meals if m.day == d}
        for d in {m.day for m in result.meals}
    }
    assert by_day[MONDAY] == {2}
    assert set().union(*(v for d, v in by_day.items() if d != MONDAY)) == {1}


def test_excluding_every_restaurant_is_explained_by_name():
    result = plan_week(
        request(meals=(3,)),
        menu([item(1, rtr_id=1)]),
        rules=[OneItemPerMeal(), ExcludeRestaurant({1}, "Sorella's")],
    )
    assert result.status is Status.INFEASIBLE
    assert "come from Sorella's, which you excluded" in result.explanation


def test_an_empty_exclusion_is_refused():
    with pytest.raises(ValueError):
        ExcludeRestaurant([], "nowhere")
