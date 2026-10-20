"""
Whether a valid week exists for a user ("Feasible" in GitHub issue #5).

Exact, not a heuristic. Days are independent, since the budget is only a weekly sum, so the
cheapest valid week is the cheapest valid day seven times over. It uses the validator's rules
and no planner code, and a week only counts as feasible once validate_week accepts it.
"""

from eval.catalog import Catalog, Item
from eval.profiles import Profile
from eval.validate import (
    MEAL_TIMES,
    WEEKDAYS,
    Meal,
    allergens_found,
    is_open,
    kcal_band,
    order_cost_cents,
    validate_week,
)


def cheapest_week(profile: Profile, catalog: Catalog) -> tuple[Meal, ...] | None:
    """
    The cheapest week that meets every rule except the budget: each day within the calorie
    band, every item allergen-free and from a restaurant open at that meal.
    Returns:
        The meals, or None if some day has no such combination.
    """
    safe = [i for i in catalog.items.values() if not allergens_found(i, profile.allergens)]
    low, high = kcal_band(profile.kcal_target)
    week = []
    for day in WEEKDAYS:
        picks = _cheapest_day(safe, catalog, day, low, high)
        if picks is None:
            return None
        week.extend(Meal(day, meal, itm_id) for meal, itm_id in zip(MEAL_TIMES, picks))
    return tuple(week)


def is_feasible(profile: Profile, catalog: Catalog) -> bool:
    """True if a valid week exists: the cheapest one passes the validator, budget included."""
    week = cheapest_week(profile, catalog)
    return week is not None and not validate_week(week, profile, catalog)


def _cheapest_day(
    safe: list[Item], catalog: Catalog, day: str, low: int, high: int
) -> tuple[int, ...] | None:
    """Item ids, one per meal, of the cheapest day totalling low..high kcal, or None."""
    # Calorie total so far -> (cost in cents, item ids): the cheapest way to reach that total.
    # Keeping only the cheapest per total is exact, because which meals can still follow
    # depends only on the total.
    reachable = {0: (0, ())}
    for meal in MEAL_TIMES:
        options = {}  # calories -> (cost, item id) of the cheapest open item with that count
        for item in safe:
            if is_open(catalog, item, day, meal):
                cost = order_cost_cents(item.price_cents, item.rtr_id, catalog.fees)
                if item.calories not in options or cost < options[item.calories][0]:
                    options[item.calories] = (cost, item.itm_id)
        extended = {}
        for total, (cost, ids) in reachable.items():
            for calories, (item_cost, itm_id) in options.items():
                new_total = total + calories
                if new_total > high:  # calories only add up, so this cannot come back in range
                    continue
                new_cost = cost + item_cost
                if new_total not in extended or new_cost < extended[new_total][0]:
                    extended[new_total] = (new_cost, ids + (itm_id,))
        reachable = extended
    in_band = [best for total, best in reachable.items() if total >= low]
    return min(in_band)[1] if in_band else None
