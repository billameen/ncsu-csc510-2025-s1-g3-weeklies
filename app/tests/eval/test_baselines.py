import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from eval.baselines import random_safe
from eval.catalog import Catalog, Item, Restaurant, load_catalog
from eval.profiles import Profile, generate_profiles
from eval.validate import MEAL_TIMES, WEEKDAYS, ViolationKind, validate_week

SEED_SQL = Path(__file__).resolve().parents[2] / "db" / "seed.sql"

OPEN_ALL_WEEK = {day: (600, 2300) for day in WEEKDAYS}

# B1 knows nothing about money or calories, so only these may go wrong in its weeks.
BUDGET_OR_CALORIES = {ViolationKind.OVER_BUDGET, ViolationKind.UNDER_KCAL, ViolationKind.OVER_KCAL}


def item(itm_id, rtr_id=1, allergens=()):
    return Item(itm_id=itm_id, rtr_id=rtr_id, price_cents=1000, calories=700, allergens=allergens)


# Items 1-20 are safe and always open. Item 21 has an allergen, item 22 is tagged "Egg", item 23
# comes from a restaurant closed all week and item 24 from one missing from the catalog.
CATALOG = Catalog(
    items={
        **{n: item(n) for n in range(1, 21)},
        21: item(21, allergens=("Dairy",)),
        22: item(22, allergens=("Egg",)),
        23: item(23, rtr_id=2),
        24: item(24, rtr_id=99),
    },
    restaurants={
        1: Restaurant(rtr_id=1, hours=OPEN_ALL_WEEK),
        2: Restaurant(rtr_id=2, hours={}),
    },
)

PROFILE = Profile(
    user_id=1, kcal_target=2100, budget_dollars=650, allergens=("Dairy", "Eggs"), hard=False
)


def test_plans_one_meal_per_slot_in_week_order():
    meals = random_safe(PROFILE, CATALOG, seed=510)

    assert [(m.day, m.meal) for m in meals] == [(d, n) for d in WEEKDAYS for n in MEAL_TIMES]


def test_same_seed_gives_the_same_week():
    assert random_safe(PROFILE, CATALOG, seed=510) == random_safe(PROFILE, CATALOG, seed=510)


def test_different_seeds_and_different_users_give_different_weeks():
    week = random_safe(PROFILE, CATALOG, seed=510)
    other_user = replace(PROFILE, user_id=2)  # same needs, so only the id can change the week

    assert random_safe(PROFILE, CATALOG, seed=511) != week
    assert random_safe(other_user, CATALOG, seed=510) != week


def test_picks_at_random_among_the_safe_open_items():
    picked = {m.itm_id for seed in range(10) for m in random_safe(PROFILE, CATALOG, seed=seed)}

    assert picked == set(range(1, 21))


@pytest.mark.parametrize("seed", range(20))
def test_never_picks_an_allergen_or_a_closed_restaurant(seed):
    meals = random_safe(PROFILE, CATALOG, seed=seed)

    assert {m.itm_id for m in meals}.isdisjoint({21, 22, 23, 24})
    assert validate_week(meals, PROFILE, CATALOG) == []


def test_slot_with_no_safe_open_item_is_left_empty():
    # The only restaurant opens at 1100, after breakfast.
    late = Catalog(
        items={1: item(1)},
        restaurants={1: Restaurant(rtr_id=1, hours={d: (1100, 2300) for d in WEEKDAYS})},
    )

    meals = random_safe(PROFILE, late, seed=510)

    assert [(m.day, m.meal) for m in meals] == [(d, n) for d in WEEKDAYS for n in (2, 3)]
    kinds = {v.kind for v in validate_week(meals, PROFILE, late)}
    assert kinds == {ViolationKind.MISSING_MEAL}


def test_on_the_seed_data_only_budget_calories_or_empty_slots_go_wrong(tmp_path):
    db = tmp_path / "seed.db"
    conn = sqlite3.connect(db)
    conn.executescript(SEED_SQL.read_text())
    conn.close()
    catalog = load_catalog(db)

    for profile in generate_profiles(510):
        violations = validate_week(random_safe(profile, catalog, seed=510), profile, catalog)
        assert {v.kind for v in violations} <= BUDGET_OR_CALORIES | {ViolationKind.MISSING_MEAL}
