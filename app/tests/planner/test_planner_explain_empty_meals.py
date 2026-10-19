"""When filters leave a meal with no items, the explanation says which filters and how many."""

from menu_factory import item, menu, request

from planner.constraint import ItemFilter
from planner.registry import get
from planner.solver import Status, plan_week

OneItemPerMeal = get("one_item_per_meal")


class NoBreakfastBefore(ItemFilter):
    name = "no_breakfast_test"
    summary = "Nothing at breakfast."
    blocked_reason = "are not served at breakfast"

    def allows(self, item, slot, ctx):
        return slot.meal != 1


class NoOddIds(ItemFilter):
    name = "no_odd_ids_test"
    summary = "Skip odd ids."
    blocked_reason = "have odd ids"

    def allows(self, item, slot, ctx):
        return item.itm_id % 2 == 0


class NoMondays(ItemFilter):
    name = "no_mondays_test"
    summary = "Nothing on Monday."
    blocked_reason = "unused"

    def allows(self, item, slot, ctx):
        return slot.weekday != "Mon"

    def describe_block(self, slot, ctx):
        return f"are not sold on {slot.weekday}"


def test_an_empty_meal_on_every_day_is_reported_once_with_counts_per_filter():
    result = plan_week(
        request(days=7),
        menu([item(1), item(2), item(3)]),
        rules=[NoOddIds(), NoBreakfastBefore(), OneItemPerMeal()],
    )

    assert result.status is Status.INFEASIBLE
    assert result.explanation == (
        "No breakfast can be planned on any day: of 3 menu items, "
        "2 have odd ids and 1 are not served at breakfast."
    )


def test_an_empty_meal_on_some_days_names_those_days_and_uses_describe_block():
    result = plan_week(
        request(days=3, meals=(2,)), menu([item(2)]), rules=[NoMondays(), OneItemPerMeal()]
    )

    assert result.explanation == (
        "No lunch can be planned on Mon Oct 19: of 1 menu items, 1 are not sold on Mon."
    )


def test_meals_blocked_the_same_way_on_the_same_days_share_a_sentence():
    result = plan_week(
        request(days=2, meals=(1, 2)),
        menu([item(1), item(3)]),
        rules=[NoOddIds(), NoBreakfastBefore(), OneItemPerMeal()],
    )
    # NoOddIds is applied first and blocks both items, so breakfast and lunch read the same.
    assert result.explanation == (
        "No breakfast or lunch can be planned on any day: of 2 menu items, 2 have odd ids."
    )


def test_an_empty_menu_says_so():
    result = plan_week(request(), menu([]), rules=[OneItemPerMeal()])
    assert result.explanation == "There are no menu items to plan with yet."


def test_no_explanation_from_this_rule_when_every_meal_has_items():
    from planner.context import PlanContext

    ctx = PlanContext(request(), menu([item(1)]), [OneItemPerMeal()])
    assert OneItemPerMeal().explain(ctx) is None


def test_when_no_rule_can_explain_the_user_still_gets_the_rules_in_play():
    from planner.constraint import Constraint

    class Impossible(Constraint):
        name = "impossible_test"
        summary = "Breakfast must be free."

        def apply(self, ctx):
            ctx.model.Add(ctx.cost_cents(ctx.slots[:1]) == 0)

    result = plan_week(request(), menu([item(1)]), rules=[Impossible(), OneItemPerMeal()])

    assert result.explanation == (
        "No week meets all of these at once: every meal gets exactly one menu item; "
        "breakfast must be free."
    )
