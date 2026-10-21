"""Soft rule: an edit changes as few meals as it can."""

from planner.constraint import SoftConstraint
from planner.registry import register


@register
class PreferCurrent(SoftConstraint):
    """
    Each re-planned meal that ends up different from what was planned costs `weight`, so an
    edit only swaps meals it has to. Without this, "make Thursday vegetarian" could also swap
    a Thursday meal that was already vegetarian just to save a dollar or add variety. The
    default weight, 1000, is $10 a meal: more than cost or variety usually trade, less than
    meeting the edit itself (prefer_edits).
    """

    name = "prefer_current"
    summary = "Keep planned meals unless changing them is needed."
    order = 240
    enabled_by_default = False
    default_weight = 1000

    def __init__(self, current=None, weight=None):
        """current: {(date, meal number): itm_id} of the plan being edited."""
        super().__init__(weight)
        self.current = dict(current or {})

    def apply(self, ctx):
        """Penalize picking anything but the current item in each planned slot."""
        for slot in ctx.slots:
            planned = self.current.get((slot.day, slot.meal))
            if planned is None:
                continue
            changes = [var for item, var in ctx.picks(slot) if item.itm_id != planned]
            if changes:
                ctx.add_penalty(self, sum(changes))
