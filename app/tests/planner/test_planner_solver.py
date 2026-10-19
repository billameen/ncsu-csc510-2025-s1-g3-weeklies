"""plan_week: solving a model built from rules and reporting the result."""

import pytest
from menu_factory import MONDAY, item, menu, request

from planner.constraint import Constraint
from planner.registry import get
from planner.solver import PlannerError, PlanResult, Status, plan_week

OneItemPerMeal = get("one_item_per_meal")


def test_one_item_per_meal_gives_every_slot_exactly_one_item():
    result = plan_week(request(days=2), menu([item(1), item(2)]), rules=[OneItemPerMeal()])

    assert result.ok and result.status in (Status.OPTIMAL, Status.FEASIBLE)
    assert [(m.day.day, m.meal) for m in result.meals] == [
        (19, 1),
        (19, 2),
        (19, 3),
        (20, 1),
        (20, 2),
        (20, 3),
    ]
    assert result.reasons == () and result.explanation is None


def test_result_totals_cost_and_calories_per_day():
    result = plan_week(
        request(days=2), menu([item(1, price_cents=1000, calories=500)]), rules=[OneItemPerMeal()]
    )

    assert result.total_cost_cents == 6 * (1000 + 73 + 548)
    assert list(result.kcal_by_day().values()) == [1500, 1500]
    assert result.menu_entries()[:2] == ["[2026-10-19,1,1]", "[2026-10-19,1,2]"]


def test_with_no_soft_rules_the_plan_is_trivially_optimal():
    result = plan_week(request(), menu([item(1)]), rules=[OneItemPerMeal()])
    assert result.status is Status.OPTIMAL and result.optimal


def test_a_meal_with_no_items_left_makes_the_week_infeasible():
    class NothingAllowed(Constraint):
        name = "nothing_allowed_test"
        summary = "Blocks every item."

        def apply(self, ctx):
            for slot in ctx.slots:
                for i in ctx.candidates(slot):
                    ctx.forbid(slot, i, self)

    result = plan_week(request(), menu([item(1)]), rules=[NothingAllowed(), OneItemPerMeal()])

    assert result.status is Status.INFEASIBLE and not result.ok
    assert result.meals == () and result.explanation


def test_a_rule_that_builds_an_invalid_model_is_reported_as_a_planner_bug():
    class Invalid(Constraint):
        name = "invalid_test"
        summary = "Adds a constraint with an out-of-range coefficient."

        def apply(self, ctx):
            var = ctx.model.NewIntVar(0, 1, "v")
            ctx.model.Add(var * (2**62) + var * (2**62) <= 1)

    with pytest.raises(PlannerError, match="invalid model"):
        plan_week(request(), menu([item(1)]), rules=[Invalid(), OneItemPerMeal()])


def test_rules_default_to_the_registered_rules_for_the_request():
    result = plan_week(request(), menu([item(1)]))
    assert result.ok


def test_seconds_is_measured():
    assert plan_week(request(), menu([item(1)]), rules=[OneItemPerMeal()]).seconds > 0


def test_planned_meal_exposes_the_fields_the_app_stores():
    meal = plan_week(request(), menu([item(7)]), rules=[OneItemPerMeal()]).meals[0]
    assert (meal.day, meal.meal, meal.itm_id) == (MONDAY, 1, 7)


def test_empty_result_defaults():
    result = PlanResult(Status.TIMED_OUT, reasons=("slow",))
    assert result.total_cost_cents == 0 and result.kcal_by_day() == {}
    assert result.explanation == "slow"
