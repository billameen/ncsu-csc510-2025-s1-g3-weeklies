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


def test_a_budget_that_is_too_low_names_the_cheapest_valid_week():
    result = plan([CHEAP, PRICEY], 15_000, days=7)

    cheapest = 21 * meal_cost_cents(500)
    assert result.explanation == (
        f"The cheapest week that meets your other requirements costs ${cheapest / 100:,.2f} "
        "with tax and fees; your weekly budget is $150.00."
    )


def test_the_cheapest_week_respects_the_other_rules():
    # The cheap item is out of stock, so the cheapest valid week is all PRICEY.
    result = plan_week(
        request(budget_cents=15_000, days=7),
        menu([item(1, price_cents=500, in_stock=False), PRICEY]),
        rules=[get("in_stock")(), OneItemPerMeal(), WeeklyBudget()],
    )
    assert f"${21 * meal_cost_cents(2000) / 100:,.2f}" in result.explanation


def test_shorter_plans_say_plan_instead_of_week():
    result = plan([CHEAP], 100, days=2)
    assert result.explanation.startswith("The cheapest 2-day plan that meets")


def test_budget_defers_when_another_rule_is_impossible_anyway():
    result = plan_week(
        request(budget_cents=100, kcal=5000),
        menu([CHEAP]),
        rules=[OneItemPerMeal(), get("daily_calories")(), WeeklyBudget()],
    )
    assert "budget" not in result.explanation
    assert "kcal" in result.explanation


def test_an_unproven_cheapest_cost_is_reported_as_a_lower_bound(monkeypatch):
    from planner import solver
    from planner.solver import Cheapest

    monkeypatch.setattr(solver, "cheapest_without", lambda ctx, rule: Cheapest(20_000, False))
    result = plan([CHEAP], 15_000, days=7)
    assert "costs at least $200.00" in result.explanation


def test_no_budget_explanation_when_the_cheapest_week_fits(monkeypatch):
    from planner import solver
    from planner.context import PlanContext
    from planner.solver import Cheapest

    monkeypatch.setattr(solver, "cheapest_without", lambda ctx, rule: Cheapest(10_000, True))
    ctx = PlanContext(request(budget_cents=15_000), menu([CHEAP]), [WeeklyBudget()])
    assert WeeklyBudget().explain(ctx) is None
