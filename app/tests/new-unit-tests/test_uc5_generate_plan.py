"""Unit tests for POST /generate_plan, MenuGenerator.update_menu(), and the
allergen-filtering logic it relies on (menu_generation.filter_allergens).

filter_allergens() used to guard each row with ``rows["allergens"] is not None``
before calling ``.split(',')``. A pandas/NumPy NaN is a *float*, not None, so it
passed that guard and raised AttributeError. It now checks for a real string. The
app also runs it in strict mode, which removes items whose allergens are unknown
for a user with allergies.

Environment assumptions:
- pytest is run from the repository root with the project's Python
  dependencies installed. The shared ``app``/``client`` fixtures in
  ``app/tests/conftest.py`` point Flask at a disposable SQLite database,
  so these tests do not touch ``app/CSC510_DB.db``.
- The LLM is never used. ``Flask_app.MenuGenerator`` is replaced with a
  stand-in whose ``update_menu`` calls the real ``filter_allergens`` on a
  crafted DataFrame -- this avoids constructing a real ``MenuGenerator``
  (which would query the DB and instantiate ``llm_toolkit.LLM``, triggering an
  OpenAI call or a local HuggingFace model download).
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


class _NanMenuGenerator:
    """Stand-in for MenuGenerator that sends a real NaN allergen cell through the
    real filter_allergens(), without touching the DB or LLM. It records the
    strict_allergens flag the route passed, and plans whichever item survives."""

    last_strict = None

    def __init__(self, tokens: int = 500, llm=None, strict_allergens: bool = False):
        self.strict_allergens = strict_allergens
        _NanMenuGenerator.last_strict = strict_allergens

    def update_menu(self, menu, preferences, allergens, date, meal_numbers, number_of_days=1, goal=""):
        menu_items = pd.DataFrame({
            "itm_id": [1, 2],
            "name": ["Mystery Casserole", "Plain Rice"],
            "description": ["unlabeled leftovers", "steamed rice"],
            "price": [999, 499],
            "calories": [500, 300],
            "allergens": [float("nan"), "Soy"],  # item 1: a NULL cell pandas has upcast to NaN
        })
        # This is the exact call MenuGenerator.__get_context() makes internally.
        filtered = filter_allergens(menu_items, allergens, strict=self.strict_allergens)
        row = filtered.iloc[0]
        return f"[{date},{int(row['itm_id'])},{meal_numbers[0]}]"


def _planned_item_id(client):
    with client.session_transaction() as sess:
        return int(sess["GeneratedMenu"].strip("[]").split(",")[1])


def test_a_nan_allergen_cell_no_longer_crashes_and_the_unknown_item_is_excluded(client, monkeypatch):
    monkeypatch.setattr(Flask_app, "MenuGenerator", _NanMenuGenerator)
    monkeypatch.setenv("PLANNER", "llm")  # these tests cover the v1 LLM planner

    _register_and_login(client, "nan-allergy@example.test", "Peanuts")

    response = client.post("/generate_plan")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert _NanMenuGenerator.last_strict is True
    # Item 1's allergens are unknown, so it cannot be shown to be peanut-free.
    assert _planned_item_id(client) == 2


# This proves a NaN allergen cell is handled safely during POST /generate_plan: no crash, the route asks for strict filtering, and the item with unknown allergens is not served to a user with allergies.


def test_a_user_with_no_recorded_allergies_can_still_be_served_an_unknown_allergen_item(client, monkeypatch):
    monkeypatch.setattr(Flask_app, "MenuGenerator", _NanMenuGenerator)
    monkeypatch.setenv("PLANNER", "llm")  # these tests cover the v1 LLM planner

    _register_and_login(client, "no-allergy@example.test", "")  # allergies left blank

    response = client.post("/generate_plan")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert _planned_item_id(client) == 1


# This proves unknown-allergen items are only withheld from users who have allergies; with none on file, nothing is filtered.


def test_a_generation_error_returns_a_generic_500_without_internal_details(client, monkeypatch):
    class _Boom(_NanMenuGenerator):
        def update_menu(self, *args, **kwargs):
            raise AttributeError("'float' object has no attribute 'split'")

    monkeypatch.setattr(Flask_app, "MenuGenerator", _Boom)
    monkeypatch.setenv("PLANNER", "llm")  # these tests cover the v1 LLM planner

    _register_and_login(client, "boom@example.test", "")

    response = client.post("/generate_plan")

    assert response.status_code == 500
    body = response.get_json()
    assert body["ok"] is False
    assert "float" not in body["error"] and "split" not in body["error"]


# This proves an exception during generation is reported to the client as a generic error, without the raw exception text.
