"""weekly_budget on its own: the plan's total cost with tax and fees fits the budget."""

import pytest
from menu_factory import item, menu, request

from planner.menu import meal_cost_cents
from planner.registry import get
from planner.solver import Status, plan_week

OneItemPerMeal, WeeklyBudget = get("one_item_per_meal"), get("weekly_budget")

CHEAP, PRICEY = item(1, price_cents=500), item(2, price_cents=2000)


def plan(items, budget_cents, **kw):
    return plan_week(
        request(budget_cents=budget_cents, **kw),
        menu(items),
        rules=[OneItemPerMeal(), WeeklyBudget()],
    )


def test_the_week_including_tax_and_fees_fits_the_budget():
    budget = 21 * meal_cost_cents(500) + 2 * (meal_cost_cents(2000) - meal_cost_cents(500))
    result = plan([CHEAP, PRICEY], budget, days=7)

    assert result.ok and result.total_cost_cents <= budget


@pytest.mark.parametrize("slack, feasible", [(0, True), (-1, False)])
def test_the_budget_edge_is_included(slack, feasible):
    exactly = 3 * meal_cost_cents(500)
    assert plan([CHEAP], exactly + slack).ok is feasible


def test_fees_count_toward_the_budget():
    # Three $5 items are $15 before tax and fees, but $32.52 delivered.
    result = plan([CHEAP], 1600)
    assert result.status is Status.INFEASIBLE
