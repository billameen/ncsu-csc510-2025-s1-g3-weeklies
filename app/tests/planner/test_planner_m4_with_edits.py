"""M4 (fees per order, batching, pickup) working together with M3's plan edits."""
from datetime import date

import pytest
from menu_factory import item, menu, request

from planner.edits.replan import check_proposal
from planner.fees import FeeSchedule, RestaurantFees
from planner.registry import get
from planner.solver import plan_week

OneItemPerMeal, WeeklyBudget, PreferLowCost = (
    get("one_item_per_meal"), get("weekly_budget"), get("prefer_low_cost"))
FeeCost, DayLimit = get("fee_cost"), get("day_limit")
FEES = FeeSchedule(overrides={1: RestaurantFees(199, 149), 2: RestaurantFees(599, 149)})
BATCHING = {"fee_cost": {"batching": True}}


def _items():
    return [item(1, 900, 600, rtr_id=1), item(2, 1100, 600, rtr_id=1),
            item(3, 700, 600, rtr_id=2), item(4, 1500, 600, rtr_id=2)]


@pytest.mark.parametrize("rule", [FeeCost(), FeeCost(batching=True),
                                  FeeCost(batching=True, pickup_restaurants=[2], pickup_days=["Mon"])])
def test_pricing_a_saved_week_matches_what_the_solver_charged(rule):
    m = menu(_items(), fees=FEES)
    result = plan_week(request(days=2), m, rules=[OneItemPerMeal(), rule, WeeklyBudget(), PreferLowCost()])
    assert result.ok
    plan = {meal.slot: meal.item for meal in result.meals}
    assert rule.plan_fees_cents(FEES, plan) == result.fees_cents


def test_pricing_a_saved_week_finds_the_cheapest_batching():
    m = menu(_items(), fees=FEES)
    slots = request(days=1).slots()
    one_restaurant = {s: m.items[1] for s in slots}             # B, L, D all from restaurant 1
    # Only one pair of the three can share a delivery (breakfast to dinner is 10 hours).
    assert FeeCost(batching=True).plan_fees_cents(FEES, one_restaurant) == 2 * 348
    assert FeeCost().plan_fees_cents(FEES, one_restaurant) == 3 * 348
    picked_up = FeeCost(pickup_restaurants=[1], pickup_days=["Mon"])
    assert picked_up.plan_fees_cents(FEES, one_restaurant) == 3 * 149


def test_accepting_an_edit_of_a_batched_week_reads_its_order_tags():
    m = menu(_items(), fees=FEES)
    req = request(days=2, options=BATCHING)
    entries = plan_week(req, m).menu_entries()
    assert any(e.count(",") == 3 for e in entries)              # some meals carry an order tag
    assert check_proposal(req, m, entries) is None


def test_edits_still_see_batched_days_as_planned():
    import Flask_app
    day = date(2026, 10, 21)
    gen = "[2026-10-21,5,1,o1],[2026-10-21,6,2,o1],[2026-10-21,7,3]"
    assert Flask_app.planned_days(gen, [day]) == [day]
    assert Flask_app.current_plan(gen, [day]) == {(day, 1): 5, (day, 2): 6, (day, 3): 7}


def test_a_missed_daily_cost_limit_is_priced_with_the_restaurants_own_fees():
    m = menu(_items(), fees=FEES)
    limit = DayLimit("cost", "<=", 1)
    result = plan_week(request(days=1), m, rules=[OneItemPerMeal(), FeeCost(), limit])
    assert not result.ok
    plan = {s: m.items[3] for s in request(days=1).slots()}    # restaurant 2: $5.99 delivery
    expected = 3 * FEES.meal_cost_cents(700, 2)
    assert f"${expected / 100:,.2f}" in limit.unmet(plan)
