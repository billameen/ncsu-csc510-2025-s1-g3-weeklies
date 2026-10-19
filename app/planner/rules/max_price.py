"""Edit rule: items at or under a menu price, in some meals ("dinners under $10")."""

from planner.constraint import ScopedItemFilter
from planner.registry import register


@register
class MaxPrice(ScopedItemFilter):
    """
    Inside its scope, only items whose menu price is at most `max_price_cents`. The menu
    price is what users see and say ("under $10"); tax and fees still count toward the weekly
    budget as usual.
    """

    name = "max_price"
    summary = "Some meals must cost at most a set menu price."
    blocked_reason = "cost more than the price limit"

    def __init__(self, max_price_cents: int, scope=None):
        if not isinstance(max_price_cents, int) or max_price_cents <= 0:
            raise ValueError(f"{self.name}: price must be a positive number of cents")
        super().__init__(scope)
        self.max_price_cents = max_price_cents

    def allows(self, item, slot, ctx):
        """True if the item's menu price is within the limit."""
        return item.price_cents <= self.max_price_cents

    def describe_block(self, slot, ctx):
        """E.g. "cost more than $10.00"."""
        return f"cost more than ${self.max_price_cents / 100:.2f}"

    def __repr__(self) -> str:
        return f"MaxPrice({self.max_price_cents}, {self.scope.describe()!r})"
