import itertools
import random
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from eval.catalog import Catalog, Item, Restaurant, load_catalog
from eval.feasibility import cheapest_week, is_feasible
from eval.profiles import ALLERGENS, Profile, generate_profiles
from eval.validate import (
    MEAL_TIMES,
    WEEKDAYS,
    ViolationKind,
    allergens_found,
    is_open,
    kcal_band,
    order_cost_cents,
    validate_week,
)

SEED_SQL = Path(__file__).resolve().parents[2] / "db" / "seed.sql"

OPEN_ALL_WEEK = {day: (600, 2300) for day in WEEKDAYS}


def item(itm_id, price_cents, calories, allergens=(), rtr_id=1):
    return Item(
        itm_id=itm_id,
        rtr_id=rtr_id,
        price_cents=price_cents,
        calories=calories,
        allergens=allergens,
    )


def week_cost(meals, catalog):
    return sum(order_cost_cents(catalog.items[m.itm_id].price_cents) for m in meals)


def brute_force_cost(profile, catalog):
    """The cheapest valid-calorie week by trying every combination, or None."""
    low, high = kcal_band(profile.kcal_target)
    total = 0
    for day in WEEKDAYS:
        slots = [
            [
                i
                for i in catalog.items.values()
                if not allergens_found(i, profile.allergens) and is_open(catalog, i, day, meal)
            ]
            for meal in MEAL_TIMES
        ]
        costs = [
            sum(order_cost_cents(i.price_cents) for i in combo)
            for combo in itertools.product(*slots)
            if low <= sum(i.calories for i in combo) <= high
        ]
        if not costs:
            return None
        total += min(costs)
    return total


# Target 2100 kcal allows 1890-2310 a day. The three cheapest items make only 900 kcal; the
# cheapest valid day is 800 + 800 + 300 kcal: 2 x $11.92 + $8.70 = $32.54 per order total.
CATALOG = Catalog(
    items={
        1: item(1, 500, 500),
        2: item(2, 600, 800),
        3: item(3, 2000, 1000),
        4: item(4, 300, 300),
    },
    restaurants={1: Restaurant(rtr_id=1, hours=OPEN_ALL_WEEK)},
)

PROFILE = Profile(user_id=1, kcal_target=2100, budget_dollars=650, allergens=(), hard=False)


def test_finds_the_cheapest_valid_week_not_the_cheapest_items():
    week = cheapest_week(PROFILE, CATALOG)

    assert week_cost(week, CATALOG) == 7 * 3254
    assert validate_week(week, PROFILE, CATALOG) == []


def test_the_hand_computed_example_agrees_with_brute_force():
    assert brute_force_cost(PROFILE, CATALOG) == 7 * 3254


@pytest.mark.parametrize("budget_dollars, feasible", [(228, True), (227, False)])
def test_feasible_only_if_the_cheapest_week_fits_the_budget(budget_dollars, feasible):
    # The cheapest week costs $227.78.
    profile = replace(PROFILE, budget_dollars=budget_dollars)

    assert is_feasible(profile, CATALOG) is feasible


def test_an_unreachable_calorie_target_has_no_week():
    # Three 1000 kcal items make at most 3000, below 4000 - 10% = 3600.
    profile = replace(PROFILE, kcal_target=4000)

    assert cheapest_week(profile, CATALOG) is None
    assert not is_feasible(profile, CATALOG)


def test_avoids_allergens_and_closed_restaurants_even_when_cheaper():
    catalog = Catalog(
        items={
            **CATALOG.items,
            5: item(5, 100, 800, allergens=("Dairy",)),  # cheapest 800 kcal, but Dairy
            6: item(6, 100, 300, rtr_id=2),  # cheapest 300 kcal, but closed all day Mon
        },
        restaurants={
            1: Restaurant(rtr_id=1, hours=OPEN_ALL_WEEK),
            2: Restaurant(rtr_id=2, hours={**OPEN_ALL_WEEK, "Mon": ()}),
        },
    )
    profile = replace(PROFILE, allergens=("Dairy",))

    week = cheapest_week(profile, catalog)

    assert 5 not in {m.itm_id for m in week}
    assert 6 not in {m.itm_id for m in week if m.day == "Mon"}
    assert 6 in {m.itm_id for m in week if m.day == "Tue"}
    assert validate_week(week, profile, catalog) == []
    assert week_cost(week, catalog) == brute_force_cost(profile, catalog)


def test_a_day_with_nothing_open_has_no_week():
    catalog = replace(
        CATALOG, restaurants={1: Restaurant(rtr_id=1, hours={**OPEN_ALL_WEEK, "Sun": ()})}
    )

    assert cheapest_week(PROFILE, catalog) is None


HOURS_CHOICES = [
    OPEN_ALL_WEEK,
    {day: (1100, 2300) for day in WEEKDAYS},  # no breakfast
    {day: (600, 1300, 1500, 2300) for day in WEEKDAYS},  # no lunch
    {**OPEN_ALL_WEEK, "Sun": ()},  # closed Sundays
]


@pytest.mark.parametrize("case", range(40))
def test_matches_brute_force_on_random_small_menus(case):
    rng = random.Random(case)
    catalog = Catalog(
        items={
            n: item(
                n,
                price_cents=rng.randrange(200, 2001),
                calories=rng.randrange(100, 1201, 10),
                allergens=tuple(rng.sample(ALLERGENS[:3], rng.randint(0, 1))),
                rtr_id=rng.randint(1, 3),
            )
            for n in range(1, 9)
        },
        restaurants={r: Restaurant(rtr_id=r, hours=rng.choice(HOURS_CHOICES)) for r in range(1, 4)},
    )
    profile = Profile(
        user_id=1,
        kcal_target=rng.randrange(1600, 3001, 50),
        budget_dollars=650,
        allergens=tuple(rng.sample(ALLERGENS[:3], rng.randint(0, 2))),
        hard=False,
    )

    week = cheapest_week(profile, catalog)
    expected = brute_force_cost(profile, catalog)

    if expected is None:
        assert week is None
    else:
        assert week_cost(week, catalog) == expected
        kinds = {v.kind for v in validate_week(week, profile, catalog)}
        assert kinds <= {ViolationKind.OVER_BUDGET}


def test_on_the_seed_data_feasible_means_the_validator_accepts_the_cheapest_week(tmp_path):
    db = tmp_path / "seed.db"
    conn = sqlite3.connect(db)
    conn.executescript(SEED_SQL.read_text())
    conn.close()
    catalog = load_catalog(db)

    for profile in generate_profiles(510):
        week = cheapest_week(profile, catalog)
        violations = [] if week is None else validate_week(week, profile, catalog)
        assert {v.kind for v in violations} <= {ViolationKind.OVER_BUDGET}
        assert is_feasible(profile, catalog) is (week is not None and not violations)
