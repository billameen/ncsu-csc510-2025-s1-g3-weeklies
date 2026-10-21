"""
`PlanContext`: the solver model for one plan, and the helpers rules use to add to it.

For every meal slot and menu item there is a 0/1 variable "pick this item for this slot".
Rules read and constrain those variables; they never build their own.

Cost: every meal costs its item price plus tax (``food_cost_cents``) plus fees. Fees are
charged per order (see planner.fees). Unless a fee rule says otherwise each meal is its own
delivery order; the fee_cost rule (planner.rules.fee_cost) replaces that, over the whole plan,
with the fees of fewer orders (batching) and pickup.
"""

import time
from collections.abc import Iterable, Sequence
from datetime import date

from ortools.sat.python import cp_model

from planner.constraint import Constraint, Kind
from planner.menu import Menu, MenuItem
from planner.request import PlanRequest, Slot


class PlanContext:
    """
    The model being built for one request.
    Attributes:
        request: What the user asked for.
        menu: Everything that could be picked.
        rules: Every rule in this plan, in the order they are applied.
        model: The CP-SAT model. Rules may add constraints to it directly.
        slots: The meals to plan, in order.
        deadline: time.monotonic() value after which explain() calls should give up.
    """

    def __init__(
        self,
        request: PlanRequest,
        menu: Menu,
        rules: Sequence[Constraint] = (),
        *,
        deadline: float | None = None,
    ):
        self.request = request
        self.menu = menu
        self.rules = tuple(rules)
        self.model = cp_model.CpModel()
        self.slots = request.slots()
        self.deadline = deadline if deadline is not None else time.monotonic() + 4.0
        self._pick = {
            (slot.index, itm_id): self.model.NewBoolVar(f"s{slot.index}_i{itm_id}")
            for slot in self.slots
            for itm_id in menu.items
        }
        self._blocked: dict[tuple[int, int], Constraint] = {}
        # Calories per day the plan aims for. Rules such as calorie_shift change single days
        # before daily_calories reads them.
        self.kcal_targets: dict[date, int] = {
            day: request.daily_calorie_target for day in request.dates()
        }
        # Slots pin_meals had to leave free because their pinned item is no longer allowed.
        self.unpinned: list[Slot] = []
        self._penalties: list[tuple[Constraint, cp_model.LinearExpr]] = []
        self._fee_rule: Constraint | None = None
        self._fees: cp_model.LinearExpr | None = None
        self._fee_batches: tuple = ()

    # --- reading the model ---------------------------------------------------------------

    def pick(self, slot: Slot, item: MenuItem) -> cp_model.IntVar:
        """The 0/1 variable that is 1 if item is picked for slot."""
        return self._pick[slot.index, item.itm_id]

    def candidates(self, slot: Slot) -> list[MenuItem]:
        """Items no rule has forbidden for slot so far, in id order."""
        return [i for i in self.menu.items.values() if (slot.index, i.itm_id) not in self._blocked]

    def picks(self, slot: Slot) -> list[tuple[MenuItem, cp_model.IntVar]]:
        """(item, variable) for each candidate of slot."""
        return [(item, self.pick(slot, item)) for item in self.candidates(slot)]

    def blocked_by(self, slot: Slot, item: MenuItem) -> Constraint | None:
        """The first rule that forbade item for slot, or None if it is still a candidate."""
        return self._blocked.get((slot.index, item.itm_id))

    def slots_by_day(self) -> dict[date, tuple[Slot, ...]]:
        """The slots grouped by day, days in order."""
        days: dict[date, list[Slot]] = {}
        for slot in self.slots:
            days.setdefault(slot.day, []).append(slot)
        return {day: tuple(slots) for day, slots in days.items()}

    def kcal_target(self, day: date) -> int:
        """The calorie target for one day: the request's, unless a rule adjusted it."""
        return self.kcal_targets.get(day, self.request.daily_calorie_target)

    def calories(self, slots: Iterable[Slot]) -> cp_model.LinearExpr:
        """Total calories picked over slots."""
        return sum(item.calories * var for slot in slots for item, var in self.picks(slot))

    def food_cost_cents(self, item: MenuItem) -> int:
        """The item's price plus tax, no fees."""
        return item.price_cents + self.menu.fees.tax_cents(item.price_cents)

    def meal_cost_cents(self, item: MenuItem) -> int:
        """The item ordered on its own for delivery: price, tax, and its restaurant's fees."""
        return self.food_cost_cents(item) + self.menu.fees.order_fee_cents(item.rtr_id)

    def cost_cents(self, slots: Iterable[Slot] | None = None) -> cp_model.LinearExpr:
        """
        Total cost picked over slots (default: all), tax and fees included.

        Over the whole plan this uses the fee rule's fees if one has set them (fewer orders
        through batching, pickup). Over a subset of slots, or with no fee rule, each meal is
        priced as its own delivery order, which is never less than what it really costs.
        """
        if slots is None and self._fees is not None:
            food = sum(
                self.food_cost_cents(item) * var for slot in self.slots for item, var in self.picks(slot)
            )
            return food + self._fees
        slots = self.slots if slots is None else slots
        return sum(self.meal_cost_cents(item) * var for slot in slots for item, var in self.picks(slot))

    @property
    def fee_rule(self) -> Constraint | None:
        """The rule that set the plan's fees with `set_fees`, if any."""
        return self._fee_rule

    # --- changing the model --------------------------------------------------------------

    def forbid(self, slot: Slot, item: MenuItem, rule: Constraint) -> None:
        """Never pick item for slot. The first rule to forbid a pair is remembered."""
        key = (slot.index, item.itm_id)
        if key not in self._blocked:
            self._blocked[key] = rule
            self.model.Add(self._pick[key] == 0)

    def set_fees(self, rule: Constraint, expr: cp_model.LinearExpr, batches=()) -> None:
        """
        Make expr the fees of the whole plan, replacing "every meal is its own delivery
        order". Only one rule may do this, and it must run before any rule that reads
        ``cost_cents()`` (the budget, prefer_low_cost).
        Args:
            rule: The rule setting the fees; it must provide ``pickup(rtr_id, day)``.
            expr: The plan's total fees in cents.
            batches: (variable, rtr_id, day, slots) for every possible batch: if the
                variable is 1, those slots are one order from rtr_id.
        """
        if self._fee_rule is not None:
            raise ValueError(f"{rule.name}: the fees were already set by {self._fee_rule.name}")
        self._fee_rule = rule
        self._fees = expr
        self._fee_batches = tuple(batches)

    @property
    def fee_batches(self) -> tuple:
        """The possible batches given to `set_fees` (empty if none or no fee rule)."""
        return self._fee_batches

    def add_penalty(self, rule: Constraint, expr: cp_model.LinearExpr) -> None:
        """Add rule.weight * expr to the cost the solver minimizes. Soft rules only."""
        if rule.kind is not Kind.SOFT:
            raise TypeError(f"{rule.name} is a hard rule; only soft rules add penalties")
        self._penalties.append((rule, expr))

    def objective(self) -> cp_model.LinearExpr:
        """The weighted sum of every penalty added so far (0 if none)."""
        return sum(rule.weight * expr for rule, expr in self._penalties)

    def time_left(self) -> float:
        """Seconds until the deadline, never negative."""
        return max(0.0, self.deadline - time.monotonic())
