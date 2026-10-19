"""max_price on its own: menu price at or under the limit inside the scope."""

import pytest
from menu_factory import item, menu, request

from planner.registry import get
from planner.scope import MealScope
from planner.solver import Status, plan_week

OneItemPerMeal, MaxPrice = get("one_item_per_meal"), get("max_price")


def test_only_items_at_or_under_the_price_inside_the_scope():
    result = plan_week(
        request(),
        menu([item(1, price_cents=1000), item(2, price_cents=1001)]),
        rules=[OneItemPerMeal(), MaxPrice(1000, MealScope(meals={3}))],
    )
    assert [m.itm_id for m in result.meals if m.meal == 3] == [1]


def test_nothing_cheap_enough_is_explained_with_the_limit():
    result = plan_week(
        request(meals=(2,)),
        menu([item(1, price_cents=1500)]),
        rules=[OneItemPerMeal(), MaxPrice(1000)],
    )
    assert result.status is Status.INFEASIBLE
    assert "1 cost more than $10.00" in result.explanation


@pytest.mark.parametrize("bad", [0, -100, 9.99])
def test_the_limit_must_be_positive_cents(bad):
    with pytest.raises(ValueError):
        MaxPrice(bad)
