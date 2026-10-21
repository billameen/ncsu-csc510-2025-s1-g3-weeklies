"""Plan-edit rule: keep the meals an edit does not touch exactly as they are."""

from planner.constraint import ItemFilter
from planner.registry import register


@register
class PinMeals(ItemFilter):
    """
    For each pinned slot, only the item already planned there may be picked, so an edit to
    Thursday re-plans Thursday and nothing else.

    If a pinned item can no longer be picked (it went out of stock, its restaurant changed
    its hours, or an allergy was added since), the slot is left free instead of making the
    whole edit impossible, and it is listed in `ctx.unpinned` so the change can be shown.
    Runs after the other item filters (order 10-14) so it can see that.
    """

    name = "pin_meals"
    summary = "Meals outside an edit stay as they are."
    blocked_reason = "are not the meal already planned"
    order = 15
    enabled_by_default = False

    def __init__(self, pins):
        """pins: {(date, meal number): itm_id} for the meals to keep."""
        self.pins = dict(pins)

    def allows(self, item, slot, ctx):
        """True for the pinned item (or any item in an unpinned slot)."""
        pinned = self.pins.get((slot.day, slot.meal))
        return pinned is None or item.itm_id == pinned

    def apply(self, ctx):
        """Pin each slot to its item, unless that item is no longer allowed there."""
        for slot in ctx.slots:
            pinned = self.pins.get((slot.day, slot.meal))
            if pinned is None:
                continue
            candidates = ctx.candidates(slot)
            if not any(item.itm_id == pinned for item in candidates):
                ctx.unpinned.append(slot)
                continue
            for item in candidates:
                if item.itm_id != pinned:
                    ctx.forbid(slot, item, self)

    def __repr__(self) -> str:
        return f"PinMeals({len(self.pins)} meals)"
