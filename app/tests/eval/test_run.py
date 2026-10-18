import json
import numbers
import re
import sqlite3

import pytest

import eval.run
import menu_generation
from eval.baselines import ReplayLLM, random_safe
from eval.catalog import load_catalog
from eval.feasibility import cheapest_week, is_feasible
from eval.profiles import generate_profiles
from eval.run import (
    Planner,
    UserResult,
    evaluate,
    m0_planners,
    render_markdown,
    run,
    summarize,
)
from eval.validate import WEEKDAYS, Violation, ViolationKind

PLANNER_METRICS = {
    "h1_valid_pct",
    "h2_median_distinct",
    "h3_p95_s",
    "h4_no_plan_pct",
    "overall_valid_pct",
    "users_with_violation",
}


@pytest.fixture
def menu_db(tmp_path, monkeypatch):
    """A 30-item menu, open all week, that both the eval and v1 read."""
    db = tmp_path / "menu.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE Restaurant (rtr_id INTEGER, hours TEXT, status TEXT);
        CREATE TABLE MenuItem (itm_id INTEGER, rtr_id INTEGER, name TEXT, description TEXT,
                               price INTEGER, calories INTEGER, instock INTEGER, allergens TEXT);
        """
    )
    hours = json.dumps({day: [600, 2300] for day in WEEKDAYS})
    conn.execute("INSERT INTO Restaurant VALUES (1, ?, 'Open')", (hours,))
    conn.executemany(
        "INSERT INTO MenuItem VALUES (?, 1, ?, 'tasty', ?, ?, 1, ?)",
        [
            (n, f"Dish {n}", 400 + 50 * n, 300 + 30 * n, "Dairy" if n % 5 == 0 else None)
            for n in range(1, 31)
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(menu_generation, "db_file", str(db))
    return db


def cheapest(profile, catalog, seed):
    """A planner that is right by construction: the feasibility check's own week, or None."""
    return cheapest_week(profile, catalog) if is_feasible(profile, catalog) else None


PLANNERS = [Planner("B1", random_safe), Planner("Cheapest", cheapest)]

REAL_LIVE_LLM = eval.run._live_llm  # kept before the command fixture replaces it


def small_run(menu_db, seed=510):
    return run(seed, load_catalog(menu_db), generate_profiles(seed)[:5], PLANNERS)


# --- evaluate ---


def test_evaluate_keeps_no_plan_answers_and_validates_weeks(menu_db):
    catalog = load_catalog(menu_db)
    profiles = generate_profiles(510)[:5]
    feasible = {p.user_id: False for p in profiles}

    results = evaluate(Planner("None", lambda p, c, s: None), profiles, catalog, 510, feasible)

    assert [r.user_id for r in results] == [p.user_id for p in profiles]
    assert all(r.meals is None and r.violations == () for r in results)
    assert all(r.seconds >= 0 for r in results)


def test_evaluate_adds_the_recorded_llm_time(menu_db):
    class Replay:
        recorded_seconds = 0.0

    replay = Replay()

    def plan(profile, catalog, seed):
        replay.recorded_seconds += 2.5
        return None

    profiles = generate_profiles(510)[:2]
    feasible = {p.user_id: False for p in profiles}
    results = evaluate(Planner("B2", plan, replay), profiles, load_catalog(menu_db), 510, feasible)

    assert all(2.5 <= r.seconds < 3.5 for r in results)


def test_evaluate_stops_when_an_infeasible_user_gets_a_valid_week(menu_db):
    catalog = load_catalog(menu_db)
    profile = next(p for p in generate_profiles(510) if cheapest(p, catalog, 510))

    with pytest.raises(RuntimeError, match="feasibility check"):
        evaluate(Planner("Cheapest", cheapest), [profile], catalog, 510, {profile.user_id: False})


# --- summarize ---


def test_summary_counts_users_per_violation_kind_and_lists_every_kind():
    results = [
        UserResult(1, True, (), (Violation(ViolationKind.OVER_BUDGET),) * 2, 1.0),
        UserResult(2, True, (), (Violation(ViolationKind.OVER_BUDGET),), 1.0),
        UserResult(3, False, None, (), 1.0),
    ]

    counts = summarize(results)["users_with_violation"]

    assert list(counts) == [kind.value for kind in ViolationKind]
    assert counts["over_budget"] == 2
    assert sum(counts.values()) == 2


# --- report and markdown ---


def test_report_schema(menu_db):
    report = small_run(menu_db)

    assert set(report) == {"schema_version", "seed", "users", "thresholds", "planners"}
    assert report["schema_version"] == 1 and report["seed"] == 510
    assert set(report["users"]) == {"total", "feasible", "hard", "hard_feasible"}
    assert report["users"]["total"] == 5
    assert set(report["thresholds"]) == {
        "h1_valid_pct",
        "h2_median_distinct",
        "h3_p95_s",
        "h4_no_plan_pct",
    }
    assert all(set(t) == {"pass_if", "value"} for t in report["thresholds"].values())
    assert list(report["planners"]) == ["B1", "Cheapest"]
    for metrics in report["planners"].values():
        assert set(metrics) == PLANNER_METRICS
        for key in PLANNER_METRICS - {"users_with_violation"}:
            assert metrics[key] is None or isinstance(metrics[key], numbers.Real)
    json.dumps(report)  # serializable as is


def test_a_planner_that_is_right_by_construction_passes_h1_and_h4(menu_db):
    report = small_run(menu_db)
    users = report["users"]
    cheapest_metrics = report["planners"]["Cheapest"]

    if users["feasible"]:
        assert cheapest_metrics["h1_valid_pct"] == 100.0
    if users["feasible"] < users["total"]:
        assert cheapest_metrics["h4_no_plan_pct"] == 100.0


def test_two_runs_match_apart_from_timing(menu_db):
    def without_timing(report):
        for metrics in report["planners"].values():
            metrics.pop("h3_p95_s")
        return report

    assert without_timing(small_run(menu_db)) == without_timing(small_run(menu_db))


def test_markdown_has_the_results_table(menu_db):
    md = render_markdown(small_run(menu_db))
    lines = md.splitlines()

    assert lines[0] == "# M0 results"
    assert "| Hypothesis | Pass if | Baselines | B1 | Cheapest |" in lines
    for hypothesis in ("H1", "H2", "H3", "H4"):
        row = next(line for line in lines if line.startswith(f"| {hypothesis} "))
        assert re.search(r"(PASS|FAIL|n/a)", row)
    assert "| Violation | B1 | Cheapest |" in lines


def test_markdown_marks_pass_and_fail_against_the_threshold(menu_db):
    report = small_run(menu_db)
    report["planners"]["B1"]["h3_p95_s"] = 0.5
    report["planners"]["Cheapest"]["h3_p95_s"] = 9.0

    row = next(line for line in render_markdown(report).splitlines() if line.startswith("| H3 "))

    assert "0.500 s PASS" in row and "9.000 s FAIL" in row


# --- the command ---


def test_m0_planners_are_b1_and_b2_with_b2_adding_its_recorded_llm_time(tmp_path):
    (tmp_path / "rec.json").write_text(json.dumps({"model": None, "calls": {}}))
    replay = ReplayLLM(tmp_path / "rec.json")

    planners = m0_planners(replay)

    assert [p.name for p in planners] == ["B1", "B2"]
    assert planners[0].replay is None and planners[1].replay is replay


class FakeOpenAI:
    """Stands in for the app's LLM (here OpenAI) while recording: always picks the first item."""

    provider = "openai"
    model_name = "fake-gpt"

    def generate(self, system, prompt):
        return re.search(r"CSV CONTEXT:\nitem_id[^\n]*\n(\d+),", prompt).group(1)


@pytest.fixture
def command(menu_db, tmp_path, monkeypatch):
    """main() on the small menu with 5 users, recording to a temporary file."""
    monkeypatch.setattr(eval.run, "RECORDING", tmp_path / "fixtures" / "b2.json")
    monkeypatch.setattr(eval.run, "generate_profiles", lambda seed: generate_profiles(seed)[:5])
    monkeypatch.setattr(eval.run, "_live_llm", FakeOpenAI)
    return tmp_path


def read_report(out):
    return json.loads((out / "m0.json").read_text())


def test_record_then_replay_gives_the_same_results(command):
    assert eval.run.main(["--record", "--out", str(command / "rec")]) == 0
    assert (command / "fixtures" / "b2.json").exists()
    assert eval.run.main(["--out", str(command / "replay")]) == 0

    recorded, replayed = read_report(command / "rec"), read_report(command / "replay")
    for report in (recorded, replayed):
        for metrics in report["planners"].values():
            metrics.pop("h3_p95_s")
    assert replayed == recorded
    assert (command / "replay" / "m0.md").read_text().startswith("# M0 results")


def test_baseline_regression_sets_the_exit_code(command):
    eval.run.main(["--record", "--out", str(command / "base")])
    baseline = read_report(command / "base")
    assert baseline["users"]["feasible"] > 0, "the small menu needs feasible users for H1"

    same = command / "same.json"
    same.write_text(json.dumps(baseline))
    assert eval.run.main(["--out", str(command / "a"), "--baseline", str(same)]) == 0

    baseline["planners"]["B1"]["h1_valid_pct"] += 10
    better = command / "better.json"
    better.write_text(json.dumps(baseline))
    assert eval.run.main(["--out", str(command / "b"), "--baseline", str(better)]) == 1


def test_replay_without_a_recording_says_how_to_record(command):
    with pytest.raises(SystemExit, match="--record"):
        eval.run.main(["--out", str(command / "out")])


def test_record_uses_the_apps_own_llm_and_names_its_model(command, monkeypatch):
    # No OPENAI_API_KEY, so llm_toolkit picks the local model, as the app does.
    built = []

    class LocalModel(FakeOpenAI):
        provider = "local"
        model_name = "ibm-granite/granite-4.0-h-350M"

        def __init__(self, tokens):
            built.append(tokens)

    monkeypatch.setattr(eval.run, "_live_llm", REAL_LIVE_LLM)
    monkeypatch.setattr(eval.run.llm_toolkit, "LLM", LocalModel)

    assert eval.run.main(["--record", "--out", str(command / "out")]) == 0

    assert built == [500]  # the token limit /generate_plan uses
    recording = json.loads((command / "fixtures" / "b2.json").read_text())
    assert recording["model"] == "ibm-granite/granite-4.0-h-350M"


def test_record_keeps_what_it_has_if_the_llm_switched_models_midway(command, monkeypatch):
    class FallsBackOnThirdCall(FakeOpenAI):
        calls = 0

        def generate(self, system, prompt):
            FallsBackOnThirdCall.calls += 1
            if FallsBackOnThirdCall.calls == 3:  # what llm_toolkit does after an OpenAI error
                self.provider, self.model_name = "local", "ibm-granite/granite-4.0-h-350M"
            return super().generate(system, prompt)

    monkeypatch.setattr(eval.run, "_live_llm", FallsBackOnThirdCall)

    with pytest.raises(SystemExit, match="switched from fake-gpt to ibm-granite"):
        eval.run.main(["--record", "--out", str(command / "out")])
    recording = json.loads((command / "fixtures" / "b2.json").read_text())
    assert recording["model"] == "fake-gpt"
    assert sum(len(answers) for answers in recording["calls"].values()) == 2
    assert not (command / "out").exists()


def test_an_interrupted_recording_resumes_where_it_stopped(command, monkeypatch):
    class PowerCut(FakeOpenAI):
        calls = 0

        def generate(self, system, prompt):
            PowerCut.calls += 1
            if PowerCut.calls == 30:
                raise KeyboardInterrupt  # the laptop slept, or someone pressed Ctrl+C
            return super().generate(system, prompt)

    monkeypatch.setattr(eval.run, "_live_llm", PowerCut)
    with pytest.raises(KeyboardInterrupt):
        eval.run.main(["--record", "--out", str(command / "first")])

    class Counting(FakeOpenAI):
        calls = 0

        def generate(self, system, prompt):
            Counting.calls += 1
            return super().generate(system, prompt)

    monkeypatch.setattr(eval.run, "_live_llm", Counting)
    assert eval.run.main(["--record", "--out", str(command / "resumed")]) == 0
    assert Counting.calls == 5 * 21 - 29  # only the meals the first run never got to

    monkeypatch.setattr(eval.run, "RECORDING", command / "clean.json")
    assert eval.run.main(["--record", "--out", str(command / "clean")]) == 0
    resumed, clean = read_report(command / "resumed"), read_report(command / "clean")
    for report in (resumed, clean):
        for metrics in report["planners"].values():
            metrics.pop("h3_p95_s")
    assert resumed == clean


def test_a_finished_recording_drops_responses_the_run_no_longer_asks_for(command):
    assert eval.run.main(["--record", "--seed", "510", "--out", str(command / "a")]) == 0
    assert eval.run.main(["--record", "--seed", "511", "--out", str(command / "b")]) == 0

    recording = json.loads((command / "fixtures" / "b2.json").read_text())
    assert sum(len(answers) for answers in recording["calls"].values()) == 5 * 21
