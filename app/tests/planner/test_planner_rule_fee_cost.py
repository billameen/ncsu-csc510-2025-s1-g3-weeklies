"""fee_cost (FeeCostConstraint, M4): fees per order, batching and pickup."""
from dataclasses import dataclass

import pytest
from menu_factory import item, menu, request, restaurant

from planner.fees import DEFAULT_FEES, FeeSchedule, RestaurantFees
from planner.menu import meal_cost_cents
from planner.registry import get, rules_for
from planner.rules.fee_cost import batch_groups
from planner.solver import Status, plan_week

OneItemPerMeal, WeeklyBudget, PreferLowCost = (
    get("one_item_per_meal"), get("weekly_budget"), get("prefer_low_cost"))
FeeCost = get("fee_cost")
ORDER_FEE = DEFAULT_FEES.order_fee_cents()          # $3.99 + $1.49 = 548


def plan(items, fee_rule, budget_cents=100_000, fees=None, **kw):
    return plan_week(
        request(budget_cents=budget_cents, **kw),
        menu(items, fees=fees),
        rules=[OneItemPerMeal(), fee_rule, WeeklyBudget(), PreferLowCost()],
    )


def _sizes(result):
    return [len(o.meals) for o in result.orders]


# --- Expected behaviour -------------------------------------------------------

@pytest.mark.parametrize("meals", [(1, 2), (2, 3)])   # 4 h and 6 h apart
def test_same_restaurant_meals_within_6_hours_are_one_order(meals):
    result = plan([item(1)], FeeCost(batching=True), meals=meals)

    assert result.ok
    assert _sizes(result) == [2]
    assert result.orders[0].batched and result.fees_cents == ORDER_FEE
    assert result.fee_savings_cents == ORDER_FEE


def test_a_full_day_from_one_restaurant_is_two_orders_not_three():
    # Breakfast and dinner are 10 h apart, so all three cannot share one delivery.
    result = plan([item(1)], FeeCost(batching=True))

    assert sorted(_sizes(result)) == [1, 2]
    assert result.fees_cents == 2 * ORDER_FEE


def test_pickup_has_no_delivery_fee():
    rule = FeeCost(pickup_restaurants=[1], pickup_days=["Mon"])
    result = plan([item(1)], rule, meals=(2,))

    assert result.orders[0].pickup is True
    assert result.fees_cents == DEFAULT_FEES.service_fee_cents      # $1.49, no $3.99


def test_savings_math_matches_a_hand_computed_example():
    # Restaurant 1 charges $1.99 delivery + $1.49 service = $3.48 per order. Three $10.00
    # meals: separately 3 x $3.48 = $10.44 in fees; batched (lunch + dinner) 2 orders = $6.96.
    fees = FeeSchedule(overrides={1: RestaurantFees(199, 149)})
    result = plan([item(1)], FeeCost(batching=True), fees=fees)

    assert result.separate_fees_cents == 1044
    assert result.fees_cents == 696
    assert result.fee_savings_cents == 348
    assert result.total_cost_cents == 3 * (1000 + 73) + 696


def test_the_115_dollar_week_drops_to_76_dollars_72_with_batching():
    # The issue's demo: 21 meals at $3.99 + $1.49 each is $115.08 in fees. One batch a day
    # (breakfast + lunch or lunch + dinner) makes 14 orders: 14 x $5.48 = $76.72.
    week = dict(days=7)
    off = plan([item(1)], FeeCost(), **week)
    on = plan([item(1)], FeeCost(batching=True), **week)

    assert (off.fees_cents, len(off.orders)) == (11508, 21)
    assert (on.fees_cents, len(on.orders)) == (7672, 14)
    assert on.fee_savings_cents == 11508 - 7672


def test_default_fees_reproduce_m1s_per_meal_charges():
    result = plan([item(1, price_cents=500), item(2, price_cents=2000)], FeeCost(), days=2)

    assert result.ok and len(result.orders) == len(result.meals) == 6
    assert result.total_cost_cents == sum(meal_cost_cents(m.item.price_cents) for m in result.meals)
    assert result.fees_cents == result.separate_fees_cents == 6 * ORDER_FEE
    assert result.fee_savings_cents == 0


def test_fee_cost_is_on_by_default_with_batching_off():
    rules = rules_for(request())
    fee_rules = [r for r in rules if isinstance(r, FeeCost)]
    assert len(fee_rules) == 1 and fee_rules[0].batching is False
    assert not fee_rules[0].pickup_restaurants and not fee_rules[0].pickup_days


def test_per_restaurant_fees_steer_the_plan_to_cheaper_delivery():
    # Same food, but restaurant 2 delivers for $1.99 instead of $5.99.
    fees = FeeSchedule(overrides={1: RestaurantFees(599, 149), 2: RestaurantFees(199, 149)})
    result = plan([item(1, rtr_id=1), item(2, rtr_id=2)], FeeCost(), fees=fees, meals=(2,))

    assert result.meals[0].item.rtr_id == 2
    assert result.fees_cents == 199 + 149


# --- Failure cases ------------------------------------------------------------

@dataclass(frozen=True)
class _Slot:
    time: int


@pytest.mark.parametrize("times, grouped", [
    ((1000, 1600), True),    # 6 h apart: may share a delivery
    ((1000, 1700), False),   # 7 h apart: too long to hold food
    ((1000, 1400, 2000), False),
])
def test_meals_7_hours_apart_are_never_batched(times, grouped):
    slots = [_Slot(t) for t in times]
    groups = batch_groups(slots)
    if len(times) == 2:
        assert bool(groups) is grouped
    else:
        assert all(g[-1].time - g[0].time <= 600 for g in groups)
        assert (slots[0], slots[2]) not in groups and tuple(slots) not in groups


def test_breakfast_and_dinner_10_hours_apart_stay_separate():
    result = plan([item(1)], FeeCost(batching=True), meals=(1, 3))
    assert _sizes(result) == [1, 1]


def test_batching_off_keeps_every_meal_its_own_order():
    result = plan([item(1)], FeeCost(batching=False), meals=(1, 2))
    assert _sizes(result) == [1, 1] and result.fee_savings_cents == 0


def test_meals_from_different_restaurants_are_never_one_order():
    lunch_only = item(1, rtr_id=1, calories=900)
    dinner_only = item(2, rtr_id=2, calories=900)
    hours_lunch = {d: (1100, 1500) for d in ("Mon",)}
    hours_dinner = {d: (1800, 2200) for d in ("Mon",)}
    result = plan_week(
        request(meals=(2, 3)),
        menu([lunch_only, dinner_only], [restaurant(1, hours_lunch), restaurant(2, hours_dinner)]),
        rules=[get("restaurant_open")(), OneItemPerMeal(), FeeCost(batching=True), PreferLowCost()],
    )
    assert result.ok and _sizes(result) == [1, 1]
    assert {o.rtr_id for o in result.orders} == {1, 2}


@pytest.mark.parametrize("restaurants, days", [
    ([1], []),          # opted into the restaurant but no day
    ([], ["Mon"]),      # opted into the day but no restaurant
    ([2], ["Mon"]),     # a different restaurant
    ([1], ["Tue"]),     # a different day
])
def test_pickup_without_opting_into_both_restaurant_and_day_pays_delivery(restaurants, days):
    rule = FeeCost(pickup_restaurants=restaurants, pickup_days=days)
    result = plan([item(1)], rule, meals=(2,))

    assert result.orders[0].pickup is False
    assert result.fees_cents == ORDER_FEE


@pytest.mark.parametrize("kwargs", [
    {"batching": "yes"},
    {"pickup_restaurants": [0]},
    {"pickup_restaurants": ["3"]},
    {"pickup_days": ["Monday"]},
    {"window_hours": 0},
    {"window_hours": 6.5},
])
def test_invalid_fee_options_are_refused(kwargs):
    with pytest.raises(ValueError):
        FeeCost(**kwargs)


def test_a_budget_that_only_fits_with_batching_on():
    # A day of three $10.00 meals: $48.63 separately, $43.15 with one batch.
    separately = 3 * meal_cost_cents(1000)
    batched = separately - ORDER_FEE
    budget = batched + 100

    off = plan([item(1)], FeeCost(), budget_cents=budget)
    on = plan([item(1)], FeeCost(batching=True), budget_cents=budget)

    assert off.status is Status.INFEASIBLE
    assert "$48.63 with tax and fees" in off.explanation
    assert on.ok and on.total_cost_cents == batched <= budget


def test_only_one_rule_may_set_the_fees():
    with pytest.raises(ValueError, match="already set"):
        plan_week(request(), menu([item(1)]), rules=[OneItemPerMeal(), FeeCost(), FeeCost(batching=True)])


# --- Every plan's orders are consistent ---------------------------------------

def test_orders_cover_each_meal_once_from_one_restaurant_within_6_hours():
    items = [item(i, rtr_id=1 + i % 3, price_cents=600 + 150 * i, calories=500 + 40 * i) for i in range(1, 10)]
    fees = FeeSchedule(overrides={1: RestaurantFees(199, 149), 2: RestaurantFees(599, 149)})
    result = plan_week(
        request(kcal=1800, days=7),
        menu(items, fees=fees),
        rules=[OneItemPerMeal(), get("daily_calories")(),
               FeeCost(batching=True, pickup_restaurants=[3], pickup_days=["Sat", "Sun"]),
               WeeklyBudget(), PreferLowCost(), get("prefer_variety")()],
    )
    assert result.ok
    in_orders = [m.slot.index for o in result.orders for m in o.meals]
    assert sorted(in_orders) == [m.slot.index for m in result.meals]
    for o in result.orders:
        assert {m.item.rtr_id for m in o.meals} == {o.rtr_id}
        assert {m.day for m in o.meals} == {o.day}
        times = sorted(m.slot.time for m in o.meals)
        assert times[-1] - times[0] <= 600
        assert o.pickup == (o.rtr_id == 3 and o.day.strftime("%a") in ("Sat", "Sun"))
    assert result.total_cost_cents == sum(m.food_cost_cents for m in result.meals) + result.fees_cents
