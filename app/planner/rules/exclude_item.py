"""Edit rule: never plan certain items in some meals ("no Beef Ribs this week")."""

from planner.constraint import ScopedItemFilter
from planner.registry import register


@register
class ExcludeItem(ScopedItemFilter):
    """
    Inside its scope, never the items in `itm_ids`. Names are matched to ids before the rule
    is built (see planner.edits); `label` is the name the user used, for messages.
    """

    name = "exclude_item"
    summary = "Some meals must not be a given menu item."
    blocked_reason = "are excluded"

    def __init__(self, itm_ids, label: str, scope=None):
        itm_ids = frozenset(itm_ids)
        if not itm_ids:
            raise ValueError(f"{self.name}: no items to exclude")
        super().__init__(scope)
        self.itm_ids = itm_ids
        self.label = label

    def allows(self, item, slot, ctx):
        """True unless the item is one of the excluded ones."""
        return item.itm_id not in self.itm_ids

    def describe_block(self, slot, ctx):
        """E.g. "are excluded (Beef Ribs)"."""
        return f"are excluded ({self.label})"

    def __repr__(self) -> str:
        return f"ExcludeItem({sorted(self.itm_ids)}, {self.label!r}, {self.scope.describe()!r})"
