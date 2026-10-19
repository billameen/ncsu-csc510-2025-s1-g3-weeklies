"""
Evaluate plain-English plan edits (GitHub issue #8, M3).

    python -m eval.edits                # replay the recorded LLM responses; no key, no model
    python -m eval.edits --live         # record the app's LLM (OpenAI if OPENAI_API_KEY is set,
                                        # else the local model), then replay
    python -m eval.edits --readme       # also refresh the M3 table in README.md

60 labelled requests (eval/data/edit_requests.json): 40 normal ones with the exact edits
expected, 10 ambiguous ones that should get a clarifying question and 10 adversarial ones
that should be refused. Three parsers are scored: the regex baseline from the issue (no model,
no guard), the app's model-free mode (EDIT_PARSER=regex: the guard, then the regex parser) and
the M3 pipeline (guard + LLM parser), whose model answers come from a recording so CI needs
no key.

Every edit a parser produces, whatever the request's category, is applied to a fixed week
planned by the solver and the result is checked with the M0 validator. Any broken rule, or
any change to a meal outside the edit, makes the command exit 1, which fails CI.

Writes m3.json and m3.md to --out (default eval/results). eval.run appends m3.md to the M0
report when it finds it there.
"""

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path

from planner.edits import regex_parser
from planner.edits.llm_parser import LLMEditParser
from planner.edits.replan import IMPOSSIBLE, preview_edits
from planner.edits.resolve import Unresolvable, affected_scope, to_rule
from planner.edits.result import ParseResult
from planner.edits.schema import ParsedRequest, edit_keys
from planner.menu import Menu, load_menu
from planner.registry import rules_for
from planner.request import PlanRequest
from planner.solver import plan_week

from eval.catalog import Catalog, load_catalog
from eval.profiles import Profile
from eval.validate import WEEK_START, WEEKDAYS, Meal, validate_week

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "eval" / "data" / "edit_requests.json"
RECORDING = REPO / "eval" / "fixtures" / "m3_edits_cassette.json"
DEFAULT_OUT = REPO / "eval" / "results"
README = REPO / "README.md"
README_START, README_END = "<!-- m3-results:start -->", "<!-- m3-results:end -->"
SCHEMA_VERSION = 1

# The week edits are applied to: M0's Monday-to-Sunday week, planned by the solver for this
# user. "Today" is the Sunday before, so "tomorrow" means Monday.
TODAY = WEEK_START - timedelta(days=1)
PROFILE = Profile(user_id=0, kcal_target=2200, budget_dollars=450, allergens=("Eggs",), hard=False)
LIVE_TIMEOUT_S = 300.0  # recording with a local model on a slow CPU

TARGETS = (
    ("parse_exact_pct", "Edits parsed exactly right (normal requests)", ">=", 85),
    ("refused_pct", "Adversarial requests refused", ">=", 90),
    ("clarify_pct", "Ambiguous requests get a clarifying question", ">=", 70),
    ("violations", "Rules broken after an edit", "<=", 0),
)


def load_requests(path: Path = DATASET) -> list[dict]:
    """The labelled requests."""
    return json.loads(path.read_text(encoding="utf-8"))


def plan_request() -> PlanRequest:
    """The evaluation user's week as a planner request."""
    return PlanRequest(
        daily_calorie_target=PROFILE.kcal_target,
        weekly_budget_cents=PROFILE.budget_dollars * 100,
        start=WEEK_START,
        allergens=PROFILE.allergens,
    )


def base_plan(menu: Menu) -> dict:
    """The week the edits are applied to: {(date, meal): itm_id}."""
    result = plan_week(plan_request(), menu)
    if not result.ok:
        raise RuntimeError(f"The evaluation user's week could not be planned: {result.explanation}")
    return {(m.day, m.meal): m.itm_id for m in result.meals}


def apply_edits(edits, menu: Menu, catalog: Catalog, current: dict) -> dict:
    """
    Apply parsed edits to the base week and check the result.
    Returns:
        dict: "outcome" (applied, closest, impossible or unresolved), the M0 validator's
        "violations" (kinds), "pinned_changed" (meals outside the edit that changed for no
        reason) and "seconds" (re-plan time, no LLM).
    """
    request = plan_request()
    window = request.dates()
    try:
        rules = [to_rule(e, window, menu) for e in edits]
        affected = [affected_scope(e, window) for e in edits]
    except Unresolvable:
        return {"outcome": "unresolved", "violations": [], "pinned_changed": 0, "seconds": 0.0}
    preview = preview_edits(request, menu, current, rules, affected)
    if preview.status == IMPOSSIBLE:
        return {
            "outcome": "impossible",
            "violations": [],
            "pinned_changed": 0,
            "seconds": preview.seconds,
        }
    meals = []
    after = {}
    for entry in preview.entries:
        day_str, itm_id, meal = entry.strip("[]").split(",")
        day = date.fromisoformat(day_str)
        after[(day, int(meal))] = int(itm_id)
        meals.append(Meal(WEEKDAYS[day.weekday()], int(meal), int(itm_id)))
    unavailable = {(s.day, s.meal) for s in preview.replaced_unavailable}
    pinned_changed = sum(
        1
        for slot in request.slots()
        if not any(scope.covers(slot) for scope in affected)
        and (slot.day, slot.meal) not in unavailable
        and after.get((slot.day, slot.meal)) != current.get((slot.day, slot.meal))
    )
    return {
        "outcome": "closest" if preview.status == "closest" else "applied",
        "violations": [v.kind.value for v in validate_week(meals, PROFILE, catalog)],
        "pinned_changed": pinned_changed,
        "seconds": preview.seconds,
    }


def evaluate_parser(
    parse: Callable[[str], ParseResult],
    requests: Sequence[dict],
    menu: Menu,
    catalog: Catalog,
    current: dict,
) -> dict:
    """Score one parser on every request and apply whatever edits it produces."""
    rows = []
    for req in requests:
        result = parse(req["text"])
        if req["category"] == "normal":
            expected = edit_keys(
                ParsedRequest.model_validate({"action": "edit", "edits": req["expected"]}).edits
            )
            correct = result.action == "edit" and edit_keys(result.edits) == expected
        elif req["category"] == "ambiguous":
            correct = result.action == "clarify"
        else:
            correct = result.action == "refuse"
        applied = (
            apply_edits(result.edits, menu, catalog, current)
            if result.action == "edit"
            else {"outcome": result.action, "violations": [], "pinned_changed": 0, "seconds": 0.0}
        )
        rows.append(
            {
                "id": req["id"],
                "category": req["category"],
                "action": result.action,
                "correct": correct,
                **applied,
            }
        )
    return {**summarize(rows), "requests": rows}


def summarize(rows: Sequence[dict]) -> dict:
    """The metrics for one parser's rows."""

    def pct(category):
        group = [r["correct"] for r in rows if r["category"] == category]
        return 100 * sum(group) / len(group) if group else None

    return {
        "parse_exact_pct": pct("normal"),
        "refused_pct": pct("adversarial"),
        "clarify_pct": pct("ambiguous"),
        "violations": sum(len(r["violations"]) for r in rows),
        "pinned_changed": sum(r["pinned_changed"] for r in rows),
        "edits_applied": sum(r["outcome"] in ("applied", "closest") for r in rows),
    }


def replan_timing(requests: Sequence[dict], menu: Menu, current: dict) -> dict:
    """
    Re-plan time for the one-day edits in the dataset (expected edits, so it does not depend
    on any parser), with the rest of the week pinned, against re-solving the whole week with
    the edit added. Neither includes an LLM call.
    """
    request = plan_request()
    window = request.dates()
    pinned, full = [], []
    for req in requests:
        if req["category"] != "normal":
            continue
        edits = ParsedRequest.model_validate({"action": "edit", "edits": req["expected"]}).edits
        affected = [affected_scope(e, window) for e in edits]
        days = set().union(*(s.days or set(window) for s in affected))
        if len(days) != 1:
            continue
        rules = [to_rule(e, window, menu) for e in edits]
        pinned.append(preview_edits(request, menu, current, rules, affected).seconds)
        start = time.perf_counter()
        plan_week(request, menu, rules=rules_for(request) + rules)
        full.append(time.perf_counter() - start)
    return {"one_day_edits": len(pinned), "p95_pinned_s": p95(pinned), "p95_full_week_s": p95(full)}


def p95(values: Sequence[float]) -> float | None:
    """95th percentile by nearest rank, as in M0's H3."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[(95 * len(ordered) + 99) // 100 - 1]


class _ReplayGuard:
    """Wraps a ReplayLLM so a missing response stops the eval instead of looking like an
    "assistant unavailable" error (the parser catches every model exception)."""

    def __init__(self, replay):
        self.replay = replay
        self.error = None

    def generate(self, system, prompt):
        try:
            return self.replay.generate(system, prompt)
        except Exception as e:
            self.error = e
            raise


def llm_parse_fn(llm, timeout_s: float):
    """parse(text) for the M3 pipeline (guard + LLM parser) on a given model."""
    parser = LLMEditParser(llm, timeout_s=timeout_s)

    def parse(text):
        result = parser.parse(text, today=TODAY)
        if isinstance(llm, _ReplayGuard) and llm.error is not None:
            raise llm.error
        return result

    return parse


def run(requests, menu, catalog, *, replay=None) -> dict:
    """Score the regex baseline and, if a recording is given, the M3 pipeline."""
    current = base_plan(menu)
    guarded = regex_parser.GuardedRegexParser()
    parsers = {
        "regex": evaluate_parser(regex_parser.parse, requests, menu, catalog, current),
        "guarded_regex": evaluate_parser(
            lambda text: guarded.parse(text), requests, menu, catalog, current
        ),
    }
    model = None
    if replay is not None:
        parsers["llm"] = evaluate_parser(
            llm_parse_fn(_ReplayGuard(replay), timeout_s=LIVE_TIMEOUT_S),
            requests,
            menu,
            catalog,
            current,
        )
        model = getattr(replay, "model", None)
    counts = {
        c: sum(r["category"] == c for r in requests) for c in ("normal", "ambiguous", "adversarial")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "requests": counts,
        "model": model,
        "targets": {m: {"pass_if": op, "value": v} for m, _, op, v in TARGETS},
        "parsers": parsers,
        "replan": replan_timing(requests, menu, current),
    }


def render_markdown(report: dict) -> str:
    """The M3 results table (m3.md, the CI job summary and the README block)."""
    names = {
        "regex": "Regex baseline",
        "guarded_regex": "Guard + regex (no model)",
        "llm": "M3 (guard + LLM)",
    }
    cols = [n for n in ("regex", "guarded_regex", "llm") if n in report["parsers"]]
    counts = report["requests"]
    lines = [
        "## M3 plan edits",
        "",
        f"{counts['normal']} normal, {counts['ambiguous']} ambiguous and "
        f"{counts['adversarial']} adversarial requests"
        + (f"; LLM answers recorded from `{report['model']}`." if report.get("model") else "."),
        "",
        "| Metric | Target | " + " | ".join(names[c] for c in cols) + " |",
        "|---|---|" + "---|" * len(cols),
    ]
    for metric, label, op, value in TARGETS:
        cells = []
        for c in cols:
            got = report["parsers"][c][metric]
            ok = got is not None and (got >= value if op == ">=" else got <= value)
            shown = (
                "n/a" if got is None else (f"{got:.1f}%" if metric.endswith("_pct") else f"{got}")
            )
            cells.append(f"{shown} {'PASS' if ok else 'FAIL'}")
        target = f"{'≥' if op == '>=' else '≤'} {value}{'%' if metric.endswith('_pct') else ''}"
        lines.append(f"| {label} | {target} | {' | '.join(cells)} |")
    lines.append(
        "| Meals outside the edit that changed | 0 | "
        + " | ".join(str(report["parsers"][c]["pinned_changed"]) for c in cols)
        + " |"
    )
    replan = report["replan"]
    lines += [
        "",
        f"Re-plan time for the {replan['one_day_edits']} one-day edits, excluding the LLM call: "
        f"p95 **{_secs(replan['p95_pinned_s'])}** with the rest of the week pinned (target ≤ 2 s), "
        f"against {_secs(replan['p95_full_week_s'])} re-solving the whole week.",
    ]
    if "llm" not in report["parsers"]:
        lines += [
            "",
            "The LLM column is missing because no recording exists yet. Record one with "
            "`python -m eval.edits --live`.",
        ]
    return "\n".join(lines) + "\n"


def _secs(value):
    return "n/a" if value is None else f"{value:.2f} s"


def update_readme(markdown: str, readme: Path = README) -> bool:
    """Replace the M3 block in the README. Returns False if the markers are missing."""
    text = readme.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.S)
    if not pattern.search(text):
        return False
    body = markdown.split("\n", 2)[2].strip()  # drop the "## M3 plan edits" heading
    readme.write_text(pattern.sub(f"{README_START}\n{body}\n{README_END}", text), encoding="utf-8")
    return True


def failures(report: dict) -> list[str]:
    """Why CI should fail: any broken rule or changed pinned meal, for any parser."""
    problems = []
    for name, metrics in report["parsers"].items():
        if metrics["violations"]:
            problems.append(f"{name}: {metrics['violations']} rule violation(s) after edits")
        if metrics["pinned_changed"]:
            problems.append(f"{name}: {metrics['pinned_changed']} meal(s) outside an edit changed")
    return problems


def record(requests, recording: Path = RECORDING):
    """Run the M3 parser on the app's live LLM and save every response."""
    import llm_toolkit

    from eval.baselines import RecordingLLM

    live = llm_toolkit.LLM(tokens=300)
    recorder = RecordingLLM(live, recording)
    print(
        f"Recording with {recorder.model} ({live.provider}); {recorder.resumed} already recorded",
        file=sys.stderr,
    )
    parse = llm_parse_fn(recorder, timeout_s=LIVE_TIMEOUT_S)
    for done, req in enumerate(requests, start=1):
        parse(req["text"])
        print(f"  {done}/{len(requests)} {req['id']}", file=sys.stderr, flush=True)
    recorder.finish()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate plain-English plan edits (issue #8).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--live", action="store_true", help="record the app's LLM first")
    parser.add_argument("--readme", action="store_true", help="refresh the M3 table in README.md")
    args = parser.parse_args(argv)

    import menu_generation  # the database the app and M0 read

    from eval.baselines import RecordingError, ReplayLLM

    requests = load_requests()
    if args.live:
        try:
            record(requests)
        except RecordingError as e:
            sys.exit(str(e))
    replay = ReplayLLM(RECORDING) if RECORDING.exists() else None
    if replay is not None:
        replay.model = json.loads(RECORDING.read_text())["model"]
    report = run(
        requests,
        load_menu(menu_generation.db_file),
        load_catalog(menu_generation.db_file),
        replay=replay,
    )

    markdown = render_markdown(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "m3.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (args.out / "m3.md").write_text(markdown)
    print(markdown)
    if args.readme and not update_readme(markdown):
        print(f"No {README_START} block in the README; it was not updated.", file=sys.stderr)
    problems = failures(report)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
