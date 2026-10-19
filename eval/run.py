"""
Run the evaluation and score it against the hypotheses in GitHub issue #5.

    python -m eval.run --seed 510                  # replay the recorded B2 run; no API key
    python -m eval.run --seed 510 --record         # record B2 on the app's LLM, then replay
    python -m eval.run --baseline main_m0.json     # exit 1 if H1 dropped 5+ points vs main

Writes m0.json and m0.md to --out (default eval/results). Exits 0 even when a hypothesis
fails; only a regression against --baseline exits 1.

Metrics are percentages from 0 to 100 (or counts and seconds), and None when no user falls in
the group a metric is measured on.

A planner returns its meals, None for "no valid week", or eval.planners.NoValidWeek for "no
valid week" with the reason the user would be shown.
"""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import llm_toolkit
import menu_generation

from eval.baselines import RecordingError, RecordingLLM, ReplayLLM, random_safe, v1_llm
from eval.catalog import Catalog, load_catalog
from eval.feasibility import is_feasible
from eval.planners import NoValidWeek, m1_solver
from eval.profiles import Profile, generate_profiles
from eval.validate import Meal, Violation, ViolationKind, validate_week

REPO = Path(__file__).resolve().parent.parent
RECORDING = REPO / "eval" / "fixtures" / "b2_v1_cassette.json"
DEFAULT_OUT = REPO / "eval" / "results"
SCHEMA_VERSION = 2  # 2: adds explained_pct per planner


@dataclass(frozen=True)
class Hypothesis:
    id: str
    metric: str
    label: str
    pass_if: str  # ">=" or "<="
    value: float
    baselines: str


HYPOTHESES = (
    Hypothesis("H1", "h1_valid_pct", "Valid week, feasible users", ">=", 90, "B1, B2"),
    Hypothesis("H2", "h2_median_distinct", "Distinct items per week (median)", ">=", 14, "B1"),
    Hypothesis("H3", "h3_p95_s", "Time to plan a week (p95)", "<=", 5, "B2"),
    Hypothesis("H4", "h4_no_plan_pct", '"No valid week", infeasible users', ">=", 90, "B1, B2"),
)


@dataclass(frozen=True)
class Planner:
    name: str
    plan: Callable[[Profile, Catalog, int], tuple[Meal, ...] | NoValidWeek | None]
    # A ReplayLLM whose recorded LLM latency is added to the measured time (for H3).
    replay: ReplayLLM | None = None


@dataclass(frozen=True)
class UserResult:
    user_id: int
    feasible: bool  # a valid week exists for this user
    meals: tuple[Meal, ...] | None  # None: the planner answered "no valid week"
    violations: tuple[Violation, ...]
    seconds: float  # time the planner took for this user
    reason: str | None = None  # why there is no valid week, if the planner said

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


def explained_pct(results: Sequence[UserResult]) -> float | None:
    """
    Share of infeasible users who get "no valid week" together with a reason they can act
    on (M1's target: 100%). A bare "no valid week", or an invalid week, counts as a miss.
    """
    return _pct([r.meals is None and bool(r.reason) for r in results if not r.feasible])


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


def evaluate(
    planner: Planner,
    profiles: Sequence[Profile],
    catalog: Catalog,
    seed: int,
    feasible: Mapping[int, bool],
) -> list[UserResult]:
    """
    Plan a week for every user, time it and validate it.
    Raises:
        RuntimeError: A planner found a valid week for a user marked infeasible. That cannot
        happen unless the feasibility check (or the validator) is wrong, so it stops the run.
    """
    results = []
    for profile in profiles:
        recorded_before = planner.replay.recorded_seconds if planner.replay else 0.0
        start = time.perf_counter()
        answer = planner.plan(profile, catalog, seed)
        seconds = time.perf_counter() - start
        reason = answer.reason if isinstance(answer, NoValidWeek) else None
        meals = None if isinstance(answer, NoValidWeek) else answer
        if planner.replay:
            seconds += planner.replay.recorded_seconds - recorded_before
        result = UserResult(
            user_id=profile.user_id,
            feasible=feasible[profile.user_id],
            meals=None if meals is None else tuple(meals),
            violations=() if meals is None else tuple(validate_week(meals, profile, catalog)),
            seconds=seconds,
            reason=reason,
        )
        if result.valid and not result.feasible:
            raise RuntimeError(
                f"{planner.name} found a valid week for user {profile.user_id}, whom the "
                "feasibility check marked infeasible: the feasibility check or the validator "
                "is wrong."
            )
        results.append(result)
    return results


def summarize(results: Sequence[UserResult]) -> dict:
    """One planner's metrics, plus how many users had each kind of violation (every kind)."""
    return {
        "h1_valid_pct": h1_valid_pct(results),
        "h2_median_distinct": h2_median_distinct(results),
        "h3_p95_s": h3_p95_seconds(results),
        "h4_no_plan_pct": h4_no_plan_pct(results),
        "overall_valid_pct": overall_valid_pct(results),
        "explained_pct": explained_pct(results),
        "users_with_violation": {
            kind.value: sum(any(v.kind == kind for v in r.violations) for r in results)
            for kind in ViolationKind
        },
    }


def run(seed: int, catalog: Catalog, profiles: Sequence[Profile], planners: Sequence[Planner]):
    """Evaluate every planner on the same users and return the report (m0.json's content)."""
    feasible = {p.user_id: is_feasible(p, catalog) for p in profiles}
    return {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "users": {
            "total": len(profiles),
            "feasible": sum(feasible.values()),
            "hard": sum(p.hard for p in profiles),
            "hard_feasible": sum(feasible[p.user_id] for p in profiles if p.hard),
        },
        "thresholds": {h.metric: {"pass_if": h.pass_if, "value": h.value} for h in HYPOTHESES},
        "planners": {
            planner.name: summarize(evaluate(planner, profiles, catalog, seed, feasible))
            for planner in planners
        },
    }


def render_markdown(report: dict) -> str:
    """The results table posted to the CI job summary and committed as m0.md."""
    names = list(report["planners"])
    users = report["users"]
    lines = [
        "# M0 results",
        "",
        f"Seed {report['seed']}, {users['total']} simulated users: {users['feasible']} feasible "
        f"(a valid week exists) and {users['total'] - users['feasible']} not. "
        f"{users['hard_feasible']} of the {users['hard']} hard users are feasible.",
        "",
        "| Hypothesis | Pass if | Baselines | " + " | ".join(names) + " |",
        "|---|---|---|" + "---|" * len(names),
    ]
    for h in HYPOTHESES:
        cells = []
        for name in names:
            value = report["planners"][name][h.metric]
            if value is None:
                cells.append("n/a")
            else:
                passed = value >= h.value if h.pass_if == ">=" else value <= h.value
                cells.append(f"{_format(h.metric, value)} {'PASS' if passed else 'FAIL'}")
        pass_if = f"{'≥' if h.pass_if == '>=' else '≤'} {_format(h.metric, h.value)}"
        lines.append(f"| {h.id} {h.label} | {pass_if} | {h.baselines} | {' | '.join(cells)} |")
    overall = [
        _format("overall_valid_pct", report["planners"][n]["overall_valid_pct"]) for n in names
    ]
    explained = [_format("explained_pct", report["planners"][n]["explained_pct"]) for n in names]
    lines += [
        f"| All users with a valid week | no threshold | | {' | '.join(overall)} |",
        f"| Infeasible users told why | M1 target 100% | B2 | {' | '.join(explained)} |",
        "",
        "H3 for a replayed LLM planner adds the recorded LLM latency to the replay time.",
        "",
        "## Users with each kind of violation",
        "",
        "| Violation | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for kind in ViolationKind:
        counts = [str(report["planners"][n]["users_with_violation"][kind.value]) for n in names]
        lines.append(f"| {kind.value} | {' | '.join(counts)} |")
    return "\n".join(lines) + "\n"


def _format(metric: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    if metric.endswith("_pct"):
        return f"{value:.1f}%"
    if metric.endswith("_s"):
        return f"{value:.3f} s"
    return f"{value:g}"


def m0_planners(replay: ReplayLLM) -> list[Planner]:
    """The M0 baselines, then M1 (the solver). B2 answers its prompts from the recording."""
    return [
        Planner("B1", random_safe),
        Planner("B2", partial(v1_llm, llm=replay), replay),
        Planner("M1", m1_solver),
    ]


def record_b2(catalog: Catalog, profiles: Sequence[Profile], seed: int):
    """
    Run v1 for every user on the app's LLM and record the responses to RECORDING, resuming
    an earlier, unfinished recording if there is one.
    """
    live = _live_llm()
    recorder = RecordingLLM(live, RECORDING)
    print(
        f"Recording B2 with {recorder.model} ({live.provider}); "
        f"{recorder.resumed} responses already recorded",
        file=sys.stderr,
    )
    for done, profile in enumerate(profiles, start=1):
        v1_llm(profile, catalog, seed, llm=recorder)
        print(f"  user {done}/{len(profiles)} recorded", file=sys.stderr, flush=True)
    recorder.finish()


def _live_llm():
    """
    The app's own LLM, chosen the way the app chooses it: OpenAI if OPENAI_API_KEY is set
    (environment or .env), otherwise the local HuggingFace model.
    """
    return llm_toolkit.LLM(tokens=500)  # the token limit /generate_plan uses


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the M0 evaluation (GitHub issue #5).")
    parser.add_argument("--seed", type=int, default=510)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where m0.json/.md go")
    parser.add_argument(
        "--record",
        action="store_true",
        help="run B2 on the app's LLM (OpenAI if OPENAI_API_KEY is set, else the local model) "
        "and save the recording",
    )
    parser.add_argument(
        "--baseline", type=Path, help="an m0.json to compare H1 against; exit 1 on regression"
    )
    args = parser.parse_args(argv)

    # The database v1 reads, so every planner and every check sees the same menu.
    catalog = load_catalog(menu_generation.db_file)
    profiles = generate_profiles(args.seed)
    if args.record:
        try:
            record_b2(catalog, profiles, args.seed)
        except RecordingError as e:
            sys.exit(str(e))
    if not RECORDING.exists():
        sys.exit(
            f"No B2 recording at {RECORDING}. Record one with "
            f"`python -m eval.run --seed {args.seed} --record`."
        )
    # Results always come from a replay, even right after recording, so B2's time is the
    # recorded LLM time for every call (a resumed recording replays part of the run instantly).
    report = run(args.seed, catalog, profiles, m0_planners(ReplayLLM(RECORDING)))

    markdown = render_markdown(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "m0.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.out / "m0.md").write_text(markdown)
    print(markdown)

    if args.baseline:
        problems = check_regression(
            report["planners"], json.loads(args.baseline.read_text())["planners"]
        )
        for problem in problems:
            print(f"Regression: {problem}", file=sys.stderr)
        if problems:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
