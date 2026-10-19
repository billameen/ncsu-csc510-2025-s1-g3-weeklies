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
        """Total delivered cost of all picks <= weekly_budget_cents."""
        ctx.model.Add(ctx.cost_cents() <= ctx.request.weekly_budget_cents)

    def explain(self, ctx):
        """
        The cost of the cheapest plan that meets every other hard rule, against the budget,
        e.g. "The cheapest week that meets your other requirements costs $212.40 ...". None
        if the other rules cannot be met either (then they explain), or if the cheapest
        cost could not be pinned down above the budget in time.
        """
        from planner.solver import cheapest_without  # the solver imports the rule registry

        budget = ctx.request.weekly_budget_cents
        cheapest = cheapest_without(ctx, self)
        if cheapest is None or cheapest.cost_cents <= budget:
            return None
        week = "week" if ctx.request.days == 7 else f"{ctx.request.days}-day plan"
        costs = "costs" if cheapest.proven else "costs at least"
        return (
            f"The cheapest {week} that meets your other requirements {costs} "
            f"${cheapest.cost_cents / 100:,.2f} with tax and fees; your weekly budget is "
            f"${budget / 100:,.2f}."
        )
