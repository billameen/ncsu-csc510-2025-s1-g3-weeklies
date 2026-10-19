"""Soft rule: prefer plans that do not repeat the same item."""

from planner.constraint import SoftConstraint
from planner.registry import register


@register
class PreferVariety(SoftConstraint):
    """
    Penalty of weight x number of repeats, where an item picked n times counts n - 1
    repeats. The default weight, 600, means a repeat is accepted only when it saves more
    than $6 (or is needed to meet a hard rule). It was tuned on the M0 simulated users to
    reach the H2 target of at least 14 distinct items a week.
    """

    name = "prefer_variety"
    summary = "Prefer plans that repeat items less."
    order = 220
    default_weight = 600

    def apply(self, ctx):
        uses: dict[int, list] = {}
        for slot in ctx.slots:
            for item, var in ctx.picks(slot):
                uses.setdefault(item.itm_id, []).append(var)
        for itm_id, picks in uses.items():
            if len(picks) < 2:
                continue  # can only be picked once: never a repeat
            repeats = ctx.model.NewIntVar(0, len(picks) - 1, f"repeats_{itm_id}")
            ctx.model.Add(repeats >= sum(picks) - 1)
            ctx.add_penalty(self, repeats)
