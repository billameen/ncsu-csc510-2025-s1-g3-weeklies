"""
Run the evaluation and score it against the hypotheses in GitHub issue #5.

Metrics are percentages from 0 to 100 (or counts and seconds), and None when no user falls in
the group a metric is measured on.
"""

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from eval.validate import Meal, Violation


@dataclass(frozen=True)
class UserResult:
    user_id: int
    feasible: bool  # a valid week exists for this user
    meals: tuple[Meal, ...] | None  # None: the planner answered "no valid week"
    violations: tuple[Violation, ...]
    seconds: float  # time the planner took for this user

    @property
    def valid(self) -> bool:
        return self.meals is not None and not self.violations


def h1_valid_pct(results: Sequence[UserResult]) -> float | None:
    """H1: share of feasible users who get a valid week. "No valid week" counts as a miss."""
    return _pct([r.valid for r in results if r.feasible])


def h2_median_distinct(results: Sequence[UserResult]) -> float | None:
    """H2: median number of distinct items per week planned for a feasible user, valid or not."""
    counts = [len({m.itm_id for m in r.meals}) for r in results if r.feasible and r.meals]
    return statistics.median(counts) if counts else None


def h3_p95_seconds(results: Sequence[UserResult]) -> float | None:
    """
    H3: 95th percentile of planning time over all users, by nearest rank: the value at rank
    ceil(0.95 * n) in ascending order, so it is always a time that was actually measured.
    """
    if not results:
        return None
    seconds = sorted(r.seconds for r in results)
    rank = (95 * len(seconds) + 99) // 100  # ceil(0.95 * n), in integers
    return seconds[rank - 1]


def h4_no_plan_pct(results: Sequence[UserResult]) -> float | None:
    """H4: share of infeasible users who get an explicit "no valid week" answer."""
    return _pct([r.meals is None for r in results if not r.feasible])


def overall_valid_pct(results: Sequence[UserResult]) -> float | None:
    """Headline number, no threshold: share of all users who get a valid week."""
    return _pct([r.valid for r in results])


def check_regression(
    current: Mapping[str, Mapping], baseline: Mapping[str, Mapping], max_drop: float = 5.0
) -> list[str]:
    """
    Compare H1 per planner against a baseline (the results on main).
    Args:
        current: Planner name -> metrics, including "h1_valid_pct".
        baseline: The same shape, from the baseline run.
        max_drop: A drop of this many percentage points or more fails.
    Returns:
        list[str]: One message per planner whose H1 dropped too far; empty if none did.
        Planners missing from the baseline, or with undefined H1 on either side, are skipped.
    """
    problems = []
    for planner, metrics in current.items():
        now = metrics.get("h1_valid_pct")
        before = baseline.get(planner, {}).get("h1_valid_pct")
        if now is None or before is None:
            continue
        # Rounded so an exact 5-point drop such as 7/60 -> 4/60 is not 4.999999999999999.
        drop = round(before - now, 6)
        if drop >= max_drop:
            problems.append(
                f"{planner}: H1 dropped {drop:.1f} points ({before:.1f}% -> {now:.1f}%), "
                f"the limit is {max_drop:.1f}"
            )
    return problems


def _pct(flags: list[bool]) -> float | None:
    return 100 * sum(flags) / len(flags) if flags else None
