"""
Check a planned week against the definition of a valid week in GitHub issue #5.

This module is the spec. It deliberately does not import planner code (menu_generation or
eval.baselines), so a planner bug cannot also hide in the check that is meant to catch it.
The one exception is the fee *data*, ``planner.fees``: what each restaurant charges is
configuration, not planning logic, and checkout reads the same numbers.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from planner.fees import DEFAULT_FEES, FeeSchedule

from eval.catalog import Catalog, Item
from eval.profiles import Profile

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# The planned week runs Mon-Sun from this Monday. Planners that work in dates use it.
WEEK_START = date(2026, 10, 19)

# Meal number -> order time (HHMM). Numbered like the app's generated menus:
# 1 breakfast, 2 lunch, 3 dinner.
MEAL_TIMES = {1: 1000, 2: 1400, 3: 2000}


# Different spellings of the same allergen in the menu data, after lowercasing.
_ALLERGEN_ALIASES = {"egg": "eggs", "peanuts": "nuts"}


class ViolationKind(StrEnum):
    MISSING_MEAL = "missing_meal"
    EXTRA_MEAL = "extra_meal"
    UNKNOWN_ITEM = "unknown_item"
    ALLERGEN = "allergen"
    CLOSED_RESTAURANT = "closed_restaurant"
    UNDER_KCAL = "under_kcal"
    OVER_KCAL = "over_kcal"
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
        meals were given, then missing slots in week order, then calorie problems by day, then
        the budget. Extra meals and unknown items are left out of every later check, so only
        problems the remaining meals prove are reported: a day missing a meal can still be
        over its calorie target, but not under it.
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
        item = catalog.items[m.itm_id]
        found = allergens_found(item, profile.allergens)
        if found:
            violations.append(
                Violation(
                    ViolationKind.ALLERGEN,
                    m.day,
                    m.meal,
                    f"item {m.itm_id} contains {', '.join(found)}",
                )
            )
        if not is_open(catalog, item, m.day, m.meal):
            violations.append(
                Violation(
                    ViolationKind.CLOSED_RESTAURANT,
                    m.day,
                    m.meal,
                    f"restaurant {item.rtr_id} is closed {m.day} at {MEAL_TIMES[m.meal]:04d}",
                )
            )
        placed.append(m)

    violations.extend(
        Violation(ViolationKind.MISSING_MEAL, day, meal)
        for day in WEEKDAYS
        for meal in MEAL_TIMES
        if (day, meal) not in filled
    )

    low, high = kcal_band(profile.kcal_target)
    for day in WEEKDAYS:
        day_meals = [m for m in placed if m.day == day]
        kcal = sum(catalog.items[m.itm_id].calories for m in day_meals)
        detail = f"{kcal} kcal, allowed {low}-{high}"
        if kcal > high:
            violations.append(Violation(ViolationKind.OVER_KCAL, day, detail=detail))
        elif kcal < low and len(day_meals) == len(MEAL_TIMES):
            violations.append(Violation(ViolationKind.UNDER_KCAL, day, detail=detail))

    week_cents = sum(
        order_cost_cents(catalog.items[m.itm_id].price_cents, catalog.items[m.itm_id].rtr_id,
                         catalog.fees)
        for m in placed
    )
    if week_cents > profile.budget_dollars * 100:
        violations.append(
            Violation(
                ViolationKind.OVER_BUDGET,
                detail=f"week costs ${week_cents / 100:.2f}, budget is ${profile.budget_dollars}",
            )
        )
    return violations


def kcal_band(target: int) -> tuple[int, int]:
    """
    The whole-calorie range a day may total: within 10% of the target, edges included. Computed
    in integers, so 0.9 x 2105 = 1894.5 gives 1895 exactly.
    """
    return -(-9 * target // 10), 11 * target // 10


def order_cost_cents(price_cents: int, rtr_id: int | None = None,
                     fees: FeeSchedule = DEFAULT_FEES) -> int:
    """
    Cost of one meal ordered on its own for delivery, the way checkout charges it: item price
    plus tax (rounded half up to the cent), the restaurant's delivery fee and service fee.
    No tip. Computed here from the fee data rather than by calling the planner's pricing.
    """
    tax_cents = (Decimal(price_cents) * fees.tax_rate).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    restaurant = fees.for_restaurant(rtr_id)
    return price_cents + int(tax_cents) + restaurant.delivery_fee_cents + restaurant.service_fee_cents


def normalize_allergen(tag: str) -> str:
    """
    Canonical form of an allergen tag: lowercase with whitespace collapsed, and the menu data's
    alternate spellings resolved ("Egg" is "eggs"; "Peanuts" count as "nuts").
    """
    tag = " ".join(tag.lower().split())
    return _ALLERGEN_ALIASES.get(tag, tag)


def allergens_found(item: Item, allergens: Iterable[str]) -> list[str]:
    """
    The given allergens that the item contains, normalized, deduplicated and in the item's tag
    order. Empty if the item is safe.
    """
    avoid = {normalize_allergen(a) for a in allergens}
    tags = (normalize_allergen(t) for t in item.allergens)
    return [t for t in dict.fromkeys(tags) if t in avoid]


def is_open(catalog: Catalog, item: Item, day: str, meal: int) -> bool:
    """
    True if the item's restaurant is open at the meal's time: the time falls inside one of the
    day's (open, close) pairs, both ends included. A restaurant missing from the catalog, or a
    day with no entry, no times, or an odd number of times (unreadable), is closed.
    """
    restaurant = catalog.restaurants.get(item.rtr_id)
    if restaurant is None:
        return False
    times = restaurant.hours.get(day, ())
    if len(times) % 2:
        return False
    time = MEAL_TIMES[meal]
    return any(times[i] <= time <= times[i + 1] for i in range(0, len(times), 2))
