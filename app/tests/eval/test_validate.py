import pytest

from eval.catalog import Catalog, Item, Restaurant
from eval.profiles import Profile
from eval.validate import (
    MEAL_TIMES,
    WEEKDAYS,
    Meal,
    Violation,
    ViolationKind,
    order_cost_cents,
    validate_week,
)

OPEN_ALL_WEEK = {day: (600, 2300) for day in WEEKDAYS}


def item(itm_id, price_cents=1000):
    return Item(itm_id=itm_id, rtr_id=1, price_cents=price_cents, calories=700, allergens=())


# Per order: $10.00 costs $16.21, $9.62 costs $15.80 and $9.63 costs $15.81 (see the
# order_cost_cents cases below).
CATALOG = Catalog(
    items={1: item(1), 2: item(2, price_cents=962), 3: item(3, price_cents=963)},
    restaurants={1: Restaurant(rtr_id=1, hours=OPEN_ALL_WEEK)},
)

# 21 x item 1 costs $340.41, well under budget; 3 x 700 kcal hits the target exactly.
PROFILE = Profile(user_id=1, kcal_target=2100, budget_dollars=650, allergens=(), hard=False)


def full_week(itm_id=1):
    return [Meal(day=day, meal=meal, itm_id=itm_id) for day in WEEKDAYS for meal in MEAL_TIMES]


def with_budget(budget_dollars):
    return Profile(
        user_id=1, kcal_target=2100, budget_dollars=budget_dollars, allergens=(), hard=False
    )


def swap(meals, day, meal, itm_id):
    """Replace the item in one slot."""
    return [m if (m.day, m.meal) != (day, meal) else Meal(day, meal, itm_id) for m in meals]


def test_the_week_has_seven_days_of_three_meals():
    assert WEEKDAYS == ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    assert MEAL_TIMES == {1: 1000, 2: 1400, 3: 2000}


def test_valid_week_has_no_violations():
    assert validate_week(full_week(), PROFILE, CATALOG) == []


def test_missing_meal_is_reported():
    meals = [m for m in full_week() if (m.day, m.meal) != ("Wed", 2)]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.MISSING_MEAL, day="Wed", meal=2)
    ]


def test_empty_week_reports_every_slot_missing():
    violations = validate_week([], PROFILE, CATALOG)

    assert violations == [
        Violation(ViolationKind.MISSING_MEAL, day=day, meal=meal)
        for day in WEEKDAYS
        for meal in MEAL_TIMES
    ]


def test_second_meal_in_the_same_slot_is_extra():
    meals = full_week() + [Meal(day="Fri", meal=3, itm_id=1)]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.EXTRA_MEAL, day="Fri", meal=3)
    ]


@pytest.mark.parametrize("day, meal", [("Funday", 1), ("Mon", 4), ("Mon", 0)])
def test_meal_outside_the_week_is_extra(day, meal):
    meals = full_week() + [Meal(day=day, meal=meal, itm_id=1)]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.EXTRA_MEAL, day=day, meal=meal)
    ]


def test_extra_meal_is_only_reported_as_extra():
    meals = full_week() + [Meal(day="Fri", meal=3, itm_id=999)]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.EXTRA_MEAL, day="Fri", meal=3)
    ]


def test_21_meals_with_one_slot_doubled_reports_both_extra_and_missing():
    meals = [m if (m.day, m.meal) != ("Sun", 1) else Meal("Sat", 1, 1) for m in full_week()]

    assert len(meals) == 21
    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.EXTRA_MEAL, day="Sat", meal=1),
        Violation(ViolationKind.MISSING_MEAL, day="Sun", meal=1),
    ]


def test_unknown_item_is_reported():
    # Not in the catalog: out of stock, from a closed restaurant, or made up by the planner.
    meals = [m if (m.day, m.meal) != ("Tue", 1) else Meal("Tue", 1, 999) for m in full_week()]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.UNKNOWN_ITEM, day="Tue", meal=1)
    ]


def test_violation_detail_is_not_part_of_equality():
    assert Violation(ViolationKind.UNKNOWN_ITEM, "Mon", 1, detail="a") == Violation(
        ViolationKind.UNKNOWN_ITEM, "Mon", 1, detail="b"
    )


@pytest.mark.parametrize(
    "price_cents, expected",
    [
        (1000, 1621),  # $10.00 + $0.725 tax rounded half up to $0.73 + $3.99 + $1.49
        (1299, 1941),  # $12.99 + $0.94 tax + fees
        (962, 1580),  # $9.62 + $0.70 tax + fees
        (963, 1581),  # $9.63 + $0.70 tax + fees
        (200, 763),  # $2.00 + $0.145 tax rounded half up to $0.15 + fees
        (1, 549),  # $0.01 + no tax + fees
    ],
)
def test_order_cost_adds_tax_and_both_fees_like_checkout(price_cents, expected):
    assert order_cost_cents(price_cents) == expected


def test_week_exactly_at_budget_passes():
    # 20 x $16.21 + $15.80 = $340.00
    meals = swap(full_week(), "Sun", 3, itm_id=2)

    assert validate_week(meals, with_budget(340), CATALOG) == []


def test_week_one_cent_over_budget_fails():
    # 20 x $16.21 + $15.81 = $340.01
    meals = swap(full_week(), "Sun", 3, itm_id=3)

    assert validate_week(meals, with_budget(340), CATALOG) == [Violation(ViolationKind.OVER_BUDGET)]


def test_over_budget_is_reported_even_with_meals_missing():
    # 20 x $16.21 = $324.20, already over a $324 budget without the missing meal.
    meals = [m for m in full_week() if (m.day, m.meal) != ("Sun", 3)]

    assert validate_week(meals, with_budget(324), CATALOG) == [
        Violation(ViolationKind.MISSING_MEAL, day="Sun", meal=3),
        Violation(ViolationKind.OVER_BUDGET),
    ]


def test_extra_meal_is_not_priced():
    # The week itself is exactly $340.00; pricing the extra $16.21 meal would put it over.
    meals = swap(full_week(), "Sun", 3, itm_id=2) + [Meal(day="Sun", meal=3, itm_id=1)]

    assert validate_week(meals, with_budget(340), CATALOG) == [
        Violation(ViolationKind.EXTRA_MEAL, day="Sun", meal=3)
    ]


@pytest.mark.parametrize(
    "budget_dollars, expected",
    [
        (324, [Violation(ViolationKind.UNKNOWN_ITEM, day="Sun", meal=2)]),
        (
            323,
            [
                Violation(ViolationKind.UNKNOWN_ITEM, day="Sun", meal=2),
                Violation(ViolationKind.OVER_BUDGET),
            ],
        ),
    ],
)
def test_budget_is_checked_on_the_known_meals_only(budget_dollars, expected):
    # 19 x $16.21 + $15.80 = $323.79 for the meals that can be priced.
    meals = swap(swap(full_week(), "Sun", 3, itm_id=2), "Sun", 2, itm_id=999)

    assert validate_week(meals, with_budget(budget_dollars), CATALOG) == expected
