"""
Re-plan only the meals an edit touches, and describe the change.

Every meal outside the edit is pinned to what is already planned (pin_meals), the edit's
rules are added to the plan's usual rules, and the solver re-plans what is left, preferring
to keep each edited meal as it is unless changing it serves the edit (prefer_current). The
solver still enforces every rule (allergens, opening hours, calories, budget), so an edit
can change which meals are picked but never break a rule.

If the edit cannot be met as asked, the closest option is planned instead: the edit's item
rules become strong preferences (prefer_edits) and the user is told how close it got.
"""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from planner.constraint import ScopedItemFilter
from planner.menu import Menu, MenuItem
from planner.registry import get, rules_for
from planner.request import PlanRequest, Slot
from planner.scope import MealScope
from planner.solver import DEFAULT_TIME_LIMIT_S, plan_week

PREVIEW = "preview"  # the edit as asked
CLOSEST = "closest"  # the edit could not be met; this is the nearest plan
IMPOSSIBLE = "impossible"  # not even a nearby plan exists


@dataclass(frozen=True)
class MealChange:
    """One meal that changes."""

    slot: Slot
    before: MenuItem | None
    after: MenuItem


@dataclass(frozen=True)
class EditPreview:
    """
    A proposed plan after an edit, not yet saved.
    Attributes:
        status: PREVIEW, CLOSEST or IMPOSSIBLE.
        changes: The meals that change, in slot order.
        entries: The whole window in User.generated_menu's format, to save on Accept.
        explanation: Why the edit could not be met as asked (CLOSEST, IMPOSSIBLE).
        replaced_unavailable: Unedited meals that had to change because their item can no
            longer be planned (out of stock, closed, a new allergy).
        met: For CLOSEST, how many of the edited meals meet the edit; total is `edited`.
    """

    status: str
    changes: tuple[MealChange, ...] = ()
    entries: tuple[str, ...] = ()
    cost_before_cents: int = 0
    cost_after_cents: int = 0
    kcal_before: dict = field(default_factory=dict)
    kcal_after: dict = field(default_factory=dict)
    explanation: str | None = None
    replaced_unavailable: tuple[Slot, ...] = ()
    met: int = 0
    edited: int = 0
    seconds: float = 0.0


def preview_edits(
    request: PlanRequest,
    menu: Menu,
    current: Mapping[tuple[date, int], int],
    edit_rules: Sequence,
    affected: Sequence[MealScope],
    *,
    time_limit_s: float = DEFAULT_TIME_LIMIT_S,
) -> EditPreview:
    """
    Plan the edit without saving it.
    Args:
        request: The plan window and the user's targets, allergens and preferences.
        menu: The current menu.
        current: The planned item per (date, meal) in the window. Missing slots are free.
        edit_rules: Rule plug-ins built from the edits (planner.edits.resolve.to_rule).
        affected: The meals each edit re-plans (planner.edits.resolve.affected_scope).
    """
    started = time.monotonic()
    slots = request.slots()
    edited = [s for s in slots if any(scope.covers(s) for scope in affected)]
    pins = {
        (s.day, s.meal): current[(s.day, s.meal)]
        for s in slots
        if s not in edited and (s.day, s.meal) in current
    }
    base = rules_for(request) + [get("pin_meals")(pins), get("prefer_current")(current)]

    result = plan_week(request, menu, rules=base + list(edit_rules), time_limit_s=time_limit_s)
    status, explanation = PREVIEW, None
    if not result.ok:
        explanation = result.explanation
        filters = [r for r in edit_rules if isinstance(r, ScopedItemFilter)]
        others = [r for r in edit_rules if not isinstance(r, ScopedItemFilter)]
        closest = None
        if filters:
            closest = plan_week(
                request,
                menu,
                rules=base + others + [get("prefer_edits")(filters)],
                time_limit_s=time_limit_s,
            )
        if closest is None or not closest.ok:
            return EditPreview(
                IMPOSSIBLE, explanation=explanation, seconds=time.monotonic() - started
            )
        result, status = closest, CLOSEST

    after = {(m.day, m.meal): m.item for m in result.meals}
    changes = tuple(
        MealChange(s, menu.items.get(current.get((s.day, s.meal))), after[(s.day, s.meal)])
        for s in slots
        if current.get((s.day, s.meal)) != after[(s.day, s.meal)].itm_id
    )
    met = sum(
        all(r.allows(after[(s.day, s.meal)], s, None) for r in edit_rules if _covers(r, s))
        for s in edited
    )
    before_items = [menu.items[i] for i in current.values() if i in menu.items]
    return EditPreview(
        status,
        changes=changes,
        entries=tuple(result.menu_entries()),
        cost_before_cents=sum(i.cost_cents for i in before_items),
        cost_after_cents=result.total_cost_cents,
        kcal_before=_kcal(current, menu),
        kcal_after=result.kcal_by_day(),
        explanation=explanation,
        replaced_unavailable=tuple(c.slot for c in changes if c.slot not in edited),
        met=met,
        edited=len(edited),
        seconds=time.monotonic() - started,
    )


def _covers(rule, slot) -> bool:
    return isinstance(rule, ScopedItemFilter) and rule.scope.covers(slot)


def _kcal(current, menu) -> dict:
    totals: dict = {}
    for (day, _), itm_id in current.items():
        if itm_id in menu.items:
            totals[day] = totals.get(day, 0) + menu.items[itm_id].calories
    return dict(sorted(totals.items()))
