import random
from pathlib import Path

import pytest

from eval.profiles import ALLERGENS, generate_profiles, profiles_to_json, user_seed

SNAPSHOT = Path(__file__).resolve().parents[3] / "eval" / "data" / "profiles_seed510.json"

SEEDS = [510, 1, 2]


def test_same_seed_gives_the_same_profiles():
    assert generate_profiles(510) == generate_profiles(510)


def test_different_seed_gives_different_profiles():
    assert generate_profiles(510) != generate_profiles(511)


def test_does_not_touch_the_global_random_state():
    random.seed(0)
    expected = random.random()

    random.seed(0)
    generate_profiles(510)

    assert random.random() == expected


@pytest.mark.parametrize("seed", SEEDS)
def test_group_sizes_and_user_ids(seed):
    profiles = generate_profiles(seed)

    assert [p.user_id for p in profiles] == list(range(1, 101))
    assert sum(p.hard for p in profiles) == 20


@pytest.mark.parametrize("seed", SEEDS)
def test_calories_and_budgets_are_within_their_group_ranges(seed):
    for p in generate_profiles(seed):
        kcal_range, budget_range = (
            ((2400, 3000), (350, 450)) if p.hard else ((1600, 3000), (300, 650))
        )
        assert kcal_range[0] <= p.kcal_target <= kcal_range[1]
        assert p.kcal_target % 50 == 0
        assert budget_range[0] <= p.budget_dollars <= budget_range[1]


@pytest.mark.parametrize("seed", SEEDS)
def test_allergens_are_distinct_listed_and_in_canonical_order(seed):
    for p in generate_profiles(seed):
        assert set(p.allergens) <= set(ALLERGENS)
        assert list(p.allergens) == sorted(p.allergens, key=ALLERGENS.index)
        assert len(set(p.allergens)) == len(p.allergens)


@pytest.mark.parametrize("seed", SEEDS)
def test_allergen_counts_per_group(seed):
    profiles = generate_profiles(seed)
    hard = [p for p in profiles if p.hard]
    regular = [p for p in profiles if not p.hard]

    assert all(len(p.allergens) in (2, 3) for p in hard)
    assert sum(not p.allergens for p in regular) == 40
    assert all(len(p.allergens) <= 3 for p in regular)


def test_the_seven_allergens():
    assert ALLERGENS == ("Gluten", "Dairy", "Eggs", "Soy", "Nuts", "Fish", "Shellfish")


def test_matches_the_committed_snapshot():
    assert SNAPSHOT.read_text() == profiles_to_json(generate_profiles(510)), (
        "Profiles for seed 510 changed. If that is intended, regenerate the snapshot with "
        "`python -m eval.profiles --seed 510 > eval/data/profiles_seed510.json`."
    )


def test_user_seed_is_stable_across_runs():
    # A fixed value catches implementations that use hash(), which is salted per process.
    assert user_seed(510, 1) == 2560661077026503355


def test_user_seed_differs_by_user_and_by_seed():
    seeds = {user_seed(s, u) for s in (510, 511) for u in range(1, 101)}

    assert len(seeds) == 200
