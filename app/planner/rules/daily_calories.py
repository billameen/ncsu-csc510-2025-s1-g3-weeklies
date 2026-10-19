"""Hard rule: each day's calories land within 10% of the user's daily target."""

from planner.constraint import Constraint
from planner.registry import register


def calorie_band(target: int) -> tuple[int, int]:
    """
    The whole-calorie range a day may total: within 10% of target, both ends included.
    Integer arithmetic, so a 2,105 kcal target gives 1,895..2,315 exactly (0.9 x 2105 is
    1894.5, rounded up).
    """
    return -(-9 * target // 10), 11 * target // 10


@register
class DailyCalories(Constraint):
    """Every planned day totals between 90% and 110% of request.daily_calorie_target."""

    name = "daily_calories"
    summary = "Each day's calories are within 10% of your daily target."
    order = 50

    def apply(self, ctx):
        low, high = calorie_band(ctx.request.daily_calorie_target)
        for slots in ctx.slots_by_day().values():
            total = ctx.calories(slots)
            ctx.model.Add(total >= low)
            ctx.model.Add(total <= high)

    def explain(self, ctx):
        """
        Days whose available items cannot add up to the band in any combination, with the
        closest total they can reach. Exact: it tries every calorie total the day's
        candidate items can make. Ignores other rules such as the budget, so a day it names
        is impossible however the rest of the week is planned.
        """
        target = ctx.request.daily_calorie_target
        low, high = calorie_band(target)
        closest_by_day = {}
        for day, slots in ctx.slots_by_day().items():
            options = [{item.calories for item in ctx.candidates(slot)} for slot in slots]
            if not all(options):
                continue  # an empty meal; one_item_per_meal explains that
            totals = reachable_totals(options)
            if not any(low <= t <= high for t in totals):
                closest_by_day[day] = min(
                    totals, key=lambda t: (min(abs(t - low), abs(t - high)), t)
                )
        if not closest_by_day:
            return None
        days_by_total: dict[int, list] = {}
        for day, total in closest_by_day.items():
            days_by_total.setdefault(total, []).append(day)
        all_days = len(closest_by_day) == len(ctx.slots_by_day()) > 1
        closest = "; ".join(
            f"{total:,} kcal "
            + ("on any day" if all_days and len(days_by_total) == 1 else "on " + _days(days))
            for total, days in days_by_total.items()
        )
        return (
            f"Your daily target of {target:,} kcal needs each day to total {low:,}-{high:,} kcal, "
            f"but no combination of the available meals gets there. The closest is {closest}."
        )


def _days(days) -> str:
    return ", ".join(f"{day:%a %b} {day.day}" for day in days)


def reachable_totals(options: list[set[int]]) -> set[int]:
    """Every total reachable by choosing one value from each set (empty if any set is)."""
    totals = {0}
    for values in options:
        totals = {t + v for t in totals for v in values}
    return totals
