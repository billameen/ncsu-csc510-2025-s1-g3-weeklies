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
        """
        low <= calories picked on each day <= high. Also tells the solver, for each day, the
        cheapest combination that can meet the band (see `cheapest_day`): as a lower bound on
        that day's cost, which lets it prove at once that a budget is too low, and as a hint
        to start from, which finds a valid week quickly when the budget allows one.
        """
        low, high = calorie_band(ctx.request.daily_calorie_target)
        for slots in ctx.slots_by_day().values():
            total = ctx.calories(slots)
            ctx.model.Add(total >= low)
            ctx.model.Add(total <= high)
            cheapest = cheapest_day(slots, ctx, low, high)
            if cheapest is None:
                continue  # no combination meets the band; the model is infeasible as is
            cost, items = cheapest
            # Implied by the band and the filters applied so far, so it removes no plan.
            ctx.model.Add(ctx.cost_cents(slots) >= cost)
            for slot, item in zip(slots, items):
                ctx.model.AddHint(ctx.pick(slot, item), 1)

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


def cheapest_day(slots, ctx, low: int, high: int):
    """
    The cheapest way to fill slots (one day) with candidate items totalling low..high kcal.
    Exact dynamic programming over calorie totals: for each total keep only the cheapest way
    to reach it, which is enough because what can follow depends only on the total. Ties go
    to lower item ids, so the result is deterministic.
    Returns:
        (cost_cents, items in slot order), or None if no combination lands in the band.
    """
    reachable = {0: (0, ())}  # calories so far -> (cost, items)
    for slot in slots:
        options = {}  # calories -> cheapest candidate with that many
        for item in ctx.candidates(slot):
            best = options.get(item.calories)
            cost = ctx.meal_cost_cents(item)
            if best is None or (cost, item.itm_id) < (ctx.meal_cost_cents(best), best.itm_id):
                options[item.calories] = item
        extended = {}
        for total, (cost, items) in reachable.items():
            for calories, item in options.items():
                new_total = total + calories
                if new_total > high:
                    continue  # calories only add up, so this cannot come back into the band
                candidate = (cost + ctx.meal_cost_cents(item), items + (item,))
                if new_total not in extended or _key(candidate) < _key(extended[new_total]):
                    extended[new_total] = candidate
        reachable = extended
    in_band = [best for total, best in reachable.items() if total >= low]
    return min(in_band, key=_key) if in_band else None


def _key(option):
    cost, items = option
    return cost, tuple(i.itm_id for i in items)


def reachable_totals(options: list[set[int]]) -> set[int]:
    """Every total reachable by choosing one value from each set (empty if any set is)."""
    totals = {0}
    for values in options:
        totals = {t + v for t in totals for v in values}
    return totals
