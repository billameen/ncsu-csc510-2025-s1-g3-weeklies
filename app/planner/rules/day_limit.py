"""Edit rule: a cap or floor on each day's cost or calories ("keep each day under $40")."""

from planner.constraint import Constraint, SoftConstraint
from planner.registry import register
from planner.rules.daily_calories import calorie_band, cheapest_day

METRICS = ("cost", "calories")
OPS = ("<=", ">=")


@register
class DayLimit(Constraint):
    """
    On each day in `days` (None: every day), the total `metric` is at most (op "<=") or at
    least (op ">=") `value`. Cost is in cents with tax and fees, like the weekly budget, which
    still applies on top: a daily limit can only make a plan stricter.
    """

    name = "day_limit"
    summary = "Each day's cost or calories stays under (or over) a limit."
    order = 55  # after daily_calories (50), whose bands explain() compares against
    enabled_by_default = False

    def __init__(self, metric: str, op: str, value: int, days=None):
        if metric not in METRICS:
            raise ValueError(f"{self.name}: metric must be one of {METRICS}, got {metric!r}")
        if op not in OPS:
            raise ValueError(f"{self.name}: op must be one of {OPS}, got {op!r}")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{self.name}: value must be a positive whole number, got {value!r}")
        self.metric, self.op, self.value = metric, op, value
        self.days = None if days is None else frozenset(days)

    def _covered(self, ctx):
        return {
            day: slots
            for day, slots in ctx.slots_by_day().items()
            if self.days is None or day in self.days
        }

    def _total(self, ctx, slots):
        return ctx.cost_cents(slots) if self.metric == "cost" else ctx.calories(slots)

    def apply(self, ctx):
        """Bound the total of each covered day."""
        for slots in self._covered(ctx).values():
            total = self._total(ctx, slots)
            ctx.model.Add(total <= self.value if self.op == "<=" else total >= self.value)

    def _amount(self, value: int) -> str:
        return f"${value / 100:,.2f}" if self.metric == "cost" else f"{value:,} kcal"

    def explain(self, ctx):
        """
        A day whose limit cannot be met whatever else is planned: a cost cap below the
        cheapest day that meets its calorie target, or a calorie limit outside that target's
        band. None otherwise (the limit may still conflict with other requests; those
        rules, or the fallback, explain it).
        """
        limit = self._amount(self.value)
        if self.metric == "cost" and self.op == "<=":
            cheapest = []
            for day, slots in self._covered(ctx).items():
                found = cheapest_day(slots, ctx, *calorie_band(ctx.kcal_target(day)))
                if found is not None and found[0] > self.value:
                    cheapest.append(found[0])
            if cheapest:
                return (
                    f"The cheapest day that meets your calorie target costs "
                    f"{self._amount(min(cheapest))} with tax and fees; you asked for at most "
                    f"{limit} a day."
                )
            return None
        if self.metric == "calories":
            for day in self._covered(ctx):
                target = ctx.kcal_target(day)
                low, high = calorie_band(target)
                if self.op == "<=" and self.value < low:
                    return (
                        f"Your calorie target of {target:,} kcal needs at least {low:,} kcal a "
                        f"day, more than the {limit} you asked for."
                    )
                if self.op == ">=" and self.value > high:
                    return (
                        f"Your calorie target of {target:,} kcal allows at most {high:,} kcal a "
                        f"day, less than the {limit} you asked for."
                    )
        return None

    def soften(self):
        """Prefer days as close to the limit as possible."""
        return PreferDayLimit(self)

    def unmet(self, plan):
        """E.g. "Mon Oct 19 costs $24.10", or "Every day costs $42.18", against the limit."""
        totals: dict = {}
        for slot, item in plan.items():
            if self.days is None or slot.day in self.days:
                amount = item.cost_cents if self.metric == "cost" else item.calories
                totals[slot.day] = totals.get(slot.day, 0) + amount
        missed = {
            day: total
            for day, total in sorted(totals.items())
            if (total > self.value if self.op == "<=" else total < self.value)
        }
        if not missed:
            return None
        by_total: dict[int, list] = {}
        for day, total in missed.items():
            by_total.setdefault(total, []).append(day)
        every = len(missed) == len(totals) > 1 and len(by_total) == 1
        parts = []
        for total, days in by_total.items():
            one = every or len(days) == 1
            if self.metric == "cost":
                verb = "costs" if one else "cost"
            else:
                verb = "has" if one else "have"
            who = "Every day" if every else ", ".join(f"{d:%a %b} {d.day}" for d in days)
            parts.append(f"{who} {verb} {self._amount(total)}")
        bound = "at most" if self.op == "<=" else "at least"
        return f"{'; '.join(parts)} (you asked for {bound} {self._amount(self.value)} a day)"

    def __repr__(self) -> str:
        days = "every day" if self.days is None else sorted(d.isoformat() for d in self.days)
        return f"DayLimit({self.metric} {self.op} {self.value}, {days})"


@register
class PreferDayLimit(SoftConstraint):
    """
    The soft version of day_limit, for the closest option when it cannot be met: each cent
    (or calorie) past the limit costs `weight`. The default, 50, makes a dollar (or 100
    kcal) over the limit cost as much as a meal that misses an item edit (prefer_edits, 5000).
    """

    name = "prefer_day_limit"
    summary = "Keep each day as close to a requested limit as possible."
    order = 232
    enabled_by_default = False
    default_weight = 50

    def __init__(self, rule: DayLimit | None = None, weight=None):
        super().__init__(weight)
        if not isinstance(rule, DayLimit):
            raise ValueError(f"{self.name}: needs a day_limit rule, got {rule!r}")
        self.rule = rule

    def apply(self, ctx):
        """Penalize how far each covered day is past the limit."""
        rule = self.rule
        for day, slots in rule._covered(ctx).items():
            total = rule._total(ctx, slots)
            excess = ctx.model.NewIntVar(0, 10**7, f"day_excess_{day.isoformat()}_{id(self)}")
            ctx.model.Add(excess >= (total - rule.value if rule.op == "<=" else rule.value - total))
            ctx.add_penalty(self, excess)
