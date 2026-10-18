"""
Check a planned week against the definition of a valid week in GitHub issue #5.

This module is the spec. It deliberately does not import planner code (menu_generation or
eval.baselines), so a planner bug cannot also hide in the check that is meant to catch it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pricing import DELIVERY_FEE, SERVICE_FEE, TAX_RATE

from eval.catalog import Catalog
from eval.profiles import Profile

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Meal number -> order time (HHMM). Numbered like the app's generated menus:
# 1 breakfast, 2 lunch, 3 dinner.
MEAL_TIMES = {1: 1000, 2: 1400, 3: 2000}

# Exact decimal copies of the dollar constants; e.g. int(4.35 * 100) is 434 in floating point.
_TAX_RATE = Decimal(str(TAX_RATE))
_FEES_CENTS = int(Decimal(str(DELIVERY_FEE)) * 100 + Decimal(str(SERVICE_FEE)) * 100)


class ViolationKind(StrEnum):
    MISSING_MEAL = "missing_meal"
    EXTRA_MEAL = "extra_meal"
    UNKNOWN_ITEM = "unknown_item"
    OVER_BUDGET = "over_budget"


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
        meals were given, then missing slots in week order, then week-level problems. Extra
        meals and unknown items are left out of every later check.
    """
    violations = []
    filled = set()
    placed = []  # meals in a valid slot with a known item
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
            continue
        placed.append(m)

    violations.extend(
        Violation(ViolationKind.MISSING_MEAL, day, meal)
        for day in WEEKDAYS
        for meal in MEAL_TIMES
        if (day, meal) not in filled
    )

    week_cents = sum(order_cost_cents(catalog.items[m.itm_id].price_cents) for m in placed)
    if week_cents > profile.budget_dollars * 100:
        violations.append(
            Violation(
                ViolationKind.OVER_BUDGET,
                detail=f"week costs ${week_cents / 100:.2f}, budget is ${profile.budget_dollars}",
            )
        )
    return violations


def order_cost_cents(price_cents: int) -> int:
    """
    Cost of one meal ordered on its own for delivery, the way checkout charges it: item price
    plus tax (rounded half up to the cent), the delivery fee and the service fee. No tip.
    """
    tax_cents = (price_cents * _TAX_RATE).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return price_cents + int(tax_cents) + _FEES_CENTS
