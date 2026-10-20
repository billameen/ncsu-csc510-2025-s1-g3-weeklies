"""
Fees per order, with batching and pickup (M4): FeeCostConstraint.

Without this rule's options every meal is its own delivery order, as in M1: 21 meals pay 21
delivery fees and 21 service fees. With them:

- **Batching** (``batching=True``, off by default): meals on the same day from the same
  restaurant whose times are at most ``window_hours`` apart (default 6) are delivered as one
  order, paying one delivery fee and one service fee. Food is never held longer than the
  window, so with the app's meal times (10:00, 14:00, 20:00) breakfast + lunch or lunch +
  dinner can share an order, but not all three.
- **Pickup** (``pickup_restaurants`` and ``pickup_days``): an order from a restaurant the
  user opted into, on a day they opted into, is picked up: no delivery fee, service fee
  still charged. Both lists must match; opting into a restaurant alone does nothing.

Fees count toward the weekly budget and the cost the solver minimizes, because they are part
of ``ctx.cost_cents()`` (see PlanContext.set_fees). So batching can make a budget that M1
found impossible possible.

    PlanRequest(..., options={"fee_cost": {"batching": True,
                                           "pickup_restaurants": [3, 7],
                                           "pickup_days": ["Sat", "Sun"]}})
"""

from itertools import combinations

from planner.constraint import Constraint
from planner.menu import WEEKDAYS
from planner.registry import register

DEFAULT_WINDOW_HOURS = 6


def _minutes(hhmm: int) -> int:
    return (hhmm // 100) * 60 + hhmm % 100


def batch_groups(day_slots, window_hours: int = DEFAULT_WINDOW_HOURS):
    """
    Every group of two or more of one day's slots whose order times are at most window_hours
    apart, i.e. that can be delivered together without holding food longer than the window.
    """
    window = window_hours * 60
    ordered = sorted(day_slots, key=lambda s: s.time)
    groups = []
    for size in range(2, len(ordered) + 1):
        for group in combinations(ordered, size):
            if _minutes(group[-1].time) - _minutes(group[0].time) <= window:
                groups.append(group)
    return groups


@register
class FeeCostConstraint(Constraint):
    """Charge fees per order; optionally batch same-restaurant meals and use pickup."""

    name = "fee_cost"
    summary = "Fees are charged per order; batched or picked-up meals pay fewer fees."
    # After the item filters and daily calories, before anything that reads the whole plan's
    # cost (weekly_budget at 60, prefer_low_cost at 210).
    order = 55

    def __init__(self, batching: bool = False, pickup_restaurants=(), pickup_days=(),
                 window_hours: int = DEFAULT_WINDOW_HOURS):
        if not isinstance(batching, bool):
            raise ValueError(f"{self.name}: batching must be True or False, got {batching!r}")
        restaurants = tuple(pickup_restaurants or ())
        if any(not isinstance(r, int) or isinstance(r, bool) or r < 1 for r in restaurants):
            raise ValueError(f"{self.name}: pickup_restaurants must be restaurant ids, got {restaurants!r}")
        days = tuple(pickup_days or ())
        bad_days = [d for d in days if d not in WEEKDAYS]
        if bad_days:
            raise ValueError(f"{self.name}: pickup_days must be among {', '.join(WEEKDAYS)}, got {bad_days!r}")
        if not isinstance(window_hours, int) or isinstance(window_hours, bool) or not 1 <= window_hours <= 24:
            raise ValueError(f"{self.name}: window_hours must be a whole number from 1 to 24, got {window_hours!r}")
        self.batching = batching
        self.pickup_restaurants = frozenset(restaurants)
        self.pickup_days = frozenset(days)
        self.window_hours = window_hours

    def pickup(self, rtr_id: int, day) -> bool:
        """True if an order from rtr_id on day is picked up (the user opted into both)."""
        return rtr_id in self.pickup_restaurants and WEEKDAYS[day.weekday()] in self.pickup_days

    def order_fee_cents(self, ctx, rtr_id: int, day) -> int:
        """Fees for one order from rtr_id on day: no delivery fee if it is picked up."""
        return ctx.menu.fees.order_fee_cents(rtr_id, pickup=self.pickup(rtr_id, day))

    def apply(self, ctx):
        """
        fees = sum over meals of their own order's fee - the fees saved by every batch.
        A batch variable is 1 only if every meal in its group is picked from its restaurant,
        and each meal belongs to at most one batch.
        """
        model = ctx.model
        fees = sum(
            self.order_fee_cents(ctx, item.rtr_id, slot.day) * var
            for slot in ctx.slots
            for item, var in ctx.picks(slot)
        )
        batches = []  # (variable, rtr_id, day, slots)
        if self.batching:
            # slot index -> restaurant -> pick variables of that restaurant's items
            picks_by_restaurant = {}
            for slot in ctx.slots:
                by_rtr = picks_by_restaurant.setdefault(slot.index, {})
                for item, var in ctx.picks(slot):
                    by_rtr.setdefault(item.rtr_id, []).append(var)
            for day, day_slots in ctx.slots_by_day().items():
                for group in batch_groups(day_slots, self.window_hours):
                    shared = set.intersection(*(set(picks_by_restaurant[s.index]) for s in group))
                    for rtr_id in sorted(shared):
                        batch = model.NewBoolVar(
                            f"batch_d{day.toordinal()}_r{rtr_id}_s{group[0].index}_n{len(group)}"
                        )
                        for s in group:
                            model.Add(batch <= sum(picks_by_restaurant[s.index][rtr_id]))
                        batches.append((batch, rtr_id, day, group))
            for slot in ctx.slots:
                containing = [b for b, _, _, group in batches if slot in group]
                if len(containing) > 1:
                    model.Add(sum(containing) <= 1)
            fees -= sum(
                (len(group) - 1) * self.order_fee_cents(ctx, rtr_id, day) * batch
                for batch, rtr_id, day, group in batches
            )
        ctx.set_fees(self, fees, batches)

    def __repr__(self) -> str:
        return (f"FeeCostConstraint(batching={self.batching}, "
                f"pickup_restaurants={sorted(self.pickup_restaurants)}, "
                f"pickup_days={sorted(self.pickup_days, key=WEEKDAYS.index)}, "
                f"window_hours={self.window_hours})")
