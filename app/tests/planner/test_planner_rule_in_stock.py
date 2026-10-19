"""in_stock on its own: out-of-stock items are never planned."""

from menu_factory import item, menu, request

from planner.registry import get
from planner.solver import plan_week

OneItemPerMeal, InStock = get("one_item_per_meal"), get("in_stock")


def test_out_of_stock_items_are_never_planned():
    result = plan_week(
        request(days=7),
        menu([item(1, in_stock=False), item(2), item(3, in_stock=False)]),
        rules=[OneItemPerMeal(), InStock()],
    )
    assert result.ok and {m.itm_id for m in result.meals} == {2}


def test_everything_out_of_stock_is_explained():
    result = plan_week(
        request(meals=(1,)),
        menu([item(1, in_stock=False), item(2, in_stock=False)]),
        rules=[OneItemPerMeal(), InStock()],
    )
    assert result.explanation == (
        "No breakfast can be planned on Mon Oct 19: of 2 menu items, 2 are out of stock."
    )
