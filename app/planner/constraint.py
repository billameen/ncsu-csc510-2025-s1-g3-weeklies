"""
The plug-in interface for planner rules.

A rule is a class with two methods:

- ``apply(ctx)`` adds the rule to the solver model held by ``ctx`` (a `PlanContext`).
- ``explain(ctx)`` returns the sentence shown to the user when a week cannot be planned
  because of this rule, or None if this rule is not the reason.

Hard rules must hold in every plan (no allergens, stay within budget). Soft rules are
preferences the solver trades off against each other (variety, lower cost); they add a
weighted penalty instead of a constraint. Most rules subclass one of the two helpers:

- `ItemFilter` for "this item can never be picked for this meal": implement ``allows``.
- `SoftConstraint` for a penalty: call ``ctx.add_penalty`` in ``apply``.

Register a rule with ``@register`` from `planner.registry`; the tutorial in
``app/docs/planner-rules.md`` walks through writing one.
"""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:  # imported for type hints only, so loading a rule never loads OR-Tools
    from planner.context import PlanContext
    from planner.menu import MenuItem
    from planner.request import PlanRequest, Slot
    from planner.scope import MealScope


class Kind(StrEnum):
    """Whether a plan may break the rule."""

    HARD = "hard"  # never: a plan that breaks it is not a plan
    SOFT = "soft"  # at a cost: the solver weighs it against other soft rules


class Constraint(ABC):
    """
    Base class for every planner rule.
    Class attributes (checked by `planner.registry.register`):
        name: Unique snake_case id, also the key for this rule in PlanRequest.options.
        kind: Kind.HARD or Kind.SOFT.
        summary: One line saying what the rule does, for docs and error messages.
        order: Rules are applied in ascending order. ItemFilters come first (10-19) so later
            rules only see items that can still be picked.
        enabled_by_default: Whether plans use the rule when the request does not mention it.
    """

    name: ClassVar[str] = ""
    kind: ClassVar[Kind] = Kind.HARD
    summary: ClassVar[str] = ""
    order: ClassVar[int] = 100
    enabled_by_default: ClassVar[bool] = True

    @classmethod
    def from_request(cls, request: "PlanRequest") -> "Constraint | None":
        """
        The rule configured for a request, or None if the request does not use it. Reads
        ``request.options[cls.name]``: missing means the default, False turns the rule off,
        True turns it on, a dict is passed as keyword arguments and anything else as the
        single argument (e.g. ``{"max_meals_per_restaurant": 3}``).
        """
        option = request.options.get(cls.name)
        if option is None:
            return cls() if cls.enabled_by_default else None
        if option is False:
            return None
        if option is True:
            return cls()
        if isinstance(option, dict):
            return cls(**option)
        return cls(option)

    @abstractmethod
    def apply(self, ctx: "PlanContext") -> None:
        """Add this rule to ``ctx.model``, using the helpers on ``ctx``."""

    def explain(self, ctx: "PlanContext") -> str | None:
        """
        Why no week can be planned, if this rule is the reason. Called only after the solver
        proved the full model infeasible, on the same ``ctx``. Return None when this rule is
        not (or not provably) the cause, so another rule's explanation is shown instead.
        """
        return None

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class ItemFilter(Constraint):
    """
    A hard rule that rules out (item, meal slot) pairs one at a time, e.g. "no allergens".
    Subclasses implement ``allows`` and set ``blocked_reason``; ``apply`` is done for them.
    When some meal is left with no item at all, the planner explains it by counting how many
    items each filter blocked, using ``blocked_reason``.
    """

    kind: ClassVar[Kind] = Kind.HARD
    order: ClassVar[int] = 10
    # Completes "<n> items ...", e.g. "are out of stock".
    blocked_reason: ClassVar[str] = ""

    @abstractmethod
    def allows(self, item: "MenuItem", slot: "Slot", ctx: "PlanContext") -> bool:
        """True if the item may be picked for the slot."""

    def describe_block(self, slot: "Slot", ctx: "PlanContext") -> str:
        """
        Completes "<n> items ..." when explaining an empty meal. Defaults to
        ``blocked_reason``; override it to mention the slot or the request (e.g. which time
        the restaurants are closed at, or which allergens).
        """
        return self.blocked_reason

    def apply(self, ctx: "PlanContext") -> None:
        """Forbid every (slot, item) pair that `allows` rejects."""
        for slot in ctx.slots:
            for item in ctx.candidates(slot):
                if not self.allows(item, slot, ctx):
                    ctx.forbid(slot, item, self)


class ScopedItemFilter(ItemFilter):
    """
    An ItemFilter that only applies to some meals, e.g. "vegetarian on Thursday". Plan edits
    are built from these. ``allows`` is asked only for slots inside ``scope``; every other
    meal is left alone. Off by default: they exist to be added to a plan, not configured.
    """

    order: ClassVar[int] = 14
    enabled_by_default: ClassVar[bool] = False

    def __init__(self, scope: "MealScope | None" = None):
        from planner.scope import EVERY_MEAL

        self.scope = scope or EVERY_MEAL

    def apply(self, ctx: "PlanContext") -> None:
        """Forbid what `allows` rejects, in the slots the scope covers."""
        for slot in ctx.slots:
            if self.scope.covers(slot):
                for item in ctx.candidates(slot):
                    if not self.allows(item, slot, ctx):
                        ctx.forbid(slot, item, self)

    # Plan edits use the two methods below: `soften` when the edit cannot be met exactly (to
    # plan the closest option instead) and `unmet` to say what that option misses.

    def soften(self) -> "Constraint":
        """The preference version of this filter: each meal that breaks it costs a penalty."""
        from planner.registry import get  # the registry imports this module

        return get("prefer_edits")([self])

    def unmet(self, plan) -> str | None:
        """
        What a plan misses of this filter, e.g. "2 of 3 meals (Thu Oct 22) are not vegan".
        Args:
            plan: {slot: picked MenuItem} for every slot of the plan.
        """
        covered = [slot for slot in plan if self.scope.covers(slot)]
        misses = [slot for slot in covered if not self.allows(plan[slot], slot, None)]
        if not misses:
            return None
        return (
            f"{len(misses)} of {len(covered)} meals ({self.scope.describe()}) "
            f"{self.describe_block(misses[0], None)}"
        )


class SoftConstraint(Constraint):
    """
    A preference. ``apply`` calls ``ctx.add_penalty(self, expr)``; the solver minimizes the sum
    of every soft rule's ``weight * expr``. Penalties are in "cents-equivalent" units so they
    compare with PreferLowCost, which charges 1 per cent spent: a weight of 600 on "one more
    repeat" means a repeat is worth avoiding if it saves less than $6.
    """

    kind: ClassVar[Kind] = Kind.SOFT
    order: ClassVar[int] = 200
    default_weight: ClassVar[int] = 1

    def __init__(self, weight: int | None = None):
        weight = self.default_weight if weight is None else weight
        if not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
            raise ValueError(f"{self.name}: weight must be a whole number >= 0, got {weight!r}")
        self.weight = weight

    def __repr__(self) -> str:
        return f"{type(self).__name__}(weight={self.weight})"
