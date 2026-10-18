"""
Baseline planners the new planner is compared against (GitHub issue #5).

Every planner takes (profile, catalog, seed) and returns the planned meals, or None to answer
"no valid week".
"""

import random

from eval.catalog import Catalog
from eval.profiles import Profile, user_seed
from eval.validate import MEAL_TIMES, WEEKDAYS, Meal, allergens_found, is_open


def random_safe(profile: Profile, catalog: Catalog, seed: int) -> tuple[Meal, ...]:
    """
    B1: for each slot, a random in-stock, allergen-free item from a restaurant open at that
    meal. No LLM and no budget or calorie logic. It reuses the validator's allergen and hours
    checks: B1 is a reference point, not the planner under test, so its misses show what
    ignoring budget and calories costs. A slot with no such item is left empty.
    """
    rng = random.Random(user_seed(seed, profile.user_id))
    safe = [i for i in catalog.items.values() if not allergens_found(i, profile.allergens)]
    meals = []
    for day in WEEKDAYS:
        for meal in MEAL_TIMES:
            choices = [i for i in safe if is_open(catalog, i, day, meal)]
            if choices:
                meals.append(Meal(day, meal, rng.choice(choices).itm_id))
    return tuple(meals)
