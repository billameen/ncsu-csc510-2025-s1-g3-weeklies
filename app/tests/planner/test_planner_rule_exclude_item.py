"""exclude_item on its own."""

import pytest
from menu_factory import item, menu, request

from planner.registry import get
from planner.scope import MealScope
from planner.solver import Status, plan_week

OneItemPerMeal, ExcludeItem = get("one_item_per_meal"), get("exclude_item")
PreferLowCost = get("prefer_low_cost")


def test_excluded_items_are_never_planned_in_scope():
    result = plan_week(
        request(days=2),
        menu([item(1, price_cents=500, name="Beef Ribs"), item(2, price_cents=900)]),
        rules=[OneItemPerMeal(), ExcludeItem({1}, "Beef Ribs"), PreferLowCost()],
    )
    assert {m.itm_id for m in result.meals} == {2}


def test_outside_the_scope_the_item_is_still_allowed():
    result = plan_week(
        request(),
        menu([item(1, price_cents=500), item(2, price_cents=900)]),
        rules=[OneItemPerMeal(), ExcludeItem({1}, "Toast", MealScope(meals={1})), PreferLowCost()],
    )
    assert [m.itm_id for m in result.meals] == [2, 1, 1]


def test_excluding_the_only_item_is_explained_by_name():
    result = plan_week(
        request(meals=(1,)), menu([item(1)]), rules=[OneItemPerMeal(), ExcludeItem({1}, "Toast")]
    )
    assert result.status is Status.INFEASIBLE
    assert "1 are excluded (Toast)" in result.explanation


def test_an_empty_exclusion_is_refused():
    with pytest.raises(ValueError):
        ExcludeItem(set(), "nothing")
