"""
Hard rule (opt-in): order from any one restaurant at most N times a week.

This is the worked example in the tutorial "Add a planner rule in 15 minutes"
(app/docs/planner-rules.md). It is off unless a request asks for it:

    PlanRequest(..., options={"max_meals_per_restaurant": 3})
"""

from planner.constraint import Constraint
from planner.registry import register


@register
class MaxMealsPerRestaurant(Constraint):
    """At most `limit` meals of the plan come from the same restaurant."""

    name = "max_meals_per_restaurant"
    summary = "No restaurant supplies more than a set number of meals."
    order = 70
    enabled_by_default = False

    def __init__(self, limit: int = 3):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError(f"{self.name}: limit must be a whole number >= 1, got {limit!r}")
        self.limit = limit

    def apply(self, ctx):
        """Picks from each restaurant, over the whole plan, <= limit."""
        picks_by_restaurant: dict[int, list] = {}
        for slot in ctx.slots:
            for item, var in ctx.picks(slot):
                picks_by_restaurant.setdefault(item.rtr_id, []).append(var)
        for picks in picks_by_restaurant.values():
            ctx.model.Add(sum(picks) <= self.limit)

    def explain(self, ctx):
        """Blame the limit only if the plan works once the limit is lifted."""
        from planner.solver import cheapest_without

        # This rule is the reason only if the plan works once it is lifted.
        if cheapest_without(ctx, self) is None:
            return None
        meals = len(ctx.slots)
        restaurants = -(-meals // self.limit)  # ceil
        return (
            f"With at most {self.limit} meals from any one restaurant, the {meals} meals need "
            f"at least {restaurants} different restaurants that fit your other requirements, "
            f"and there are not enough. Allow more meals per restaurant."
        )

    def __repr__(self) -> str:
        return f"MaxMealsPerRestaurant(limit={self.limit})"
