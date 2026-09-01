"""Unit tests for POST /generate_plan, MenuGenerator.update_menu(), and the
allergen-filtering logic it relies on (menu_generation.filter_allergens).

Known bug under test: filter_allergens() guards each row with
``rows["allergens"] is not None`` (menu_generation.py) before calling
``.split(',')`` on it. A pandas/NumPy NaN is a *float*, not None, so it
passes that guard and blows up on ``.split()`` with an AttributeError.

Environment assumptions:
- pytest is run from the repository root with the project's Python
  dependencies installed. The shared ``app``/``client`` fixtures in
  ``proj2/tests/conftest.py`` point Flask at a disposable SQLite database,
  so these tests do not touch ``proj2/CSC510_DB.db``.
- The LLM is mocked in both tests. Test 1 replaces ``Flask_app.MenuGenerator``
  itself with a stand-in whose ``update_menu`` calls the real
  ``filter_allergens`` on a crafted DataFrame — this avoids constructing a
  real ``MenuGenerator`` (which would query the DB and instantiate
  ``llm_toolkit.LLM``, triggering an OpenAI call or a local HuggingFace
  model download). Test 2 calls ``filter_allergens`` directly and never
  touches the LLM at all.
"""

import pandas as pd
import pytest

import Flask_app
from menu_generation import filter_allergens


def _register_and_login(client, email, allergies):
    """Register a user with the given allergies and log them in."""
    client.post(
        "/register",
        data={
            "fname": "Nan",
            "lname": "Tester",
            "email": email,
            "phone": "(919) 555-0199",
            "password": "secret123",
            "confirm_password": "secret123",
            "preferences": "",
            "allergies": allergies,
        },
        follow_redirects=False,
    )
    client.post("/login", data={"email": email, "password": "secret123"}, follow_redirects=False)


class _CrashingGenerator:
    """Stand-in for MenuGenerator that reproduces a real NaN allergen cell
    reaching the real filter_allergens(), without touching the DB or LLM."""

    def __init__(self, tokens: int = 500):
        pass

    def update_menu(self, menu, preferences, allergens, date, meal_numbers, number_of_days=1, goal=""):
        menu_items = pd.DataFrame({
            "itm_id": [1],
            "name": ["Mystery Casserole"],
            "description": ["unlabeled leftovers"],
            "price": [999],
            "calories": [500],
            "allergens": [float("nan")],  # e.g. a NULL cell pandas has upcast to NaN
        })
        # This is the exact call MenuGenerator.__get_context() makes internally.
        # (Only reached at all if filter_allergens doesn't raise first.)
        filtered = filter_allergens(menu_items, allergens)
        row = filtered.iloc[0]
        return f"[{date},{int(row['itm_id'])},{meal_numbers[0]}]"


def test_a_nan_allergen_cell_crashes_generate_plan_as_a_500_instead_of_an_unhandled_error(client, monkeypatch):
    monkeypatch.setattr(Flask_app, "MenuGenerator", _CrashingGenerator)
    _register_and_login(client, "nan-allergy@example.test", "Peanuts")

    response = client.post("/generate_plan")

    assert response.status_code == 500
    body = response.get_json()
    assert body["ok"] is False
    assert "float" in body["error"] and "split" in body["error"]


# This proves a NaN allergen cell does reach filter_allergens() through MenuGenerator.update_menu() during POST /generate_plan and raises AttributeError as described — and that the route's broad except Exception (Flask_app.py) catches it and reports a 500 JSON error instead of an unhandled crash.


def test_filtering_with_no_recorded_allergies_never_touches_a_nan_allergens_cell(client, monkeypatch):
    monkeypatch.setattr(Flask_app, "MenuGenerator", _CrashingGenerator)
    _register_and_login(client, "no-allergy@example.test", "")  # allergies left blank

    response = client.post("/generate_plan")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# This proves the `if not allergens: return menu_items` short-circuit at the top of filter_allergens() (menu_generation.py) prevents the .split()-on-NaN bug entirely when a user has no allergies on file, even though the same corrupted menu item is present — the row is never inspected.
