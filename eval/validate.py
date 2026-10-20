"""
Check a planned week against the definition of a valid week in GitHub issue #5.

This module is the spec. It deliberately does not import planner code (menu_generation or
eval.baselines), so a planner bug cannot also hide in the check that is meant to catch it.
The one exception is the fee *data*, ``planner.fees``: what each restaurant charges is
configuration, not planning logic, and checkout reads the same numbers.
"""

from collections import Counter
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
    # M4: problems with how the meals are grouped into orders.
    ORDER_MISMATCH = "order_mismatch"  # a meal in no order or in two, or an order of nothing
    MIXED_ORDER = "mixed_order"  # one order holds meals from different restaurants or days
    FOOD_SAFETY = "food_safety"  # meals in one order more than FOOD_SAFETY_HOURS apart
    PICKUP_NOT_OPTED = "pickup_not_opted"  # picked up without the user opting in


# M4: the longest food may wait between delivery and its meal. An order's meals must be at
# most this far apart, because the order arrives for the first one.
FOOD_SAFETY_HOURS = 6


@dataclass(frozen=True)
class Meal:
    day: str  # one of WEEKDAYS
    meal: int  # a key of MEAL_TIMES
    itm_id: int


@dataclass(frozen=True)
class Order:
    """M4: meals delivered (or picked up) together, as one order with one set of fees."""

    meals: tuple[Meal, ...]
    pickup: bool = False


@dataclass(frozen=True)
class PickupOptIn:
    """M4: where a user agreed to pick up: an order may be picked up only if both match."""

    restaurants: frozenset = frozenset()
    days: frozenset = frozenset()  # of WEEKDAYS

    def allows(self, rtr_id: int, day: str) -> bool:
        return rtr_id in self.restaurants and day in self.days


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    day: str | None = None
    meal: int | None = None
    # Human-readable explanation, left out of equality so tests compare what went wrong.
    detail: str = field(default="", compare=False)


def validate_week(
    meals: Sequence[Meal],
    profile: Profile,
    catalog: Catalog,
    orders: Sequence[Order] | None = None,
    pickup: PickupOptIn | None = None,
) -> list[Violation]:
    """
    Check a planned week.
    Args:
        meals: The planned meals, one per (day, meal) slot.
        profile: The user the week was planned for.
        catalog: In-stock items from open restaurants.
        orders: M4: how the meals are grouped into orders. None means every meal is its own
            delivery order (M0/M1). When given, the orders are checked (validate_orders) and
            the budget is checked against what those orders cost.
        pickup: M4: where the user opted into pickup (default: nowhere).
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

    if orders is not None:
        order_violations = validate_orders(meals, orders, catalog, pickup or PickupOptIn())
        violations.extend(order_violations)
    if orders is not None and not order_violations:
        week_cents = week_cost_cents(orders, catalog)
    else:
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


def validate_orders(
    meals: Sequence[Meal], orders: Sequence[Order], catalog: Catalog, pickup: PickupOptIn
) -> list[Violation]:
    """
    M4: check that the orders are a valid grouping of the meals: every meal in exactly one
    order; each order from one restaurant on one day; no order's meals more than
    FOOD_SAFETY_HOURS apart; pickup only where the user opted in. Meals with unknown items
    are left to validate_week.
    """
    violations = []
    expected = Counter((m.day, m.meal, m.itm_id) for m in meals)
    grouped = Counter((m.day, m.meal, m.itm_id) for o in orders for m in o.meals)
    for key in sorted((expected - grouped) + (grouped - expected)):
        day, meal, itm_id = key
        violations.append(Violation(ViolationKind.ORDER_MISMATCH, day, meal,
                                    f"item {itm_id} is in {grouped[key]} order(s), planned {expected[key]} time(s)"))
    for o in orders:
        if not o.meals:
            violations.append(Violation(ViolationKind.ORDER_MISMATCH, detail="an order with no meals"))
            continue
        known = [m for m in o.meals if m.itm_id in catalog.items]
        restaurants = {catalog.items[m.itm_id].rtr_id for m in known}
        days = {m.day for m in o.meals}
        first = o.meals[0]
        if len(restaurants) > 1 or len(days) > 1:
            violations.append(Violation(ViolationKind.MIXED_ORDER, first.day, first.meal,
                                        f"one order from restaurants {sorted(restaurants)} on {sorted(days)}"))
        minutes = [(MEAL_TIMES[m.meal] // 100) * 60 + MEAL_TIMES[m.meal] % 100
                   for m in o.meals if m.meal in MEAL_TIMES]
        if minutes and max(minutes) - min(minutes) > FOOD_SAFETY_HOURS * 60:
            violations.append(Violation(ViolationKind.FOOD_SAFETY, first.day, first.meal,
                                        f"meals {sorted(m.meal for m in o.meals)} are more than "
                                        f"{FOOD_SAFETY_HOURS} h apart in one order"))
        if o.pickup and not all(pickup.allows(r, d) for r in restaurants for d in days):
            violations.append(Violation(ViolationKind.PICKUP_NOT_OPTED, first.day, first.meal,
                                        f"picked up from {sorted(restaurants)} on {sorted(days)}"))
    return violations


def order_fee_cents(order: Order, catalog: Catalog) -> int:
    """M4: one order's fees: its restaurant's service fee, plus delivery unless picked up."""
    rtr_id = catalog.items[order.meals[0].itm_id].rtr_id
    fees = catalog.fees.for_restaurant(rtr_id)
    return fees.service_fee_cents + (0 if order.pickup else fees.delivery_fee_cents)


def week_cost_cents(orders: Sequence[Order], catalog: Catalog) -> int:
    """M4: what the orders cost: every item's price plus its tax, plus each order's fees."""
    food = 0
    for o in orders:
        for m in o.meals:
            price = catalog.items[m.itm_id].price_cents
            tax = (Decimal(price) * catalog.fees.tax_rate).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            food += price + int(tax)
    return food + sum(order_fee_cents(o, catalog) for o in orders)


def separate_fee_cents(meals: Sequence[Meal], catalog: Catalog) -> int:
    """M4: the fees if every meal were its own delivery order (the M1 way)."""
    return sum(order_fee_cents(Order((m,)), catalog) for m in meals)


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
