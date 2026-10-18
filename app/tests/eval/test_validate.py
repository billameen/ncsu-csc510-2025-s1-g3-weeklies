import pytest

from eval.catalog import Catalog, Item, Restaurant
from eval.profiles import Profile
from eval.validate import MEAL_TIMES, WEEKDAYS, Meal, Violation, ViolationKind, validate_week

OPEN_ALL_WEEK = {day: (600, 2300) for day in WEEKDAYS}

CATALOG = Catalog(
    items={1: Item(itm_id=1, rtr_id=1, price_cents=1000, calories=700, allergens=())},
    restaurants={1: Restaurant(rtr_id=1, hours=OPEN_ALL_WEEK)},
)

# 21 x $10.00 meals cost $340.31 with tax and fees; 3 x 700 kcal hits the target exactly.
PROFILE = Profile(user_id=1, kcal_target=2100, budget_dollars=650, allergens=(), hard=False)


def full_week(itm_id=1):
    return [Meal(day=day, meal=meal, itm_id=itm_id) for day in WEEKDAYS for meal in MEAL_TIMES]


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
