"""Edit rule: never order from certain restaurants in some meals ("nothing from Sorella's")."""

from planner.constraint import ScopedItemFilter
from planner.registry import register


@register
class ExcludeRestaurant(ScopedItemFilter):
    """Inside its scope, never items from the restaurants in `rtr_ids`."""

    name = "exclude_restaurant"
    summary = "Some meals must not come from a given restaurant."
    blocked_reason = "come from an excluded restaurant"

    def __init__(self, rtr_ids, label: str, scope=None):
        rtr_ids = frozenset(rtr_ids)
        if not rtr_ids:
            raise ValueError(f"{self.name}: no restaurants to exclude")
        super().__init__(scope)
        self.rtr_ids = rtr_ids
        self.label = label

    def allows(self, item, slot, ctx):
        """True unless the item's restaurant is excluded."""
        return item.rtr_id not in self.rtr_ids

    def describe_block(self, slot, ctx):
        """E.g. "come from Sorella's, which you excluded"."""
        return f"come from {self.label}, which you excluded"

    def __repr__(self) -> str:
        return (
            f"ExcludeRestaurant({sorted(self.rtr_ids)}, {self.label!r}, "
            f"{self.scope.describe()!r})"
        )
