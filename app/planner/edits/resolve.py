"""
Turn parsed edits into M1 rule plug-ins for one plan window.

Day words become the dates in the window that fall on those weekdays, meal words become meal
numbers, and dish or restaurant names become menu ids. A name that matches nothing raises
`Unresolvable` with a question for the user, rather than guessing.
"""

import re
from collections.abc import Sequence
from datetime import date

from planner.edits.schema import (
    MEAL_CODES,
    WEEKDAY_CODES,
    CalorieShift,
    ExcludeItem,
    ExcludeRestaurant,
    MaxPrice,
    RequireTag,
)
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


def find_items(menu: Menu, name: str):
    """
    Menu items a dish name refers to: an exact (case-insensitive) name match if there is
    one, otherwise every item whose name contains the phrase as whole words.
    """
    wanted = " ".join(name.lower().split())
    exact = [i for i in menu.items.values() if i.name.lower() == wanted]
    if exact:
        return exact
    pattern = re.compile(rf"\b{re.escape(wanted)}\b")
    return [i for i in menu.items.values() if pattern.search(i.name.lower())]


def find_restaurants(menu: Menu, name: str):
    """Restaurants a name refers to, matched the same way as dishes."""
    wanted = " ".join(name.lower().split())
    exact = [r for r in menu.restaurants.values() if r.name.lower() == wanted]
    if exact:
        return exact
    pattern = re.compile(rf"\b{re.escape(wanted)}\b")
    return [r for r in menu.restaurants.values() if pattern.search(r.name.lower())]


def to_rule(edit, window: Sequence[date], menu: Menu):
    """
    The M1 rule plug-in for one edit.
    Raises:
        Unresolvable: The edit names a dish, restaurant or day that cannot be found.
    """
    scope = resolve_scope(edit, window)
    if isinstance(edit, RequireTag):
        return get("require_tag")(edit.tag, scope)
    if isinstance(edit, MaxPrice):
        return get("max_price")(round(edit.max_price * 100), scope)
    if isinstance(edit, ExcludeItem):
        items = find_items(menu, edit.item)
        if not items:
            raise Unresolvable(
                f'I couldn\'t find "{edit.item}" on the menu. Which dish did you mean?'
            )
        return get("exclude_item")({i.itm_id for i in items}, edit.item, scope)
    if isinstance(edit, ExcludeRestaurant):
        found = find_restaurants(menu, edit.restaurant)
        if not found:
            raise Unresolvable(
                f'I couldn\'t find a restaurant called "{edit.restaurant}". Which one did you mean?'
            )
        return get("exclude_restaurant")({r.rtr_id for r in found}, edit.restaurant, scope)
    if isinstance(edit, CalorieShift):
        return get("calorie_shift")(edit.kcal_delta, scope.days)
    raise TypeError(f"unknown edit {edit!r}")  # pragma: no cover - the schema rules this out


def affected_scope(edit, window: Sequence[date]) -> MealScope:
    """The meals an edit re-plans. A calorie shift re-plans its whole days."""
    scope = resolve_scope(edit, window)
    return MealScope(days=scope.days) if isinstance(edit, CalorieShift) else scope
