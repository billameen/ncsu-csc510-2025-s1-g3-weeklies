"""Edit rule: move some days' calorie target up or down ("lighter on the weekend")."""

from planner.constraint import Constraint
from planner.registry import register
from planner.targets import MAX_DAILY_KCAL, MIN_DAILY_KCAL

MAX_SHIFT_KCAL = 1000


@register
class CalorieShift(Constraint):
    """
    Adds `kcal_delta` to the calorie target of the days in `days` (None: every day), before
    daily_calories turns targets into bands. The shifted target is kept within the same
    bounds a profile allows, so a shift can never ask for a dangerous intake. If a shifted
    day cannot be met, daily_calories explains it as "your adjusted target".
    """

    name = "calorie_shift"
    summary = "Some days aim for more or fewer calories than the daily target."
    order = 45  # before daily_calories (50), which reads the targets
    enabled_by_default = False

    def __init__(self, kcal_delta: int, days=None):
        if (
            not isinstance(kcal_delta, int)
            or isinstance(kcal_delta, bool)
            or not 0 < abs(kcal_delta) <= MAX_SHIFT_KCAL
        ):
            raise ValueError(
                f"{self.name}: shift must be a non-zero whole number of calories up to "
                f"{MAX_SHIFT_KCAL} either way"
            )
        self.kcal_delta = kcal_delta
        self.days = None if days is None else frozenset(days)

    def apply(self, ctx):
        """Shift the covered days' targets, clamped to the profile bounds."""
        for day, target in ctx.kcal_targets.items():
            if self.days is None or day in self.days:
                ctx.kcal_targets[day] = min(
                    MAX_DAILY_KCAL, max(MIN_DAILY_KCAL, target + self.kcal_delta)
                )

    def __repr__(self) -> str:
        days = "every day" if self.days is None else sorted(d.isoformat() for d in self.days)
        return f"CalorieShift({self.kcal_delta:+d}, {days})"
