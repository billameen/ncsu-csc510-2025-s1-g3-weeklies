"""Plan requests: the slots they cover and the input they reject."""

from datetime import date

import pytest

from planner.request import InvalidPlanRequest, PlanRequest

MONDAY = date(2026, 10, 19)


def request(**overrides):
    fields = dict(daily_calorie_target=2000, weekly_budget_cents=30000, start=MONDAY)
    fields.update(overrides)
    return PlanRequest(**fields)


def test_a_request_lists_its_slots_day_by_day():
    slots = request(days=2, meals=(3, 1)).slots()
    assert [(s.index, s.day.day, s.meal) for s in slots] == [
        (0, 19, 1),
        (1, 19, 3),
        (2, 20, 1),
        (3, 20, 3),
    ]
    assert slots[0].weekday == "Mon" and slots[0].time == 1000
    assert slots[1].label == "Mon Oct 19 dinner"


@pytest.mark.parametrize(
    "overrides",
    [
        {"daily_calorie_target": 0},
        {"daily_calorie_target": 2000.0},
        {"daily_calorie_target": True},
        {"weekly_budget_cents": -1},
        {"weekly_budget_cents": None},
        {"start": "2026-10-19"},
        {"days": 0},
        {"days": 15},
        {"meals": ()},
        {"meals": (1, 1)},
        {"meals": (4,)},
    ],
)
def test_bad_requests_are_rejected_with_a_message(overrides):
    with pytest.raises(InvalidPlanRequest):
        request(**overrides)


def test_from_profile_parses_the_stored_text_fields():
    req = PlanRequest.from_profile(
        daily_calorie_target=2200,
        weekly_budget_cents=25000,
        allergies="Peanuts, Egg",
        preferences="spicy,vegetarian",
        start=MONDAY,
    )
    assert req.allergens == ("Peanuts", "Egg")
    assert req.preferences == ("spicy", "vegetarian")
    assert len(req.slots()) == 21


def test_from_profile_asks_for_missing_targets():
    with pytest.raises(InvalidPlanRequest, match="daily calorie target and weekly budget"):
        PlanRequest.from_profile(
            daily_calorie_target=None,
            weekly_budget_cents=None,
            allergies=None,
            preferences=None,
            start=MONDAY,
        )


def test_options_are_read_only():
    req = request(options={"max_meals_per_restaurant": 2})
    with pytest.raises(TypeError):
        req.options["max_meals_per_restaurant"] = 9
