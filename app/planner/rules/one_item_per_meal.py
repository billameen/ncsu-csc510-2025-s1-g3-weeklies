"""Hard rule: every meal slot gets exactly one menu item."""

from collections import Counter

from planner.constraint import Constraint, ItemFilter
from planner.registry import register


@register
class OneItemPerMeal(Constraint):
    """
    Exactly one item per (day, meal). Without it the solver would happily pick nothing.

    Explains the most basic way a week is impossible: a meal for which every item has been
    ruled out. The explanation counts, for one such meal, how many items each filter rule
    blocked (out of stock, restaurant closed, allergens), so the user sees what to change.
    """

    name = "one_item_per_meal"
    summary = "Every meal gets exactly one menu item."
    order = 20

    def apply(self, ctx):
        """Exactly one pick per slot among the slot's candidates."""
        for slot in ctx.slots:
            ctx.model.AddExactlyOne(var for _, var in ctx.picks(slot))

    def explain(self, ctx):
        """Meals with no candidate left, and how many items each filter blocked."""
        if not ctx.menu.items:
            return "There are no menu items to plan with yet."
        empty = [slot for slot in ctx.slots if not ctx.candidates(slot)]
        if not empty:
            return None
        # One sentence per set of blockers: a meal blocked the same way on several days is
        # listed once with its days, and meals blocked the same way on the same days share
        # a sentence ("No breakfast or lunch can be planned on Mon ...").
        days_by_meal: dict[tuple, list] = {}
        for slot in empty:
            counts = Counter(ctx.blocked_by(slot, item) for item in ctx.menu.items.values())
            reasons = tuple(
                f"{n} {_reason(rule, slot, ctx)}"
                for rule, n in sorted(counts.items(), key=lambda kv: kv[0].order)
            )
            days_by_meal.setdefault((slot.meal, reasons), []).append(slot)
        meals_by_days: dict[tuple, list] = {}
        for (meal, reasons), slots in days_by_meal.items():
            key = (_days(slots, ctx), reasons)
            meals_by_days.setdefault(key, []).append(slots[0].meal_name)
        return " ".join(
            f"No {_join(meals, 'or')} can be planned {days}: of {len(ctx.menu.items)} menu "
            f"items, {_join(reasons)}."
            for (days, reasons), meals in meals_by_days.items()
        )


def _reason(rule, slot, ctx) -> str:
    if isinstance(rule, ItemFilter):
        return rule.describe_block(slot, ctx)
    return f"are ruled out by {rule.name}"


def _days(slots, ctx) -> str:
    all_days = len(ctx.slots_by_day())
    if len(slots) == all_days and all_days > 1:
        return "on any day"
    return "on " + ", ".join(f"{s.weekday} {s.day:%b} {s.day.day}" for s in slots)


def _join(parts, conjunction="and") -> str:
    parts = list(parts)
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {conjunction} {parts[-1]}"
