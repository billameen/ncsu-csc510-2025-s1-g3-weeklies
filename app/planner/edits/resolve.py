"""
Turn parsed edits into M1 rule plug-ins for one plan window.

Day words become the dates in the window that fall on those weekdays, meal words become meal
numbers, and dish or restaurant names become menu ids (planner.match.Condition). A name that matches nothing raises
`Unresolvable` with a question for the user, rather than guessing.
"""

import re
from collections.abc import Sequence
from datetime import date

from planner.edits.schema import (
    MEAL_CODES,
    WEEKDAY_CODES,
    CalorieShift,
    DayLimit,
    Filter,
    Include,
    Prefer,
)
from planner.match import Condition
from planner.menu import Menu
from planner.registry import get
from planner.scope import MealScope


class Unresolvable(ValueError):
    """An edit names something the plan or menu does not have. The message is a question."""


def resolve_scope(edit, window: Sequence[date]) -> MealScope:
    """
    The meals of the window an edit covers.
    Raises:
        Unresolvable: None of the edit's days fall inside the window.
    """
    days = edit.day_codes()
    dates = frozenset(d for d in window if WEEKDAY_CODES[d.weekday()] in days)
    if not dates:
        raise Unresolvable(
            f"Your plan runs {window[0]:%a %b} {window[0].day} to {window[-1]:%a %b} "
            f"{window[-1].day}. Which of those days did you mean?"
        )
    meals = frozenset(MEAL_CODES.index(m) + 1 for m in edit.meal_codes())
    return MealScope(
        days=None if len(dates) == len(window) else dates,
        meals=None if len(meals) == len(MEAL_CODES) else meals,
    )


def _phrase_pattern(phrase: str) -> re.Pattern:
    """Whole words, the last one singular or plural: "burgers" matches "Burger" and "Burgers"."""
    words = phrase.lower().split()
    last = words[-1]
    if len(last) > 3 and last.endswith("s") and not last.endswith("ss"):
        last = last[:-1]
    body = r"\s+".join([*(re.escape(w) for w in words[:-1]), re.escape(last) + r"(?:e?s)?"])
    return re.compile(rf"\b{body}\b")


def find_items(menu: Menu, name: str):
    """
    Menu items a dish name or food word refers to: an exact (case-insensitive) name match if
    there is one ("Beef Ribs"), otherwise every item whose name or description contains the
    words, singular or plural ("pork", "burgers").
    """
    wanted = " ".join(name.lower().split())
    exact = [i for i in menu.items.values() if i.name.lower() == wanted]
    if exact:
        return exact
    pattern = _phrase_pattern(wanted)
    return [i for i in menu.items.values() if pattern.search(f"{i.name} {i.description}".lower())]


def find_restaurants(menu: Menu, name: str):
    """Restaurants a name refers to: an exact name match, otherwise whole words in the name."""
    wanted = " ".join(name.lower().split())
    exact = [r for r in menu.restaurants.values() if r.name.lower() == wanted]
    if exact:
        return exact
    pattern = _phrase_pattern(wanted)
    return [r for r in menu.restaurants.values() if pattern.search(r.name.lower())]


def to_condition(field: str, op: str, value, menu: Menu) -> Condition:
    """
    The planner.match.Condition for a parsed condition, with names matched to menu ids.
    Raises:
        Unresolvable: A dish or restaurant name matches nothing on the menu.
    """
    if field == "dish":
        items = find_items(menu, value)
        if not items:
            raise Unresolvable(f'I couldn\'t find "{value}" on the menu. Which dish did you mean?')
        return Condition(field, op, value, ids={i.itm_id for i in items})
    if field == "restaurant":
        found = find_restaurants(menu, value)
        if not found:
            raise Unresolvable(
                f'I couldn\'t find a restaurant called "{value}". Which one did you mean?'
            )
        return Condition(field, op, value, ids={r.rtr_id for r in found})
    if field == "price":
        return Condition(field, op, round(value * 100))
    return Condition(field, op, value)


def to_rule(edit, window: Sequence[date], menu: Menu):
    """
    The M1 rule plug-in for one edit.
    Raises:
        Unresolvable: The edit names a dish, restaurant or day that cannot be found.
    """
    scope = resolve_scope(edit, window)
    if isinstance(edit, Filter):
        return get("filter_meals")(to_condition(edit.field, edit.op, edit.value, menu), scope)
    if isinstance(edit, Include):
        condition = to_condition(edit.field, edit.op, edit.value, menu)
        return get("include_meals")(condition, scope, edit.times)
    if isinstance(edit, DayLimit):
        value = round(edit.value * 100) if edit.metric == "cost" else int(edit.value)
        return get("day_limit")(edit.metric, edit.op, value, scope.days)
    if isinstance(edit, Prefer):
        condition = (
            to_condition(edit.field, edit.op, edit.value, menu) if edit.goal == "match" else None
        )
        return get("prefer_meals")(edit.goal, scope, condition)
    if isinstance(edit, CalorieShift):
        return get("calorie_shift")(edit.kcal_delta, scope.days)
    raise TypeError(f"unknown edit {edit!r}")  # pragma: no cover - the schema rules this out


def affected_scope(edit, window: Sequence[date]) -> MealScope:
    """The meals an edit re-plans. Calorie shifts and daily limits re-plan whole days."""
    scope = resolve_scope(edit, window)
    whole_days = isinstance(edit, (CalorieShift, DayLimit))
    return MealScope(days=scope.days) if whole_days else scope
