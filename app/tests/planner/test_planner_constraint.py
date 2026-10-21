"""The plug-in base classes and the PlanContext helpers rules build on."""

import pytest
from menu_factory import item, menu, request
from ortools.sat.python import cp_model

from planner.constraint import Constraint, ItemFilter, Kind, SoftConstraint
from planner.context import PlanContext


class NoOddIds(ItemFilter):
    name = "no_odd_ids"
    summary = "Skip items with odd ids."
    blocked_reason = "have odd ids"

    def allows(self, item, slot, ctx):
        return item.itm_id % 2 == 0


class NoBigIds(ItemFilter):
    name = "no_big_ids"
    summary = "Skip items with ids above 2."
    blocked_reason = "have big ids"

    def allows(self, item, slot, ctx):
        return item.itm_id <= 2


class PreferCheap(SoftConstraint):
    name = "prefer_cheap_test"
    summary = "Cheaper is better."
    default_weight = 3

    def apply(self, ctx):
        ctx.add_penalty(self, ctx.cost_cents())


class HardRule(Constraint):
    name = "hard_rule_test"
    summary = "Does nothing."

    def apply(self, ctx):
        pass


@pytest.fixture()
def ctx():
    four = menu([item(1, 100), item(2, 200), item(3, 300), item(4, 400)])
    return PlanContext(request(meals=(1, 2)), four)


def test_an_item_filter_forbids_what_it_does_not_allow_and_remembers_why(ctx):
    NoOddIds().apply(ctx)
    breakfast = ctx.slots[0]

    assert [i.itm_id for i in ctx.candidates(breakfast)] == [2, 4]
    assert isinstance(ctx.blocked_by(breakfast, ctx.menu.items[1]), NoOddIds)
    assert ctx.blocked_by(breakfast, ctx.menu.items[2]) is None


def test_the_first_rule_to_block_an_item_gets_the_blame(ctx):
    NoOddIds().apply(ctx)
    NoBigIds().apply(ctx)
    slot = ctx.slots[0]

    assert [i.itm_id for i in ctx.candidates(slot)] == [2]
    assert isinstance(ctx.blocked_by(slot, ctx.menu.items[3]), NoOddIds)  # odd and big
    assert isinstance(ctx.blocked_by(slot, ctx.menu.items[4]), NoBigIds)


def test_forbidden_picks_are_zero_in_every_solution(ctx):
    NoOddIds().apply(ctx)
    for slot in ctx.slots:
        ctx.model.AddExactlyOne(var for _, var in ctx.picks(slot))
    solver = cp_model.CpSolver()
    assert solver.Solve(ctx.model) == cp_model.OPTIMAL
    for slot in ctx.slots:
        assert solver.Value(ctx.pick(slot, ctx.menu.items[1])) == 0


def test_soft_rules_add_weighted_penalties_to_the_objective(ctx):
    PreferCheap().apply(ctx)
    for slot in ctx.slots:
        ctx.model.AddExactlyOne(var for _, var in ctx.picks(slot))
    ctx.model.Minimize(ctx.objective())
    solver = cp_model.CpSolver()
    assert solver.Solve(ctx.model) == cp_model.OPTIMAL
    # Two slots, cheapest item (100c -> 655c with tax and fees) in each, times weight 3.
    assert solver.ObjectiveValue() == 3 * 2 * ctx.menu.items[1].cost_cents


def test_hard_rules_cannot_add_penalties(ctx):
    with pytest.raises(TypeError, match="hard rule"):
        ctx.add_penalty(HardRule(), ctx.cost_cents())


def test_soft_rule_weights_can_be_overridden_but_not_negative():
    assert PreferCheap().weight == 3
    assert PreferCheap(weight=10).weight == 10
    with pytest.raises(ValueError, match="weight"):
        PreferCheap(weight=-1)
    with pytest.raises(ValueError, match="weight"):
        PreferCheap(weight=1.5)


def test_from_request_reads_the_rule_option():
    assert isinstance(HardRule.from_request(request()), HardRule)
    assert HardRule.from_request(request(options={"hard_rule_test": False})) is None
    assert (
        PreferCheap.from_request(request(options={"prefer_cheap_test": {"weight": 7}})).weight == 7
    )
    assert PreferCheap.from_request(request(options={"prefer_cheap_test": 9})).weight == 9


def test_rules_are_hard_unless_they_say_otherwise():
    assert HardRule.kind is Kind.HARD and NoOddIds.kind is Kind.HARD
    assert PreferCheap.kind is Kind.SOFT


def test_context_groups_slots_by_day_and_sums_calories():
    ctx = PlanContext(request(days=2, meals=(1, 3)), menu([item(1, calories=500)]))
    days = ctx.slots_by_day()
    assert [len(slots) for slots in days.values()] == [2, 2]
    first_day = next(iter(days.values()))
    for slot in first_day:
        ctx.model.Add(ctx.pick(slot, ctx.menu.items[1]) == 1)
    total = ctx.model.NewIntVar(0, 10_000, "total")
    ctx.model.Add(total == ctx.calories(first_day))
    solver = cp_model.CpSolver()
    solver.Solve(ctx.model)
    assert solver.Value(total) == 1000
