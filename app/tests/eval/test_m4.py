"""M4 evaluation: the validator's order checks and the eval.m4 metrics (GitHub issue #9)."""
import pytest

from eval.catalog import Catalog, Item, Restaurant
from eval.m4 import PLANNERS, pickup_opt_in, plan_user, summarize
from eval.profiles import Profile
from eval.validate import (
    FOOD_SAFETY_HOURS,
    WEEKDAYS,
    Meal,
    Order,
    PickupOptIn,
    ViolationKind,
    separate_fee_cents,
    validate_orders,
    validate_week,
    week_cost_cents,
)
from planner.fees import FeeSchedule, RestaurantFees
from test_planner_independence import REPO, direct_imports

OPEN = {d: (600, 2300) for d in WEEKDAYS}
FEES = FeeSchedule(overrides={1: RestaurantFees(199, 149)})   # restaurant 2 uses $3.99 + $1.49
CATALOG = Catalog(
    items={
        1: Item(1, 1, 1000, 700, ()),
        2: Item(2, 2, 1000, 700, ()),
    },
    restaurants={1: Restaurant(1, OPEN), 2: Restaurant(2, OPEN)},
    fees=FEES,
)
MON_B, MON_L, MON_D = Meal("Mon", 1, 1), Meal("Mon", 2, 1), Meal("Mon", 3, 1)


def kinds(violations):
    return {v.kind for v in violations}


# --- Validator: orders --------------------------------------------------------

def test_a_valid_batch_has_no_order_violations():
    meals = (MON_B, MON_L, MON_D)
    orders = (Order((MON_B, MON_L)), Order((MON_D,)))
    assert validate_orders(meals, orders, CATALOG, PickupOptIn()) == []


def test_meals_more_than_6_hours_apart_in_one_order_break_food_safety():
    assert FOOD_SAFETY_HOURS == 6
    v = validate_orders((MON_B, MON_D), (Order((MON_B, MON_D)),), CATALOG, PickupOptIn())
    assert kinds(v) == {ViolationKind.FOOD_SAFETY}


def test_one_order_from_two_restaurants_or_two_days_is_mixed():
    other = Meal("Mon", 3, 2)
    tue = Meal("Tue", 1, 1)
    assert kinds(validate_orders((MON_L, other), (Order((MON_L, other)),), CATALOG, PickupOptIn())) \
        == {ViolationKind.MIXED_ORDER}
    assert ViolationKind.MIXED_ORDER in kinds(
        validate_orders((MON_D, tue), (Order((MON_D, tue)),), CATALOG, PickupOptIn()))


def test_a_meal_missing_from_the_orders_or_in_two_of_them_is_a_mismatch():
    assert kinds(validate_orders((MON_B, MON_L), (Order((MON_B,)),), CATALOG, PickupOptIn())) \
        == {ViolationKind.ORDER_MISMATCH}
    assert kinds(validate_orders((MON_B,), (Order((MON_B,)), Order((MON_B,))), CATALOG, PickupOptIn())) \
        == {ViolationKind.ORDER_MISMATCH}


@pytest.mark.parametrize("opt_in, ok", [
    (PickupOptIn(frozenset({1}), frozenset({"Mon"})), True),
    (PickupOptIn(frozenset({1}), frozenset()), False),
    (PickupOptIn(frozenset(), frozenset({"Mon"})), False),
    (PickupOptIn(), False),
])
def test_pickup_needs_the_user_to_opt_into_restaurant_and_day(opt_in, ok):
    v = validate_orders((MON_L,), (Order((MON_L,), pickup=True),), CATALOG, opt_in)
    assert (v == []) is ok
    if not ok:
        assert kinds(v) == {ViolationKind.PICKUP_NOT_OPTED}


def test_week_cost_uses_one_set_of_fees_per_order_and_none_for_delivery_on_pickup():
    food = 3 * (1000 + 73)
    batched = (Order((MON_B, MON_L)), Order((MON_D,)))
    assert week_cost_cents(batched, CATALOG) == food + 2 * (199 + 149)
    picked_up = (Order((MON_B, MON_L), pickup=True), Order((MON_D,)))
    assert week_cost_cents(picked_up, CATALOG) == food + 149 + (199 + 149)
    assert separate_fee_cents((MON_B, MON_L, MON_D), CATALOG) == 3 * (199 + 149)


def test_the_budget_is_checked_against_the_orders_actual_cost():
    # Three $10.00 meals: $42.63 as separate orders from restaurant 1, $39.15 batched.
    profile = Profile(user_id=1, kcal_target=2100, budget_dollars=40, allergens=(), hard=False)
    meals = (MON_B, MON_L, MON_D)
    separate = validate_week(meals, profile, CATALOG)
    batched = validate_week(meals, profile, CATALOG, (Order((MON_B, MON_L)), Order((MON_D,))))
    assert ViolationKind.OVER_BUDGET in kinds(separate)
    assert ViolationKind.OVER_BUDGET not in kinds(batched)


def test_the_validator_only_takes_fee_data_from_the_planner_package():
    validate = (REPO / "eval" / "validate.py").read_text()
    fees = (REPO / "app" / "planner" / "fees.py").read_text()
    planner_imports = {m for m in direct_imports(validate) if m.split(".")[0] == "planner"}
    assert planner_imports and all(m == "planner.fees" or m.startswith("planner.fees.") for m in planner_imports)
    assert not {m for m in direct_imports(fees) if m.startswith(("planner", "menu", "eval"))}


# --- eval.m4 ------------------------------------------------------------------

def test_pickup_opt_ins_are_deterministic_and_cover_about_half_the_users():
    catalog = Catalog(items={}, restaurants={r: Restaurant(r, OPEN) for r in range(1, 21)})
    profiles = [Profile(u, 2000, 400, (), False) for u in range(1, 101)]
    first = [pickup_opt_in(p, catalog, 510) for p in profiles]
    again = [pickup_opt_in(p, catalog, 510) for p in profiles]
    opted = [o for o in first if o.restaurants]
    assert first == again
    assert 35 <= len(opted) <= 65
    assert all(len(o.restaurants) == 5 and {"Sat", "Sun"} <= o.days and len(o.days) == 3 for o in opted)


def _rec(user, planner, valid, fees, distinct=20, fs=0):
    return {"user_id": user, "planner": planner, "valid": valid, "fees_cents": fees,
            "distinct_items": distinct, "seconds": 1.0, "orders": 21 if planner == "m1" else 15,
            "food_safety_violations": fs, "order_violations": fs}


def test_summary_metrics_match_a_hand_computed_example():
    records = {}
    # User 1: $100.00 -> $70.00 (30%). User 2: $100.00 -> $80.00 (20%). User 3: only
    # possible with batching. User 4: no plan either way.
    for user, m1, m4 in [(1, (True, 10000), (True, 7000)), (2, (True, 10000), (True, 8000)),
                         (3, (False, 0), (True, 6000)), (4, (False, 0), (False, 0))]:
        records[(user, "m1")] = _rec(user, "m1", *m1)
        for p in PLANNERS[1:]:
            records[(user, p)] = _rec(user, p, *m4, distinct=19)
    report = summarize(records, [1, 2, 3, 4])
    c = report["checks"]["m4_batching"]

    assert report["users_done"] == 4
    assert c["savings_pct"] == [30.0, 20.0] and c["median_savings_pct"] == 25.0
    assert c["savings_pass"] is True
    assert (c["valid_week_pct_m1"], c["valid_week_pct"], c["valid_pass"]) == (50.0, 75.0, True)
    assert (c["variety_drop"], c["variety_pass"]) == (1, True)
    assert (c["budgets_made_possible"], c["users_made_possible"]) == (1, [3])
    assert c["food_safety_pass"] is True and c["valid_weeks_lost"] == []


def test_summary_fails_targets_that_are_missed():
    records = {(1, "m1"): _rec(1, "m1", True, 10000, distinct=20)}
    for p in PLANNERS[1:]:
        records[(1, p)] = _rec(1, p, True, 9000, distinct=15, fs=1)
    c = summarize(records, [1])["checks"]["m4_batching"]
    assert c["savings_pass"] is False          # 10% < 25%
    assert c["variety_pass"] is False          # dropped 5 items
    assert c["food_safety_pass"] is False


def test_plan_user_validates_the_planners_week_on_its_own(tmp_path):
    from scripts.init_db import init_db
    from eval.catalog import load_catalog

    db = tmp_path / "seed.db"
    init_db(db_file=str(db))
    catalog = load_catalog(str(db))
    profile = Profile(user_id=7, kcal_target=2200, budget_dollars=450, allergens=(), hard=False)

    # A generous limit: with coverage on, a slower machine can use up the app's 4 s just
    # building the model, and a timeout would fail this test for the wrong reason.
    off = plan_user(profile, catalog, "m1", 510, time_limit_s=30)
    on = plan_user(profile, catalog, "m4_batching", 510, time_limit_s=30)

    assert off["valid"] and on["valid"], (off, on)
    assert on["fees_cents"] == on["planner_fees_cents"] < off["fees_cents"]
    assert on["batched_orders"] > 0 and on["orders"] < off["orders"] == 21
    assert on["food_safety_violations"] == 0
