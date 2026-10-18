"""
Check a planned week against the definition of a valid week in GitHub issue #5.

This module is the spec. It deliberately does not import planner code (menu_generation or
eval.baselines), so a planner bug cannot also hide in the check that is meant to catch it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from eval.catalog import Catalog
from eval.profiles import Profile

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Meal number -> order time (HHMM). Numbered like the app's generated menus:
# 1 breakfast, 2 lunch, 3 dinner.
MEAL_TIMES = {1: 1000, 2: 1400, 3: 2000}


class ViolationKind(StrEnum):
    MISSING_MEAL = "missing_meal"
    EXTRA_MEAL = "extra_meal"
    UNKNOWN_ITEM = "unknown_item"


@dataclass(frozen=True)
class Meal:
    day: str  # one of WEEKDAYS
    meal: int  # a key of MEAL_TIMES
    itm_id: int


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    day: str | None = None
    meal: int | None = None
    # Human-readable explanation, left out of equality so tests compare what went wrong.
    detail: str = field(default="", compare=False)


def validate_week(meals: Sequence[Meal], profile: Profile, catalog: Catalog) -> list[Violation]:
    """
    Check a planned week.
    Args:
        meals: The planned meals, one per (day, meal) slot.
        profile: The user the week was planned for.
        catalog: In-stock items from open restaurants.
    Returns:
        list[Violation]: Empty if the week is valid. Meal-level problems come in the order the
        meals were given, then missing slots in week order.
    """
    violations = []
    filled = set()
    for m in meals:
        slot = (m.day, m.meal)
        if m.day not in WEEKDAYS or m.meal not in MEAL_TIMES or slot in filled:
            violations.append(
                Violation(ViolationKind.EXTRA_MEAL, m.day, m.meal, f"item {m.itm_id}")
            )
            continue
        filled.add(slot)
        if m.itm_id not in catalog.items:
            violations.append(
                Violation(
                    ViolationKind.UNKNOWN_ITEM,
                    m.day,
                    m.meal,
                    f"item {m.itm_id} is not an in-stock item from an open restaurant",
                )
            )

    violations.extend(
        Violation(ViolationKind.MISSING_MEAL, day, meal)
        for day in WEEKDAYS
        for meal in MEAL_TIMES
        if (day, meal) not in filled
    )
    return violations
