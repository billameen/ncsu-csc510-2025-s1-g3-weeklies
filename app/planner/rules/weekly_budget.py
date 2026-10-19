"""Hard rule: the whole plan, tax and fees included, fits the user's weekly budget."""

from planner.constraint import Constraint
from planner.registry import register


@register
class WeeklyBudget(Constraint):
    """
    The sum over every planned meal of item price + tax + delivery fee + service fee is at
    most request.weekly_budget_cents. Each meal is priced as its own delivery order, the way
    checkout charges it (see planner.menu.meal_cost_cents).
    """

    name = "weekly_budget"
    summary = "The whole plan, tax and fees included, fits your weekly budget."
    order = 60

    def apply(self, ctx):
        ctx.model.Add(ctx.cost_cents() <= ctx.request.weekly_budget_cents)
