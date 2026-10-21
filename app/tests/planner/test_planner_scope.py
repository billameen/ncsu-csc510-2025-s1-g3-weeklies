"""Meal scopes, and filters that apply only inside one."""

from datetime import date

import pytest
from menu_factory import MONDAY, item, menu, request

from planner.constraint import ScopedItemFilter
from planner.context import PlanContext
from planner.scope import EVERY_MEAL, MealScope

TUESDAY = date(2026, 10, 20)


class NoOddIds(ScopedItemFilter):
    name = "no_odd_ids_scoped_test"
    summary = "Skip odd ids inside the scope."
    blocked_reason = "have odd ids"

    def allows(self, item, slot, ctx):
        return item.itm_id % 2 == 0


def test_a_scope_covers_its_days_and_meals():
    scope = MealScope(days={TUESDAY}, meals={3})
    slots = PlanContext(request(days=2), menu([item(1)])).slots
    assert [(s.day.day, s.meal) for s in slots if scope.covers(s)] == [(20, 3)]
    assert all(EVERY_MEAL.covers(s) for s in slots)


@pytest.mark.parametrize(
    "scope, text",
    [
        (EVERY_MEAL, "every day"),
        (MealScope(days={TUESDAY}), "Tue Oct 20"),
        (
            MealScope(days={TUESDAY, MONDAY}, meals={2, 3}),
            "Mon Oct 19, Tue Oct 20 lunch and dinner",
        ),
        (MealScope(meals={3}), "every day dinner"),
    ],
)
def test_scopes_describe_themselves_for_messages(scope, text):
    assert scope.describe() == text


def test_unknown_meal_numbers_are_rejected():
    with pytest.raises(ValueError):
        MealScope(meals={4})


def test_a_scoped_filter_only_blocks_inside_its_scope():
    ctx = PlanContext(request(days=2), menu([item(1), item(2)]))
    NoOddIds(MealScope(days={TUESDAY}, meals={1})).apply(ctx)

    blocked = [(s.day.day, s.meal) for s in ctx.slots if len(ctx.candidates(s)) == 1]
    assert blocked == [(20, 1)]


def test_scoped_filters_are_off_unless_added():
    assert NoOddIds.enabled_by_default is False
    assert NoOddIds().scope is EVERY_MEAL
