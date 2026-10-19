"""Edit rule: some meals in a scope meet a condition ("pizza on Friday night")."""

from planner.constraint import Constraint, SoftConstraint
from planner.match import Condition
from planner.registry import register
from planner.scope import EVERY_MEAL

MAX_TIMES = 21


@register
class IncludeMeals(Constraint):
    """
    At least `times` of the meals in `scope` are items that meet `condition`. Unlike
    filter_meals, the other meals in the scope can be anything: "pizza sometime on Friday"
    needs one Friday meal to be pizza, not all three.
    """

    name = "include_meals"
    summary = "Some of the meals in a span must meet a condition, such as pizza on Friday."
    order = 70
    enabled_by_default = False

    def __init__(self, condition: Condition, scope=None, times: int = 1):
        if not isinstance(condition, Condition):
            raise ValueError(f"{self.name}: needs a planner.match.Condition, got {condition!r}")
        if not isinstance(times, int) or isinstance(times, bool) or not 1 <= times <= MAX_TIMES:
            raise ValueError(f"{self.name}: times must be 1 to {MAX_TIMES}, got {times!r}")
        self.condition = condition
        self.scope = scope or EVERY_MEAL
        self.times = times

    def _matching(self, ctx):
        return [
            var
            for slot in ctx.slots
            if self.scope.covers(slot)
            for item, var in ctx.picks(slot)
            if self.condition.matches(item)
        ]

    def apply(self, ctx):
        """Matching picks over the covered slots >= times."""
        matching = self._matching(ctx)
        ctx.model.Add(sum(matching) >= self.times if matching else ctx.model.NewConstant(0) >= 1)

    def explain(self, ctx):
        """Fewer covered meals have a matching item available than were asked for."""
        possible = sum(
            any(self.condition.matches(item) for item in ctx.candidates(slot))
            for slot in ctx.slots
            if self.scope.covers(slot)
        )
        if possible >= self.times:
            return None
        what = self.condition.describe()
        when = self.scope.describe()
        if possible == 0:
            return (
                f"No item that is {what} can be planned for {when}, given your allergies, "
                "opening hours, stock and your other requests."
            )
        return (
            f"Only {possible} of the meals on {when} can be {what}, given your allergies, "
            f"opening hours, stock and your other requests; you asked for {self.times}."
        )

    def soften(self):
        """Prefer as many matching meals as possible, up to `times`."""
        return PreferInclude(self)

    def unmet(self, plan):
        """E.g. 'No meal (Fri Oct 23 dinner) is "pizza"'."""
        hits = sum(
            self.condition.matches(item) for slot, item in plan.items() if self.scope.covers(slot)
        )
        if hits >= self.times:
            return None
        what = self.condition.describe()
        when = self.scope.describe()
        if hits == 0:
            return f"No meal ({when}) is {what}"
        return f"Only {hits} of the {self.times} meals you asked for ({when}) are {what}"

    def __repr__(self) -> str:
        return (
            f"IncludeMeals({self.condition.describe()!r}, {self.scope.describe()!r}, "
            f"times={self.times})"
        )


@register
class PreferInclude(SoftConstraint):
    """
    The soft version of include_meals, for the closest option when it cannot be met: each
    matching meal short of `times` costs `weight` ($50 by default, like prefer_edits).
    """

    name = "prefer_include"
    summary = "Include as many of the requested meals as possible."
    order = 231
    enabled_by_default = False
    default_weight = 5000

    def __init__(self, rule: IncludeMeals | None = None, weight=None):
        super().__init__(weight)
        if not isinstance(rule, IncludeMeals):
            raise ValueError(f"{self.name}: needs an include_meals rule, got {rule!r}")
        self.rule = rule

    def apply(self, ctx):
        """Penalize the shortfall: max(0, times - matching picks)."""
        matching = self.rule._matching(ctx)
        shortfall = ctx.model.NewIntVar(0, self.rule.times, f"include_short_{id(self)}")
        ctx.model.Add(shortfall >= self.rule.times - sum(matching))
        ctx.add_penalty(self, shortfall)
