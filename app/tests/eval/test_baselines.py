import json
import random
import re
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

import eval.baselines
import menu_generation
from eval.baselines import (
    RecordingError,
    RecordingLLM,
    ReplayLLM,
    StaleRecording,
    random_safe,
    v1_llm,
)
from eval.catalog import Catalog, Item, Restaurant, load_catalog
from eval.profiles import Profile, generate_profiles
from eval.validate import MEAL_TIMES, WEEKDAYS, Meal, ViolationKind, validate_week

SEED_SQL = Path(__file__).resolve().parents[2] / "db" / "seed.sql"

OPEN_ALL_WEEK = {day: (600, 2300) for day in WEEKDAYS}

# B1 knows nothing about money or calories, so only these may go wrong in its weeks.
BUDGET_OR_CALORIES = {ViolationKind.OVER_BUDGET, ViolationKind.UNDER_KCAL, ViolationKind.OVER_KCAL}


def item(itm_id, rtr_id=1, allergens=()):
    return Item(itm_id=itm_id, rtr_id=rtr_id, price_cents=1000, calories=700, allergens=allergens)


# Items 1-20 are safe and always open. Item 21 has an allergen, item 22 is tagged "Egg", item 23
# comes from a restaurant closed all week and item 24 from one missing from the catalog.
CATALOG = Catalog(
    items={
        **{n: item(n) for n in range(1, 21)},
        21: item(21, allergens=("Dairy",)),
        22: item(22, allergens=("Egg",)),
        23: item(23, rtr_id=2),
        24: item(24, rtr_id=99),
    },
    restaurants={
        1: Restaurant(rtr_id=1, hours=OPEN_ALL_WEEK),
        2: Restaurant(rtr_id=2, hours={}),
    },
)

PROFILE = Profile(
    user_id=1, kcal_target=2100, budget_dollars=650, allergens=("Dairy", "Eggs"), hard=False
)


def test_plans_one_meal_per_slot_in_week_order():
    meals = random_safe(PROFILE, CATALOG, seed=510)

    assert [(m.day, m.meal) for m in meals] == [(d, n) for d in WEEKDAYS for n in MEAL_TIMES]


def test_same_seed_gives_the_same_week():
    assert random_safe(PROFILE, CATALOG, seed=510) == random_safe(PROFILE, CATALOG, seed=510)


def test_different_seeds_and_different_users_give_different_weeks():
    week = random_safe(PROFILE, CATALOG, seed=510)
    other_user = replace(PROFILE, user_id=2)  # same needs, so only the id can change the week

    assert random_safe(PROFILE, CATALOG, seed=511) != week
    assert random_safe(other_user, CATALOG, seed=510) != week


def test_picks_at_random_among_the_safe_open_items():
    picked = {m.itm_id for seed in range(10) for m in random_safe(PROFILE, CATALOG, seed=seed)}

    assert picked == set(range(1, 21))


@pytest.mark.parametrize("seed", range(20))
def test_never_picks_an_allergen_or_a_closed_restaurant(seed):
    meals = random_safe(PROFILE, CATALOG, seed=seed)

    assert {m.itm_id for m in meals}.isdisjoint({21, 22, 23, 24})
    assert validate_week(meals, PROFILE, CATALOG) == []


def test_slot_with_no_safe_open_item_is_left_empty():
    # The only restaurant opens at 1100, after breakfast.
    late = Catalog(
        items={1: item(1)},
        restaurants={1: Restaurant(rtr_id=1, hours={d: (1100, 2300) for d in WEEKDAYS})},
    )

    meals = random_safe(PROFILE, late, seed=510)

    assert [(m.day, m.meal) for m in meals] == [(d, n) for d in WEEKDAYS for n in (2, 3)]
    kinds = {v.kind for v in validate_week(meals, PROFILE, late)}
    assert kinds == {ViolationKind.MISSING_MEAL}


def test_on_the_seed_data_only_budget_calories_or_empty_slots_go_wrong(tmp_path):
    db = tmp_path / "seed.db"
    conn = sqlite3.connect(db)
    conn.executescript(SEED_SQL.read_text())
    conn.close()
    catalog = load_catalog(db)

    for profile in generate_profiles(510):
        violations = validate_week(random_safe(profile, catalog, seed=510), profile, catalog)
        assert {v.kind for v in violations} <= BUDGET_OR_CALORIES | {ViolationKind.MISSING_MEAL}


# --- B2: the v1 LLM planner, with recorded LLM responses ---


class ScriptedLLM:
    """Answers each prompt from a list in turn, and keeps the prompts."""

    model_name = "scripted"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, system, prompt):
        self.prompts.append(prompt)
        return self.responses[(len(self.prompts) - 1) % len(self.responses)]


class FirstItemLLM:
    """Picks the first item v1 offers, like a model that always takes the top option."""

    def __init__(self):
        self.prompts = []

    def generate(self, system, prompt):
        self.prompts.append(prompt)
        return re.search(r"CSV CONTEXT:\nitem_id[^\n]*\n(\d+),", prompt).group(1)


def test_replay_returns_recorded_responses_in_order(tmp_path):
    recorder = RecordingLLM(ScriptedLLM("7", "8"), tmp_path / "rec.json")
    assert [recorder.generate("sys", "same prompt") for _ in range(2)] == ["7", "8"]
    recorder.finish()

    replay = ReplayLLM(tmp_path / "rec.json")

    assert [replay.generate("sys", "same prompt") for _ in range(2)] == ["7", "8"]


def test_replay_of_an_unrecorded_prompt_raises(tmp_path):
    recorder = RecordingLLM(ScriptedLLM("7"), tmp_path / "rec.json")
    recorder.generate("sys", "recorded")
    recorder.finish()
    replay = ReplayLLM(tmp_path / "rec.json")

    with pytest.raises(StaleRecording, match="Re-record"):
        replay.generate("sys", "never recorded")
    with pytest.raises(StaleRecording):
        replay.generate("other system", "recorded")


def test_replay_past_the_recorded_count_raises(tmp_path):
    recorder = RecordingLLM(ScriptedLLM("7"), tmp_path / "rec.json")
    recorder.generate("sys", "once")
    recorder.finish()
    replay = ReplayLLM(tmp_path / "rec.json")
    replay.generate("sys", "once")

    with pytest.raises(StaleRecording):
        replay.generate("sys", "once")


def test_recording_keeps_latency_and_model_and_replay_adds_up_latency(tmp_path):
    recorder = RecordingLLM(ScriptedLLM("7"), tmp_path / "rec.json")
    recorder.generate("sys", "a")
    recorder.generate("sys", "b")
    recorder.finish()

    saved = json.loads((tmp_path / "rec.json").read_text())
    latencies = [call["latency_s"] for calls in saved["calls"].values() for call in calls]
    assert saved["model"] == "scripted"
    assert len(latencies) == 2 and all(s >= 0 for s in latencies)

    replay = ReplayLLM(tmp_path / "rec.json")
    assert replay.recorded_seconds == 0
    replay.generate("sys", "a")
    replay.generate("sys", "b")
    assert replay.recorded_seconds == pytest.approx(sum(latencies))


def test_recording_stores_no_prompt_text(tmp_path):
    recorder = RecordingLLM(ScriptedLLM("7"), tmp_path / "rec.json")
    recorder.generate("sys", "private prompt text")
    recorder.finish()

    assert "private prompt text" not in (tmp_path / "rec.json").read_text()


class NoLLM:
    """Fails the test if the recording calls the LLM again."""

    model_name = "scripted"

    def generate(self, system, prompt):
        raise AssertionError(f"called the LLM again for {prompt!r}")


def recorded_responses(path):
    calls = json.loads(path.read_text())["calls"]
    return sorted(call["response"] for answers in calls.values() for call in answers)


def test_recording_is_saved_after_every_call(tmp_path):
    recorder = RecordingLLM(ScriptedLLM("7", "8"), tmp_path / "rec.json")

    recorder.generate("sys", "a")
    assert recorded_responses(tmp_path / "rec.json") == ["7"]
    recorder.generate("sys", "b")
    assert recorded_responses(tmp_path / "rec.json") == ["7", "8"]
    assert not list(tmp_path.glob("*.tmp"))  # written via a temporary file, then replaced


def test_recording_resumes_without_calling_the_llm_again(tmp_path):
    first = RecordingLLM(ScriptedLLM("7"), tmp_path / "rec.json")
    first.generate("sys", "a")  # then the run stops

    resumed = RecordingLLM(NoLLM(), tmp_path / "rec.json")
    assert resumed.resumed == 1
    assert resumed.generate("sys", "a") == "7"

    resumed.inner = ScriptedLLM("9")
    assert resumed.generate("sys", "b") == "9"
    resumed.finish()
    assert recorded_responses(tmp_path / "rec.json") == ["7", "9"]


def test_resume_keeps_the_order_of_repeated_prompts(tmp_path):
    first = RecordingLLM(ScriptedLLM("7", "8"), tmp_path / "rec.json")
    first.generate("sys", "same")
    first.generate("sys", "same")

    resumed = RecordingLLM(ScriptedLLM("9"), tmp_path / "rec.json")

    assert [resumed.generate("sys", "same") for _ in range(3)] == ["7", "8", "9"]


def test_finish_drops_responses_this_run_did_not_ask_for(tmp_path):
    old = RecordingLLM(ScriptedLLM("7"), tmp_path / "rec.json")
    old.generate("sys", "a")
    old.generate("sys", "no longer asked")

    rerun = RecordingLLM(NoLLM(), tmp_path / "rec.json")
    rerun.generate("sys", "a")
    rerun.finish()

    assert recorded_responses(tmp_path / "rec.json") == ["7"]


def test_resuming_a_recording_made_with_another_model_is_refused(tmp_path):
    RecordingLLM(ScriptedLLM("7"), tmp_path / "rec.json").generate("sys", "a")
    before = (tmp_path / "rec.json").read_text()

    class OtherModel(ScriptedLLM):
        model_name = "other"

    with pytest.raises(RecordingError, match="scripted"):
        RecordingLLM(OtherModel("7"), tmp_path / "rec.json")
    assert (tmp_path / "rec.json").read_text() == before


def test_a_response_from_a_model_that_switched_midway_is_not_saved(tmp_path):
    class SwitchesOnSecondCall(ScriptedLLM):
        def generate(self, system, prompt):
            if self.prompts:
                self.model_name = "local fallback"
            return super().generate(system, prompt)

    recorder = RecordingLLM(SwitchesOnSecondCall("7", "8"), tmp_path / "rec.json")
    recorder.generate("sys", "a")

    with pytest.raises(RecordingError, match="switched from scripted to local fallback"):
        recorder.generate("sys", "b")
    assert recorded_responses(tmp_path / "rec.json") == ["7"]


@pytest.fixture
def v1_menu(tmp_path, monkeypatch):
    """Point v1 at a 30-item menu that is open all week, so it samples 10 items per meal."""
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
        "INSERT INTO MenuItem VALUES (?, 1, ?, 'tasty', 1000, 700, 1, ?)",
        [(n, f"Dish {n}", "Dairy" if n == 1 else None) for n in range(1, 31)],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(menu_generation, "db_file", str(db))


def test_v1_plans_21_meals_in_week_order(v1_menu):
    meals = v1_llm(PROFILE, None, seed=510, llm=FirstItemLLM())

    assert [(m.day, m.meal) for m in meals] == [(d, n) for d in WEEKDAYS for n in MEAL_TIMES]


def test_v1_is_told_the_budget_calories_and_allergens(v1_menu):
    llm = FirstItemLLM()

    meals = v1_llm(PROFILE, None, seed=510, llm=llm)

    assert all("2100 kcal" in p and "$650" in p for p in llm.prompts)
    # Item 1 is the only Dairy item; v1's own filter keeps it out for this Dairy-avoiding user.
    assert all("\n1,Dish 1," not in p for p in llm.prompts)
    assert 1 not in {m.itm_id for m in meals}


def test_v1_prompts_depend_only_on_seed_and_user(v1_menu):
    def prompts(profile, seed):
        llm = FirstItemLLM()
        v1_llm(profile, None, seed=seed, llm=llm)
        return llm.prompts

    assert prompts(PROFILE, 510) == prompts(PROFILE, 510)
    assert prompts(PROFILE, 511) != prompts(PROFILE, 510)
    assert prompts(replace(PROFILE, user_id=2), 510) != prompts(PROFILE, 510)


def test_v1_replays_a_recorded_run_exactly(v1_menu, tmp_path):
    recorder = RecordingLLM(FirstItemLLM(), tmp_path / "rec.json")
    recorded = v1_llm(PROFILE, None, seed=510, llm=recorder)
    recorder.finish()

    replayed = v1_llm(PROFILE, None, seed=510, llm=ReplayLLM(tmp_path / "rec.json"))

    assert replayed == recorded


def test_v1_giving_up_is_an_empty_week_not_a_crash(v1_menu):
    meals = v1_llm(PROFILE, None, seed=510, llm=ScriptedLLM("I cannot choose"))

    assert meals == ()


def test_v1_with_a_stale_recording_crashes(v1_menu, tmp_path):
    (tmp_path / "rec.json").write_text(json.dumps({"model": None, "calls": {}}))

    with pytest.raises(StaleRecording):
        v1_llm(PROFILE, None, seed=510, llm=ReplayLLM(tmp_path / "rec.json"))


def test_v1_leaves_the_global_random_state_alone(v1_menu):
    random.seed(0)
    expected = random.random()

    random.seed(0)
    v1_llm(PROFILE, None, seed=510, llm=FirstItemLLM())

    assert random.random() == expected


def test_v1_errors_other_than_giving_up_propagate(v1_menu):
    class DownLLM:
        def generate(self, system, prompt):
            raise RuntimeError("API is down")

    with pytest.raises(RuntimeError, match="API is down"):
        v1_llm(PROFILE, None, seed=510, llm=DownLLM())


def test_v1_dates_map_to_weekdays_and_dates_outside_the_week_stay_dates(monkeypatch):
    class FixedMenu:
        def __init__(self, llm):
            pass

        def update_menu(self, **kwargs):
            return "[2026-10-19,5,1],[2026-10-25,6,3],[2026-10-18,7,2],[2026-10-26,8,1]"

    monkeypatch.setattr(eval.baselines, "MenuGenerator", FixedMenu)

    assert v1_llm(PROFILE, None, seed=510, llm=None) == (
        Meal("Mon", 1, 5),
        Meal("Sun", 3, 6),
        Meal("2026-10-18", 2, 7),
        Meal("2026-10-26", 1, 8),
    )
