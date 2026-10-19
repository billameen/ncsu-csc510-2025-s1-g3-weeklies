"""require_tag on its own: only tagged items inside the scope, anything outside it."""

from datetime import date

import pytest
from menu_factory import item, menu, request

from planner.registry import get
from planner.scope import MealScope
from planner.solver import Status, plan_week

OneItemPerMeal, RequireTag = get("one_item_per_meal"), get("require_tag")
PreferLowCost = get("prefer_low_cost")
TUESDAY = date(2026, 10, 20)

VEG = item(1, name="Mushroom Risotto", price_cents=1500)
STEAK = item(2, name="Steak Frites", price_cents=900)


def test_only_tagged_items_inside_the_scope_and_anything_outside():
    result = plan_week(
        request(days=2),
        menu([VEG, STEAK]),
        rules=[
            OneItemPerMeal(),
            RequireTag("vegetarian", MealScope(days={TUESDAY})),
            PreferLowCost(),
        ],
    )
    by_day = {(m.day, m.meal): m.itm_id for m in result.meals}
    assert all(i == 2 for (d, _), i in by_day.items() if d != TUESDAY)  # cheaper steak
    assert all(i == 1 for (d, _), i in by_day.items() if d == TUESDAY)


def test_no_tagged_item_is_explained_with_the_tag():
    result = plan_week(
        request(meals=(3,)),
        menu([STEAK]),
        rules=[OneItemPerMeal(), RequireTag("vegetarian")],
    )
    assert result.status is Status.INFEASIBLE
    assert "1 are not vegetarian" in result.explanation


def test_unknown_tags_are_refused():
    with pytest.raises(ValueError, match="unknown tag 'keto'"):
        RequireTag("keto")
