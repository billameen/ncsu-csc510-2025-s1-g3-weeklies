"""Hard rule: only plan items that are in stock."""

from planner.constraint import ItemFilter
from planner.registry import register


@register
class InStock(ItemFilter):
    """Skip items whose MenuItem.instock is not 1."""

    name = "in_stock"
    summary = "Only in-stock items are planned."
    blocked_reason = "are out of stock"
    order = 10

    def allows(self, item, slot, ctx):
        return item.in_stock
