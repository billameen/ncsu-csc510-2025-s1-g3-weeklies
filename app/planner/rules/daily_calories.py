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
