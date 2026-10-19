"""
The weekly planner: picks every meal of the week at once with the OR-Tools CP-SAT solver.

Each rule in `planner.rules` adds itself to one model (see `planner.constraint`). Hard rules
must hold; soft rules add weighted penalties, and the solver looks for the plan with the
lowest total penalty. Choosing all meals together is what lets a plan meet weekly limits
such as the budget, which picking one meal at a time cannot guarantee.

    from planner.menu import load_menu
    from planner.request import PlanRequest
    from planner.solver import plan_week

    result = plan_week(request, load_menu(db_file))
    if result.ok:
        ...  # result.meals, result.total_cost_cents, result.kcal_by_day()
    else:
        ...  # result.explanation says why no week could be planned

Solving stops after ``time_limit_s`` (4 s by default, counted from the call, so building the
model is included) or after ``work_limit`` of the solver's deterministic time (2.0 by
default), whichever comes first. If a valid plan was found by then it is returned with
``optimal`` False; it is valid, just not proven to be the best one. On a machine that is not
overloaded the work limit is reached first, and since it counts work rather than seconds, the
same request gets the same plan every time. If the machine is so busy that the 4 s limit is
reached first, the plan may differ between runs; it still meets every hard rule.
"""

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from ortools.sat.python import cp_model

from planner.constraint import Constraint, Kind
from planner.context import PlanContext
from planner.menu import Menu, MenuItem
from planner.registry import rules_for
from planner.request import PlanRequest, Slot

DEFAULT_TIME_LIMIT_S = 4.0
# Search effort cap in CP-SAT's deterministic time (roughly seconds on a laptop, but counted
# in work done, not on the clock). Stopping on work instead of wall-clock time makes the plan
# for a given request the same on every run; the wall-clock limit above is a backstop that
# only wins on a machine about twice as slow, or as busy, as a typical laptop. On the M0 users 2.0 gives the same
# H1, H2 and H4 as running to the 4 s limit, with p95 planning time under 3 s instead of 4.1 s.
DEFAULT_WORK_LIMIT = 2.0
# One search worker keeps the search, and so the plan, the same on every run. Plans are small
# enough that more workers mostly add CPU contention on a shared web server.
DEFAULT_WORKERS = 1
RANDOM_SEED = 0
# Least time explain() calls get to re-solve after the model is found infeasible.
MIN_DIAGNOSIS_S = 0.5


class PlannerError(Exception):
    """A rule built a model the solver rejects: a bug in that rule, not in the request."""


class Status(StrEnum):
    """How planning ended."""

    OPTIMAL = "optimal"  # the best week the rules allow, proven
    FEASIBLE = "feasible"  # a valid week; time ran out before it was proven best
    INFEASIBLE = "infeasible"  # no week meets every hard rule; see PlanResult.reasons
    TIMED_OUT = "timed_out"  # time ran out before any valid week was found


@dataclass(frozen=True)
class PlannedMeal:
    """One meal of the plan."""

    slot: Slot
    item: MenuItem

    @property
    def day(self) -> date:
        """The date of the meal."""
        return self.slot.day

    @property
    def meal(self) -> int:
        """1 breakfast, 2 lunch, 3 dinner."""
        return self.slot.meal

    @property
    def itm_id(self) -> int:
        """The MenuItem id picked."""
        return self.item.itm_id

    @property
    def cost_cents(self) -> int:
        """Price with tax and fees."""
        return self.item.cost_cents


@dataclass(frozen=True)
class PlanResult:
    """
    The outcome of `plan_week`.
    Attributes:
        status: How planning ended.
        meals: The planned meals in slot order; empty unless status is OPTIMAL or FEASIBLE.
        reasons: Why there is no plan (one sentence per cause); empty when there is one.
        seconds: Wall-clock time taken, including building the model.
    """

    status: Status
    meals: tuple[PlannedMeal, ...] = ()
    reasons: tuple[str, ...] = ()
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        """True if there is a valid plan."""
        return self.status in (Status.OPTIMAL, Status.FEASIBLE)

    @property
    def optimal(self) -> bool:
        """True if the plan is proven to be the best one; False if time ran out first."""
        return self.status is Status.OPTIMAL

    @property
    def explanation(self) -> str | None:
        """The reasons as one message for the user, or None when there is a plan."""
        return " ".join(self.reasons) or None

    @property
    def total_cost_cents(self) -> int:
        """What the whole plan costs, tax and fees included."""
        return sum(m.cost_cents for m in self.meals)

    def kcal_by_day(self) -> dict[date, int]:
        """Calories planned per day, days in order."""
        totals: dict[date, int] = {}
        for m in self.meals:
            totals[m.day] = totals.get(m.day, 0) + m.item.calories
        return totals

    def menu_entries(self) -> list[str]:
        """The plan in User.generated_menu's format: "[YYYY-MM-DD,itm_id,meal]" per meal."""
        return [f"[{m.day.isoformat()},{m.itm_id},{m.meal}]" for m in self.meals]


def plan_week(
    request: PlanRequest,
    menu: Menu,
    *,
    rules: Sequence[Constraint] | None = None,
    time_limit_s: float = DEFAULT_TIME_LIMIT_S,
    work_limit: float = DEFAULT_WORK_LIMIT,
    workers: int = DEFAULT_WORKERS,
) -> PlanResult:
    """
    Plan every meal of a request at once.
    Args:
        request: The week, targets, allergens and preferences.
        menu: What can be picked (see planner.menu.load_menu).
        rules: The rules to use, in any order. Default: rules_for(request), i.e. every
            registered rule that is on by default plus those the request's options enable.
        time_limit_s: When to stop searching and return the best plan found so far.
        work_limit: The same in deterministic time, so the plan does not depend on how busy
            the machine is. Whichever limit is hit first stops the search.
        workers: CP-SAT search workers. More can be faster but makes plans vary run to run.
    Returns:
        PlanResult: The plan, or the reasons there is none.
    Raises:
        PlannerError: A rule made the model invalid.
    """
    started = time.monotonic()
    rules = sorted(rules_for(request) if rules is None else rules, key=lambda r: r.order)
    ctx = PlanContext(request, menu, rules, deadline=started + time_limit_s)
    for rule in rules:
        rule.apply(ctx)
    ctx.model.Minimize(ctx.objective())

    # The time limit covers the whole call, so building the model counts against it.
    solve_budget = max(0.05, started + time_limit_s - time.monotonic())
    solver = _solver(solve_budget, workers, work_limit)
    status = solver.Solve(ctx.model)

    if status == cp_model.MODEL_INVALID:
        raise PlannerError(f"The rules built an invalid model: {ctx.model.Validate()}")
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        meals = tuple(
            PlannedMeal(slot, item)
            for slot in ctx.slots
            for item, var in ctx.picks(slot)
            if solver.BooleanValue(var)
        )
        # CP-SAT reports OPTIMAL once it stops for a gap limit too; only claim a proof.
        proven = (
            status == cp_model.OPTIMAL and solver.ObjectiveValue() == solver.BestObjectiveBound()
        )
        return PlanResult(
            Status.OPTIMAL if proven else Status.FEASIBLE,
            meals=meals,
            seconds=time.monotonic() - started,
        )
    if status == cp_model.INFEASIBLE:
        # Explanations may re-solve parts of the model; give them a moment even if the
        # infeasibility proof used up most of the time limit.
        ctx.deadline = max(ctx.deadline, time.monotonic() + MIN_DIAGNOSIS_S)
        return PlanResult(
            Status.INFEASIBLE, reasons=diagnose(ctx), seconds=time.monotonic() - started
        )
    # Neither a plan nor a proof that none exists. The search is deterministic, so asking
    # again gives the same answer; say what would help instead.
    seconds = time.monotonic() - started
    return PlanResult(
        Status.TIMED_OUT,
        reasons=(
            f"Planning stopped after {seconds:.1f} seconds without finding a week that meets "
            "all of your requirements, or proving that none exists. A higher budget or a "
            "higher calorie target leaves more weeks to choose from and makes one easier to "
            "find.",
        ),
        seconds=seconds,
    )


@dataclass(frozen=True)
class Cheapest:
    """The cheapest plan cost found by `cheapest_without`."""

    cost_cents: int  # exact if proven, else a lower bound: no plan costs less
    proven: bool


def cheapest_without(ctx: PlanContext, rule: Constraint) -> Cheapest | None:
    """
    For explain(): the lowest cost of any plan that meets every other hard rule in ctx,
    ignoring rule and every soft rule. Uses whatever time is left before ctx.deadline.
    Returns:
        Cheapest | None: The cost (proven minimum, or a lower bound if time ran out), or
        None if the other rules have no solution either, or nothing was learned in time.
    """
    others = [r for r in ctx.rules if r is not rule and r.kind is Kind.HARD]
    sub = PlanContext(ctx.request, ctx.menu, others, deadline=ctx.deadline)
    for other in others:
        other.apply(sub)
    sub.model.Minimize(sub.cost_cents())
    solver = _solver(max(ctx.time_left(), 0.01), DEFAULT_WORKERS)
    status = solver.Solve(sub.model)
    if status == cp_model.OPTIMAL:
        return Cheapest(round(solver.ObjectiveValue()), proven=True)
    if status == cp_model.FEASIBLE:
        return Cheapest(math.ceil(solver.BestObjectiveBound()), proven=False)
    return None


def diagnose(ctx: PlanContext) -> tuple[str, ...]:
    """
    Why the model in ctx has no solution: every hard rule's explain(ctx) that is not None,
    in rule order. If no rule can say, a fallback sentence lists the hard rules in play, so
    the user always gets something more specific than an error.
    """
    reasons = []
    for rule in ctx.rules:
        if rule.kind is Kind.HARD:
            reason = rule.explain(ctx)
            if reason:
                reasons.append(reason)
    if reasons:
        return tuple(reasons)
    hard = [rule.summary.rstrip(".").lower() for rule in ctx.rules if rule.kind is Kind.HARD]
    return (f"No week meets all of these at once: {'; '.join(hard)}.",)


def _solver(
    time_limit_s: float, workers: int, work_limit: float = DEFAULT_WORK_LIMIT
) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.max_deterministic_time = work_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = RANDOM_SEED
    # Full LP relaxation. With one worker, CP-SAT's default level could not prove even a
    # budget that is below the sum of each day's cheapest valid meals infeasible within the
    # time limit; at level 2 it takes about 0.1 s.
    solver.parameters.linearization_level = 2
    return solver
