"""
Simulated users for the evaluation (spec: "Simulated users" in GitHub issue #5).

Regenerate the committed snapshot after an intended change with:
    python -m eval.profiles --seed 510 > eval/data/profiles_seed510.json
"""

import argparse
import hashlib
import json
import random
from dataclasses import asdict, dataclass

ALLERGENS = ("Gluten", "Dairy", "Eggs", "Soy", "Nuts", "Fish", "Shellfish")

KCAL_STEP = 50


@dataclass(frozen=True)
class Profile:
    user_id: int
    kcal_target: int  # per day
    budget_dollars: int  # per week, including tax and fees
    allergens: tuple[str, ...]  # in ALLERGENS order
    hard: bool


@dataclass(frozen=True)
class _Group:
    count: int
    kcal: tuple[int, int]  # inclusive ranges
    budget: tuple[int, int]
    allergen_count: tuple[int, int]
    hard: bool


GROUPS = (
    _Group(count=20, kcal=(2400, 3000), budget=(350, 450), allergen_count=(2, 3), hard=True),
    _Group(count=40, kcal=(1600, 3000), budget=(300, 650), allergen_count=(0, 0), hard=False),
    _Group(count=40, kcal=(1600, 3000), budget=(300, 650), allergen_count=(1, 3), hard=False),
)


def generate_profiles(seed: int) -> list[Profile]:
    """
    Generate the simulated users for a seed. Uses its own random.Random, so the global random
    state is left alone.
    Args:
        seed (int): Same seed, same profiles.
    Returns:
        list[Profile]: Users with ids 1..100, groups shuffled together.
    """
    rng = random.Random(seed)
    groups = [group for group in GROUPS for _ in range(group.count)]
    rng.shuffle(groups)
    return [_make_profile(rng, user_id, group) for user_id, group in enumerate(groups, start=1)]


def _make_profile(rng: random.Random, user_id: int, group: _Group) -> Profile:
    allergens = rng.sample(ALLERGENS, rng.randint(*group.allergen_count))
    return Profile(
        user_id=user_id,
        kcal_target=rng.randrange(group.kcal[0], group.kcal[1] + 1, KCAL_STEP),
        budget_dollars=rng.randint(*group.budget),
        allergens=tuple(sorted(allergens, key=ALLERGENS.index)),
        hard=group.hard,
    )


def user_seed(seed: int, user_id: int) -> int:
    """Seed for one user's random choices. Stable across runs and machines, unlike hash()."""
    digest = hashlib.sha256(f"{seed}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def profiles_to_json(profiles: list[Profile]) -> str:
    """Serialize profiles in the committed snapshot's format."""
    return json.dumps([asdict(p) for p in profiles], indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Print the simulated users as JSON.")
    parser.add_argument("--seed", type=int, default=510)
    args = parser.parse_args()
    print(profiles_to_json(generate_profiles(args.seed)), end="")


if __name__ == "__main__":
    main()
