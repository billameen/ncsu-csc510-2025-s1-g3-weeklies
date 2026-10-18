from dataclasses import replace
from datetime import date

import pytest

from eval.catalog import Catalog, Item, Restaurant
from eval.profiles import Profile
from eval.validate import (
    MEAL_TIMES,
    WEEK_START,
    WEEKDAYS,
    Meal,
    Violation,
    ViolationKind,
    normalize_allergen,
    order_cost_cents,
    validate_week,
)

OPEN_ALL_WEEK = {day: (600, 2300) for day in WEEKDAYS}


def every_day(*times):
    return {day: times for day in WEEKDAYS}


def item(itm_id, price_cents=1000, calories=700, allergens=(), rtr_id=1):
    return Item(
        itm_id=itm_id,
        rtr_id=rtr_id,
        price_cents=price_cents,
        calories=calories,
        allergens=allergens,
    )


# Per order: $10.00 costs $16.21, $9.62 costs $15.80 and $9.63 costs $15.81 (see the
# order_cost_cents cases below).
# Calories: two 700 kcal meals plus item 4, 5, 6 or 7 make 1890, 1889, 2310 or 2311 kcal: the
# edges of 2100 ± 10% and one past each.
# Allergens: items 9-14 carry raw tags as the menu data stores them.
# Hours: item 2N comes from restaurant N (see RESTAURANTS); meals are at 1000, 1400 and 2000.
CATALOG = Catalog(
    items={
        1: item(1),
        2: item(2, price_cents=962),
        3: item(3, price_cents=963),
        4: item(4, calories=490),
        5: item(5, calories=489),
        6: item(6, calories=910),
        7: item(7, calories=911),
        8: item(8, calories=1200),
        9: item(9, allergens=("Gluten", "Soy", "Egg")),
        10: item(10, allergens=("Peanuts",)),
        11: item(11, allergens=("Gluten", "Dairy")),
        12: item(12, allergens=(" dairy ",)),
        13: item(13, allergens=("Shellfish",)),
        14: item(14, allergens=("Egg", "Eggs")),
        **{20 + n: item(20 + n, rtr_id=n) for n in range(2, 11)},
        40: item(40, rtr_id=99),  # restaurant not in the catalog
        31: item(31, rtr_id=2, allergens=("Dairy",)),
    },
    restaurants={
        n: Restaurant(rtr_id=n, hours=hours)
        for n, hours in {
            1: OPEN_ALL_WEEK,
            2: {**OPEN_ALL_WEEK, "Mon": ()},  # closed Mondays
            3: every_day(1000, 2000),  # opens at breakfast, closes at dinner
            4: every_day(1100, 1400, 1700, 2100),  # lunch and dinner service only
            5: {},  # no hours
            6: {day: t for day, t in OPEN_ALL_WEEK.items() if day != "Mon"},  # no Mon entry
            7: {**OPEN_ALL_WEEK, "Mon": (600,)},  # unreadable on Mon: odd number of times
            8: every_day(1001, 2300),  # opens a minute after breakfast
            9: every_day(600, 1959),  # closes a minute before dinner
            10: every_day(600, 1300, 1500, 2300),  # closed 1300-1500, over lunch
        }.items()
    },
)

# 21 x item 1 costs $340.41, well under budget; 3 x 700 kcal hits the target exactly.
PROFILE = Profile(user_id=1, kcal_target=2100, budget_dollars=650, allergens=(), hard=False)


def full_week(itm_id=1):
    return [Meal(day=day, meal=meal, itm_id=itm_id) for day in WEEKDAYS for meal in MEAL_TIMES]


def with_budget(budget_dollars):
    return replace(PROFILE, budget_dollars=budget_dollars)


def with_kcal_target(kcal_target):
    return replace(PROFILE, kcal_target=kcal_target)


def with_allergens(*allergens):
    return replace(PROFILE, allergens=allergens)


def swap(meals, day, meal, itm_id):
    """Replace the item in one slot."""
    return [m if (m.day, m.meal) != (day, meal) else Meal(day, meal, itm_id) for m in meals]


def test_the_week_has_seven_days_of_three_meals():
    assert WEEKDAYS == ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    assert MEAL_TIMES == {1: 1000, 2: 1400, 3: 2000}


def test_the_week_starts_on_monday_2026_10_19():
    assert WEEK_START == date(2026, 10, 19)
    assert WEEK_START.weekday() == 0


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


@pytest.mark.parametrize(
    "itm_id, expected",
    [
        (4, []),  # 1890 kcal: exactly 10% under
        (5, [Violation(ViolationKind.UNDER_KCAL, day="Mon")]),  # 1889 kcal
        (6, []),  # 2310 kcal: exactly 10% over
        (7, [Violation(ViolationKind.OVER_KCAL, day="Mon")]),  # 2311 kcal
    ],
)
def test_daily_calories_must_be_within_ten_percent_edges_included(itm_id, expected):
    meals = swap(full_week(), "Mon", 3, itm_id=itm_id)

    assert validate_week(meals, PROFILE, CATALOG) == expected


@pytest.mark.parametrize(
    "kcal_target, kind",
    [(2400, ViolationKind.UNDER_KCAL), (1900, ViolationKind.OVER_KCAL)],
)
def test_calorie_band_comes_from_the_profile(kcal_target, kind):
    # 2100 kcal a day is under 2400 - 10% = 2160 and over 1900 + 10% = 2090.
    assert validate_week(full_week(), with_kcal_target(kcal_target), CATALOG) == [
        Violation(kind, day=day) for day in WEEKDAYS
    ]


def test_each_day_is_checked_on_its_own_in_week_order():
    meals = swap(swap(full_week(), "Sat", 1, itm_id=7), "Tue", 2, itm_id=5)

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.UNDER_KCAL, day="Tue"),
        Violation(ViolationKind.OVER_KCAL, day="Sat"),
    ]


def test_day_with_an_empty_slot_is_not_reported_as_under():
    # Mon has 1400 kcal, but the missing meal is the problem, not the calories.
    meals = [m for m in full_week() if (m.day, m.meal) != ("Mon", 3)]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.MISSING_MEAL, day="Mon", meal=3)
    ]


def test_day_with_an_unknown_item_is_not_reported_as_under():
    meals = swap(full_week(), "Mon", 3, itm_id=999)

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.UNKNOWN_ITEM, day="Mon", meal=3)
    ]


def test_day_with_an_empty_slot_is_still_reported_as_over():
    # 2 x 1200 kcal is already past 2310 without the missing meal.
    meals = [
        m
        for m in swap(swap(full_week(), "Mon", 1, 8), "Mon", 2, 8)
        if (m.day, m.meal) != ("Mon", 3)
    ]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.MISSING_MEAL, day="Mon", meal=3),
        Violation(ViolationKind.OVER_KCAL, day="Mon"),
    ]


def test_extra_meal_calories_are_not_counted():
    # Counting the extra 700 kcal would put Mon at 2800.
    meals = full_week() + [Meal(day="Mon", meal=1, itm_id=1)]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.EXTRA_MEAL, day="Mon", meal=1)
    ]


def test_calorie_problems_come_before_budget():
    # Mon at 1889 kcal, and 21 x $16.21 = $340.41 against a $340 budget.
    meals = swap(full_week(), "Mon", 3, itm_id=5)

    assert validate_week(meals, with_budget(340), CATALOG) == [
        Violation(ViolationKind.UNDER_KCAL, day="Mon"),
        Violation(ViolationKind.OVER_BUDGET),
    ]


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("Eggs", "eggs"),
        ("Egg", "eggs"),
        (" egg ", "eggs"),
        ("EGGS", "eggs"),
        ("Peanuts", "nuts"),
        ("Nuts", "nuts"),
        ("Shellfish", "shellfish"),
        ("  Dairy\t", "dairy"),
        ("Tree   Nuts", "tree nuts"),
        ("Sesame", "sesame"),
    ],
)
def test_normalize_allergen(tag, expected):
    assert normalize_allergen(tag) == expected


def test_meal_with_an_allergen_is_reported():
    meals = swap(full_week(), "Thu", 2, itm_id=11)

    assert validate_week(meals, with_allergens("Dairy"), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Thu", meal=2)
    ]


def test_item_tagged_egg_is_caught_for_a_user_avoiding_eggs():
    meals = swap(full_week(), "Mon", 1, itm_id=9)

    assert validate_week(meals, with_allergens("Eggs"), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Mon", meal=1)
    ]


def test_item_tagged_peanuts_is_caught_for_a_user_avoiding_nuts():
    meals = swap(full_week(), "Mon", 1, itm_id=10)

    assert validate_week(meals, with_allergens("Nuts"), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Mon", meal=1)
    ]


def test_tag_case_and_spacing_do_not_matter():
    meals = swap(full_week(), "Mon", 1, itm_id=12)

    assert validate_week(meals, with_allergens("Dairy"), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Mon", meal=1)
    ]


@pytest.mark.parametrize(
    "itm_id, allergens",
    [
        (11, ()),  # the user avoids nothing
        (11, ("Eggs", "Nuts")),  # the item has other allergens
        (13, ("Fish",)),  # whole tags only: "Shellfish" is not "Fish"
    ],
)
def test_allergens_the_user_does_not_avoid_are_fine(itm_id, allergens):
    meals = swap(full_week(), "Mon", 1, itm_id=itm_id)

    assert validate_week(meals, with_allergens(*allergens), CATALOG) == []


@pytest.mark.parametrize("user_allergen, itm_id", [(" egg", 9), ("PEANUTS", 10)])
def test_users_allergens_are_normalized_too(user_allergen, itm_id):
    meals = swap(full_week(), "Mon", 1, itm_id=itm_id)

    assert validate_week(meals, with_allergens(user_allergen), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Mon", meal=1)
    ]


def test_two_spellings_of_one_allergen_are_named_once():
    meals = swap(full_week(), "Mon", 1, itm_id=14)

    violations = validate_week(meals, with_allergens("Eggs"), CATALOG)

    assert violations == [Violation(ViolationKind.ALLERGEN, day="Mon", meal=1)]
    assert violations[0].detail == "item 14 contains eggs"


def test_item_with_several_of_the_users_allergens_is_one_violation():
    meals = swap(full_week(), "Mon", 1, itm_id=9)

    violations = validate_week(meals, with_allergens("Gluten", "Soy", "Eggs"), CATALOG)

    assert violations == [Violation(ViolationKind.ALLERGEN, day="Mon", meal=1)]
    assert violations[0].detail == "item 9 contains gluten, soy, eggs"


def test_allergen_problems_are_reported_in_meal_order():
    meals = swap(swap(full_week(), "Sun", 3, itm_id=11), "Tue", 1, itm_id=12)

    assert validate_week(meals, with_allergens("Dairy"), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Tue", meal=1),
        Violation(ViolationKind.ALLERGEN, day="Sun", meal=3),
    ]


def test_meal_with_an_allergen_still_counts_for_calories_and_budget():
    # Mon is 700 + 1200 + 700 = 2600 kcal and the week costs 21 x $16.21 = $340.41. Leaving out
    # the $10.00, 700 kcal Dairy meal would hide both: 1900 kcal and $324.20.
    meals = swap(swap(full_week(), "Mon", 1, itm_id=11), "Mon", 2, itm_id=8)

    assert validate_week(meals, replace(with_budget(340), allergens=("Dairy",)), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Mon", meal=1),
        Violation(ViolationKind.OVER_KCAL, day="Mon"),
        Violation(ViolationKind.OVER_BUDGET),
    ]


def test_restaurant_closed_that_weekday():
    assert validate_week(swap(full_week(), "Mon", 1, itm_id=22), PROFILE, CATALOG) == [
        Violation(ViolationKind.CLOSED_RESTAURANT, day="Mon", meal=1)
    ]
    assert validate_week(swap(full_week(), "Tue", 1, itm_id=22), PROFILE, CATALOG) == []


def test_opening_and_closing_minutes_count_as_open():
    meals = swap(swap(full_week(), "Mon", 1, itm_id=23), "Mon", 3, itm_id=23)

    assert validate_week(meals, PROFILE, CATALOG) == []


@pytest.mark.parametrize("itm_id, meal", [(28, 1), (29, 3)])
def test_a_minute_outside_opening_hours_is_closed(itm_id, meal):
    meals = swap(full_week(), "Mon", meal, itm_id=itm_id)

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.CLOSED_RESTAURANT, day="Mon", meal=meal)
    ]


def test_each_opening_window_counts():
    # Lunch-and-dinner restaurant: closed at breakfast, open at 1400 (end of the first window)
    # and at 2000 (inside the second).
    meals = [m if m.day != "Wed" else Meal("Wed", m.meal, 24) for m in full_week()]

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.CLOSED_RESTAURANT, day="Wed", meal=1)
    ]


def test_time_between_two_opening_windows_is_closed():
    assert validate_week(swap(full_week(), "Mon", 2, itm_id=30), PROFILE, CATALOG) == [
        Violation(ViolationKind.CLOSED_RESTAURANT, day="Mon", meal=2)
    ]


@pytest.mark.parametrize("itm_id", [25, 26, 27, 40])
def test_missing_or_unreadable_hours_count_as_closed(itm_id):
    # No hours at all, no Mon entry, an odd number of times, and a restaurant not in the catalog.
    meals = swap(full_week(), "Mon", 1, itm_id=itm_id)

    assert validate_week(meals, PROFILE, CATALOG) == [
        Violation(ViolationKind.CLOSED_RESTAURANT, day="Mon", meal=1)
    ]


def test_unreadable_hours_on_one_day_do_not_close_the_others():
    assert validate_week(swap(full_week(), "Tue", 1, itm_id=27), PROFILE, CATALOG) == []


def test_meal_with_an_allergen_at_a_closed_restaurant_reports_both():
    meals = swap(full_week(), "Mon", 1, itm_id=31)

    assert validate_week(meals, with_allergens("Dairy"), CATALOG) == [
        Violation(ViolationKind.ALLERGEN, day="Mon", meal=1),
        Violation(ViolationKind.CLOSED_RESTAURANT, day="Mon", meal=1),
    ]


def test_meal_at_a_closed_restaurant_still_counts_for_calories_and_budget():
    # Same numbers as the allergen case: leaving out the closed $10.00, 700 kcal meal would hide
    # 2600 kcal on Mon and the $340.41 week.
    meals = swap(swap(full_week(), "Mon", 1, itm_id=22), "Mon", 2, itm_id=8)

    assert validate_week(meals, with_budget(340), CATALOG) == [
        Violation(ViolationKind.CLOSED_RESTAURANT, day="Mon", meal=1),
        Violation(ViolationKind.OVER_KCAL, day="Mon"),
        Violation(ViolationKind.OVER_BUDGET),
    ]
