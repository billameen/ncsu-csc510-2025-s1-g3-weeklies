"""Edit rule: every meal in a scope meets a condition ("make Thursday vegetarian")."""

from planner.constraint import ScopedItemFilter
from planner.match import Condition
from planner.registry import register


@register
class FilterMeals(ScopedItemFilter):
    """
    Inside its scope, only items that meet `condition` (see planner.match): a tag, a price or
    calorie bound, a dish or restaurant to avoid or stick to, an allergen to avoid.
    """

    name = "filter_meals"
    summary = "Some meals must meet a condition, such as vegetarian or $10 or less."
    blocked_reason = "do not meet the requested condition"

    def __init__(self, condition: Condition, scope=None):
        if not isinstance(condition, Condition):
            raise ValueError(f"{self.name}: needs a planner.match.Condition, got {condition!r}")
        super().__init__(scope)
        self.condition = condition

    def allows(self, item, slot, ctx):
        """True if the item meets the condition."""
        return self.condition.matches(item)

    def describe_block(self, slot, ctx):
        """E.g. "are not vegetarian", "are over $10.00"."""
        return f"are {self.condition.describe_miss()}"

    def __repr__(self) -> str:
        return f"FilterMeals({self.condition.describe()!r}, {self.scope.describe()!r})"
