"""Hard rule: every meal slot gets exactly one menu item."""

from planner.constraint import Constraint
from planner.registry import register


@register
class OneItemPerMeal(Constraint):
    """Exactly one item per (day, meal). Without it the solver would happily pick nothing."""

    name = "one_item_per_meal"
    summary = "Every meal gets exactly one menu item."
    order = 20

    def apply(self, ctx):
        for slot in ctx.slots:
            ctx.model.AddExactlyOne(var for _, var in ctx.picks(slot))
