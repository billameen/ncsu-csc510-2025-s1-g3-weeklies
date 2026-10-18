"""
Baseline planners the new planner is compared against (GitHub issue #5).

Every planner takes (profile, catalog, seed) and returns the planned meals, or None to answer
"no valid week".
"""

import hashlib
import json
import random
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from Flask_app import parse_generated_menu
from menu_generation import MenuGenerator

from eval.catalog import Catalog
from eval.profiles import Profile, user_seed
from eval.validate import MEAL_TIMES, WEEK_START, WEEKDAYS, Meal, allergens_found, is_open

# How v1 hears about the user's budget and calorie target: as preference text, the way a user
# would type them. Changing this text changes every prompt, so the recording must be redone.
V1_PREFERENCES = "{kcal} kcal per day; ${budget} for all 21 meals this week, tax and fees included"

# Start of the error v1's MenuGenerator raises when the LLM never picks a usable item.
V1_GAVE_UP = "LLM has failed"


def random_safe(profile: Profile, catalog: Catalog, seed: int) -> tuple[Meal, ...]:
    """
    B1: for each slot, a random in-stock, allergen-free item from a restaurant open at that
    meal. No LLM and no budget or calorie logic. It reuses the validator's allergen and hours
    checks: B1 is a reference point, not the planner under test, so its misses show what
    ignoring budget and calories costs. A slot with no such item is left empty.
    """
    rng = random.Random(user_seed(seed, profile.user_id))
    safe = [i for i in catalog.items.values() if not allergens_found(i, profile.allergens)]
    meals = []
    for day in WEEKDAYS:
        for meal in MEAL_TIMES:
            choices = [i for i in safe if is_open(catalog, i, day, meal)]
            if choices:
                meals.append(Meal(day, meal, rng.choice(choices).itm_id))
    return tuple(meals)


def v1_llm(profile: Profile, catalog: Catalog, seed: int, *, llm) -> tuple[Meal, ...]:
    """
    B2: the v1 MenuGenerator as shipped, for one week, with budget and calories passed in as
    preference text. catalog is unused: v1 reads the menu from the app's database itself, as
    it does in production. v1 samples items with the global random module, so it is seeded
    per user (and the previous state restored) to make the prompts, and therefore a recorded
    run, reproducible. If v1 gives up on a meal, its week is lost and comes back empty.
    """
    state = random.getstate()
    random.seed(user_seed(seed, profile.user_id))
    try:
        menu = MenuGenerator(llm=llm).update_menu(
            menu="",
            preferences=V1_PREFERENCES.format(
                kcal=profile.kcal_target, budget=profile.budget_dollars
            ),
            allergens=",".join(profile.allergens),
            date=WEEK_START.isoformat(),
            meal_numbers=list(MEAL_TIMES),
            number_of_days=len(WEEKDAYS),
        )
    except RuntimeError as e:
        if not str(e).startswith(V1_GAVE_UP):
            raise
        return ()
    finally:
        random.setstate(state)

    meals = []
    for day_str, entries in parse_generated_menu(menu).items():
        offset = (date.fromisoformat(day_str) - WEEK_START).days
        # A date outside the week keeps its own name, so the validator reports it as extra.
        day = WEEKDAYS[offset] if 0 <= offset < len(WEEKDAYS) else day_str
        meals.extend(Meal(day, e["meal"], e["itm_id"]) for e in entries)
    return tuple(meals)


class StaleRecording(Exception):
    """A prompt was not in the recording: the menu data or v1's prompts changed since."""


class RecordingLLM:
    """Wraps a real LLM and records each response with its latency, for ReplayLLM."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = defaultdict(list)

    def generate(self, system: str, prompt: str) -> str:
        start = time.perf_counter()
        response = self.inner.generate(system, prompt)
        latency = time.perf_counter() - start
        self.calls[_prompt_key(system, prompt)].append({"response": response, "latency_s": latency})
        return response

    def save(self, path: str | Path):
        """Write the recording. Only a hash of each prompt is stored, not its text."""
        recording = {"model": getattr(self.inner, "model_name", None), "calls": self.calls}
        Path(path).write_text(json.dumps(recording, indent=1, sort_keys=True) + "\n")


class ReplayLLM:
    """
    Answers prompts from a RecordingLLM recording, in the order they were recorded, without an
    API key. recorded_seconds adds up the recorded latency of every response given so far.
    """

    def __init__(self, path: str | Path):
        self.calls = json.loads(Path(path).read_text())["calls"]
        self.used = defaultdict(int)
        self.recorded_seconds = 0.0

    def generate(self, system: str, prompt: str) -> str:
        key = _prompt_key(system, prompt)
        recorded = self.calls.get(key, [])
        if self.used[key] >= len(recorded):
            raise StaleRecording(
                "The B2 recording has no response for this prompt: the menu data or v1's "
                "prompts changed since it was recorded. Re-record it with "
                "`python -m eval.run --seed <seed> --record` (needs OPENAI_API_KEY)."
            )
        call = recorded[self.used[key]]
        self.used[key] += 1
        self.recorded_seconds += call["latency_s"]
        return call["response"]


def _prompt_key(system: str, prompt: str) -> str:
    return hashlib.sha256(f"{system}\0{prompt}".encode()).hexdigest()
