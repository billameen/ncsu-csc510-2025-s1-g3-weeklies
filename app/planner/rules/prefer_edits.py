"""Soft rule for the closest option when an edit is impossible as asked."""

from planner.constraint import SoftConstraint
from planner.registry import register


@register
class PreferEdits(SoftConstraint):
    """
    The soft version of a set of edit filters (filter_meals): each meal that breaks one of
    them costs `weight`. Used only when the edit cannot be met exactly, to find the plan that
    meets it in as many meals as possible. The default weight, 5000, is $50 a
    meal, far above what cost or variety trade, so the solver gives way on those first.
    """

    name = "prefer_edits"
    summary = "Meet a requested edit in as many meals as possible."
    order = 230
    enabled_by_default = False
    default_weight = 5000

    def __init__(self, filters=(), weight=None):
        super().__init__(weight)
        self.filters = tuple(filters)

    def apply(self, ctx):
        """Penalize each pick that one of the edit filters would have forbidden."""
        for rule in self.filters:
            for slot in ctx.slots:
                if rule.scope.covers(slot):
                    misses = [
                        var for item, var in ctx.picks(slot) if not rule.allows(item, slot, ctx)
                    ]
                    if misses:
                        ctx.add_penalty(self, sum(misses))
