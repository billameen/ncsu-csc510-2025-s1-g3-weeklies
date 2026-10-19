"""Soft rule: prefer plans that do not repeat the same item."""

from planner.constraint import SoftConstraint
from planner.registry import register


@register
class PreferVariety(SoftConstraint):
    """
    Penalty for picking the same item more than once, rising with each repeat: the first
    repeat of an item costs weight, the second 2 x weight, and the third and every later one
    3 x weight. So an item picked 3 times costs 3 x weight in total and one picked 5 times
    costs 9 x weight. Rising costs make the solver spread repeats over several items instead
    of leaning on the single best-value one (a 700 kcal, $9 dish could otherwise fill a third
    of the week).

    The default weight, 600, means a first repeat is accepted only when it saves more than
    $6. On the M0 simulated users this gives a median of 20 distinct items a week (H2 target:
    14); a flat 600 per repeat gave 17, and a flat 300 gave 10.
    """

    name = "prefer_variety"
    summary = "Prefer plans that repeat items less."
    order = 220
    default_weight = 600
    ESCALATION_STEPS = 3  # the k-th repeat costs min(k, 3) x weight

    def apply(self, ctx):
        """Penalize each item's picks beyond the first, escalating per repeat."""
        uses: dict[int, list] = {}
        for slot in ctx.slots:
            for item, var in ctx.picks(slot):
                uses.setdefault(item.itm_id, []).append(var)
        for itm_id, picks in uses.items():
            # excess_k = max(0, times picked - k): each step adds weight for every pick past
            # the k-th, so the penalty is weight x (excess_1 + excess_2 + excess_3).
            for k in range(1, min(len(picks), self.ESCALATION_STEPS + 1)):
                excess = ctx.model.NewIntVar(0, len(picks) - k, f"excess_{itm_id}_{k}")
                ctx.model.Add(excess >= sum(picks) - k)
                ctx.add_penalty(self, excess)
