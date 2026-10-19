import pytest

from eval.run import (
    UserResult,
    check_regression,
    h1_valid_pct,
    h2_median_distinct,
    h3_p95_seconds,
    h4_no_plan_pct,
    overall_valid_pct,
)
from eval.validate import MEAL_TIMES, WEEKDAYS, Meal, Violation, ViolationKind

PROBLEM = (Violation(ViolationKind.OVER_BUDGET),)


def week(*itm_ids):
    """A 21-meal week cycling through the given item ids."""
    slots = [(day, meal) for day in WEEKDAYS for meal in MEAL_TIMES]
    return tuple(Meal(day, meal, itm_ids[i % len(itm_ids)]) for i, (day, meal) in enumerate(slots))


def result(feasible=True, meals=week(1), violations=(), seconds=1.0):
    return UserResult(
        user_id=1, feasible=feasible, meals=meals, violations=violations, seconds=seconds
    )


VALID = result()
INVALID = result(violations=PROBLEM)
NO_PLAN = result(meals=None)


def test_a_result_is_valid_only_with_a_week_and_no_violations():
    assert VALID.valid
    assert not INVALID.valid
    assert not NO_PLAN.valid


# --- H1: share of feasible users who get a valid week ---


def test_h1_counts_feasible_users_only():
    infeasible = result(feasible=False, violations=PROBLEM)

    assert h1_valid_pct([VALID, VALID, VALID, INVALID, infeasible, infeasible]) == 75.0


def test_h1_counts_no_plan_for_a_feasible_user_as_a_failure():
    assert h1_valid_pct([VALID, NO_PLAN]) == 50.0


def test_h1_is_undefined_without_feasible_users():
    assert h1_valid_pct([result(feasible=False, meals=None)]) is None


# --- H2: distinct items per week, median over feasible users ---


def test_h2_is_the_median_of_distinct_items_per_week():
    weeks = [week(*range(n)) for n in (3, 14, 21)]

    assert h2_median_distinct([result(meals=w) for w in weeks]) == 14


def test_h2_median_of_an_even_count_averages_the_middle_two():
    weeks = [week(*range(n)) for n in (2, 13, 14, 21)]

    assert h2_median_distinct([result(meals=w) for w in weeks]) == 13.5


def test_h2_counts_invalid_weeks_but_skips_infeasible_users_and_no_plan():
    others = [result(feasible=False, meals=week(*range(21))), NO_PLAN]

    assert h2_median_distinct([result(meals=week(1, 2), violations=PROBLEM), *others]) == 2


def test_h2_is_undefined_without_weeks_for_feasible_users():
    assert h2_median_distinct([NO_PLAN]) is None


# --- H3: p95 time to plan one week (nearest rank) ---


@pytest.mark.parametrize(
    "n, expected",
    [
        (1, 1.0),  # rank ceil(0.95) = 1
        (20, 19.0),  # rank ceil(19.0) = 19
        (21, 20.0),  # rank ceil(19.95) = 20
        (100, 95.0),  # rank ceil(95.0) = 95
    ],
)
def test_h3_is_the_nearest_rank_95th_percentile(n, expected):
    seconds = list(range(n, 0, -1))  # unsorted on purpose

    assert h3_p95_seconds([result(seconds=float(s)) for s in seconds]) == expected


def test_h3_times_every_user():
    results = [result(feasible=False, meals=None, seconds=9.0), result(seconds=1.0)]

    assert h3_p95_seconds(results) == 9.0


def test_h3_is_undefined_without_results():
    assert h3_p95_seconds([]) is None


# --- H4: share of infeasible users who get an explicit "no valid week" ---


def test_h4_counts_infeasible_users_only():
    infeasible_no_plan = result(feasible=False, meals=None)
    infeasible_week = result(feasible=False, violations=PROBLEM)

    assert h4_no_plan_pct([infeasible_no_plan, infeasible_week, NO_PLAN, VALID]) == 50.0


def test_h4_is_undefined_without_infeasible_users():
    assert h4_no_plan_pct([VALID, NO_PLAN]) is None


# --- Headline: share of all users who get a valid week ---


def test_overall_counts_every_user():
    infeasible = result(feasible=False, meals=None)

    assert overall_valid_pct([VALID, INVALID, NO_PLAN, infeasible]) == 25.0


def test_overall_is_undefined_without_results():
    assert overall_valid_pct([]) is None


# --- Regression guard: H1 may not drop by 5 or more points vs main ---


def summaries(**h1_by_planner):
    return {planner: {"h1_valid_pct": h1} for planner, h1 in h1_by_planner.items()}


@pytest.mark.parametrize(
    "baseline, current, fails",
    [
        (80.0, 75.0, True),  # a 5.0-point drop fails
        (80.0, 75.1, False),  # a 4.9-point drop passes
        (80.0, 76.0, False),  # a 4-point drop passes
        (80.0, 92.0, False),  # an improvement passes
        (80.0, 80.0, False),
    ],
)
def test_regression_fails_on_a_drop_of_five_points_or_more(baseline, current, fails):
    problems = check_regression(summaries(B1=current), summaries(B1=baseline))

    assert bool(problems) is fails


def test_exact_five_point_drop_fails_despite_float_rounding():
    # 7 -> 4 of 60 users is exactly 5 points, but computes as 4.999999999999999.
    baseline, current = 100 * 7 / 60, 100 * 4 / 60
    assert baseline - current < 5

    assert check_regression(summaries(B1=current), summaries(B1=baseline))


def test_regression_names_only_the_planner_that_dropped():
    problems = check_regression(summaries(B1=70.0, B2=50.0), summaries(B1=70.0, B2=60.0))

    assert len(problems) == 1
    assert "B2" in problems[0]


def test_regression_skips_planners_missing_from_the_baseline():
    assert check_regression(summaries(B1=70.0, M1=10.0), summaries(B1=70.0)) == []


def test_regression_skips_undefined_h1():
    assert check_regression(summaries(B1=None), summaries(B1=80.0)) == []
    assert check_regression(summaries(B1=10.0), summaries(B1=None)) == []


def test_regression_threshold_can_be_changed():
    assert check_regression(summaries(B1=78.0), summaries(B1=80.0), max_drop=2.0)
