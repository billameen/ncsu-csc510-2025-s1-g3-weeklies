"""pin_meals: meals outside an edit stay exactly as they were."""

from menu_factory import MONDAY, item, menu, request

from planner.context import PlanContext
from planner.registry import get
from planner.solver import plan_week

OneItemPerMeal, PinMeals, InStock = get("one_item_per_meal"), get("pin_meals"), get("in_stock")
PreferLowCost = get("prefer_low_cost")

ITEMS = menu([item(1, price_cents=500), item(2, price_cents=900), item(3, price_cents=1200)])


def test_pinned_meals_keep_their_item_even_when_a_cheaper_one_exists():
    pins = {(MONDAY, 1): 3, (MONDAY, 3): 2}
    result = plan_week(request(), ITEMS, rules=[OneItemPerMeal(), PinMeals(pins), PreferLowCost()])
    assert [(m.meal, m.itm_id) for m in result.meals] == [(1, 3), (2, 1), (3, 2)]


def test_a_pinned_item_that_is_no_longer_available_frees_its_slot():
    gone = menu([item(1, price_cents=500), item(2, in_stock=False)])
    rules = [InStock(), OneItemPerMeal(), PinMeals({(MONDAY, 1): 2})]
    result = plan_week(request(), gone, rules=rules)
    assert result.ok and result.meals[0].itm_id == 1


def test_unavailable_pins_are_recorded_on_the_context():
    gone = menu([item(1), item(2, in_stock=False)])
    ctx = PlanContext(request(), gone)
    InStock().apply(ctx)
    PinMeals({(MONDAY, 1): 2, (MONDAY, 2): 1}).apply(ctx)
    assert [(s.meal) for s in ctx.unpinned] == [1]
    assert [i.itm_id for i in ctx.candidates(ctx.slots[1])] == [1]
