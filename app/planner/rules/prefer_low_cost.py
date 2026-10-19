"""Soft rule: among valid plans, prefer cheaper ones."""

from planner.constraint import SoftConstraint
from planner.registry import register


@register
class PreferLowCost(SoftConstraint):
    """
    Penalty of weight x total cost in cents (tax and fees included). With the default
    weight of 1 this is the yardstick the other soft rules' weights are measured against.
    """

    name = "prefer_low_cost"
    summary = "Prefer cheaper plans."
    order = 210
    default_weight = 1

    def apply(self, ctx):
        """Penalize the total delivered cost, in cents."""
        ctx.add_penalty(self, ctx.cost_cents())
