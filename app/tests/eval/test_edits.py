"""The M3 plan-edit evaluation (eval.edits), on the seed menu with a few requests."""

import json

import pytest

import eval.edits as edits_eval
import eval.run
from eval.baselines import RecordingLLM, ReplayLLM, StaleRecording
from eval.catalog import load_catalog
from planner.edits.resolve import to_rule
from planner.edits.result import ParseResult
from planner.edits.schema import ParsedRequest
from planner.menu import load_menu
from scripts.init_db import SEED_FILE, init_db

REQUESTS = edits_eval.load_requests()
BY_ID = {r["id"]: r for r in REQUESTS}
SAMPLE = [BY_ID[i] for i in ("n01", "n02", "n04", "a01", "x01", "x06")]


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    db = tmp_path_factory.mktemp("m3") / "seed.db"
    init_db(db_file=str(db), seed_file=SEED_FILE)
    return load_menu(db), load_catalog(db), db


def oracle_reply(text):
    """What a perfect model would answer, as JSON."""
    req = next(r for r in REQUESTS if r["text"] == text)
    if req["category"] == "normal":
        return {"action": "edit", "edits": req["expected"]}
    if req["category"] == "ambiguous":
        return {"action": "clarify", "question": "What should change?"}
    return {"action": "refuse", "reason": "no"}


class OracleLLM:
    model_name = "oracle"

    def generate(self, system, prompt):
        text = prompt.split("Request: ")[-1].strip()
        return json.dumps(oracle_reply(text))


def test_the_dataset_has_40_normal_10_ambiguous_10_adversarial_requests(seed):
    menu = seed[0]
    assert [
        sum(r["category"] == c for r in REQUESTS) for c in ("normal", "ambiguous", "adversarial")
    ] == [40, 10, 10]
    assert len({r["id"] for r in REQUESTS}) == 60
    for r in REQUESTS:
        if r["category"] == "normal":
            parsed = ParsedRequest.model_validate({"action": "edit", "edits": r["expected"]})
            window = edits_eval.plan_request().dates()
            for e in parsed.edits:
                to_rule(e, window, menu)  # every named dish and restaurant exists


def test_a_perfect_parser_scores_100_with_no_violations(seed):
    menu, catalog, _ = seed
    current = edits_eval.base_plan(menu)

    def perfect(text):
        reply = oracle_reply(text)
        if reply["action"] == "edit":
            return ParseResult("edit", tuple(ParsedRequest.model_validate(reply).edits))
        return ParseResult(reply["action"], message="x")

    metrics = edits_eval.evaluate_parser(perfect, SAMPLE, menu, catalog, current)
    assert (metrics["parse_exact_pct"], metrics["clarify_pct"], metrics["refused_pct"]) == (
        100,
        100,
        100,
    )
    assert metrics["violations"] == 0 and metrics["pinned_changed"] == 0
    assert metrics["edits_applied"] == 3


def test_edits_from_any_request_are_applied_and_checked(seed):
    """The regex baseline turns an adversarial request into edits; they still break no rule."""
    menu, catalog, _ = seed
    current = edits_eval.base_plan(menu)
    metrics = edits_eval.evaluate_parser(
        edits_eval.regex_parser.parse, SAMPLE, menu, catalog, current
    )
    assert metrics["refused_pct"] == 0 and metrics["violations"] == 0


def test_recorded_llm_answers_replay_without_a_model(seed, tmp_path):
    menu, catalog, _ = seed
    cassette = tmp_path / "m3.json"
    recorder = RecordingLLM(OracleLLM(), cassette)
    parse = edits_eval.llm_parse_fn(recorder, timeout_s=30)
    for r in SAMPLE:
        parse(r["text"])
    recorder.finish()

    replay = ReplayLLM(cassette)
    replay.model = "oracle"
    report = edits_eval.run(SAMPLE, menu, catalog, replay=replay)

    llm = report["parsers"]["llm"]
    assert (llm["parse_exact_pct"], llm["clarify_pct"], llm["refused_pct"]) == (100, 100, 100)
    assert report["model"] == "oracle"
    assert edits_eval.failures(report) == []
    md = edits_eval.render_markdown(report)
    assert "M3 (guard + LLM)" in md and "recorded from `oracle`" in md


def test_a_stale_recording_stops_the_eval(tmp_path):
    cassette = tmp_path / "empty.json"
    cassette.write_text(json.dumps({"model": "x", "calls": {}}))
    parse = edits_eval.llm_parse_fn(edits_eval._ReplayGuard(ReplayLLM(cassette)), timeout_s=5)
    with pytest.raises(StaleRecording):
        parse("make Monday vegan")


def test_the_report_flags_violations_and_changed_pins():
    report = {
        "parsers": {
            "llm": {"violations": 2, "pinned_changed": 1},
            "regex": {"violations": 0, "pinned_changed": 0},
        }
    }
    assert edits_eval.failures(report) == [
        "llm: 2 rule violation(s) after edits",
        "llm: 1 meal(s) outside an edit changed",
    ]


def test_p95_uses_nearest_rank():
    assert edits_eval.p95([]) is None
    assert edits_eval.p95([float(i) for i in range(1, 21)]) == 19.0


def test_the_readme_block_is_replaced(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"before\n{edits_eval.README_START}\nold\n{edits_eval.README_END}\nafter\n")
    assert edits_eval.update_readme("## M3 plan edits\n\nnew table\n", readme)
    assert (
        readme.read_text()
        == f"before\n{edits_eval.README_START}\nnew table\n{edits_eval.README_END}\nafter\n"
    )
    assert not edits_eval.update_readme("x\n\ny", _no_markers(tmp_path))


def _no_markers(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text("nothing here\n")
    return path


def test_main_writes_results_and_exits_0_without_a_recording(seed, tmp_path, monkeypatch):
    _, _, db = seed
    import menu_generation

    monkeypatch.setattr(menu_generation, "db_file", str(db))
    monkeypatch.setattr(edits_eval, "load_requests", lambda: SAMPLE)
    monkeypatch.setattr(edits_eval, "RECORDING", tmp_path / "missing.json")

    assert edits_eval.main(["--out", str(tmp_path)]) == 0

    md = (tmp_path / "m3.md").read_text()
    assert "Regex baseline" in md and "no recording exists yet" in md
    assert json.loads((tmp_path / "m3.json").read_text())["parsers"]["regex"]["violations"] == 0


def test_the_m0_report_includes_the_m3_results(tmp_path, monkeypatch):
    (tmp_path / "m3.md").write_text("## M3 plan edits\n\nedits table\n")
    monkeypatch.setattr(eval.run, "run", lambda *a, **k: {"fake": True})
    monkeypatch.setattr(eval.run, "render_markdown", lambda report: "# M0 results\n")
    monkeypatch.setattr(eval.run, "load_catalog", lambda path: None)
    monkeypatch.setattr(eval.run, "RECORDING", tmp_path / "rec.json")
    (tmp_path / "rec.json").write_text(json.dumps({"model": None, "calls": {}}))
    assert eval.run.main(["--out", str(tmp_path)]) == 0
    assert "edits table" in (tmp_path / "m0.md").read_text()
