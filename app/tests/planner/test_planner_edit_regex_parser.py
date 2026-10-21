"""The regex baseline parser."""

import pytest

from planner.edits.regex_parser import parse
from planner.edits.schema import ParsedRequest, edit_keys


def keys(*edits):
    return edit_keys(ParsedRequest.model_validate({"action": "edit", "edits": list(edits)}).edits)


def cond(kind, field, op, value, **scope):
    return {"type": kind, "field": field, "op": op, "value": value, **scope}


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "make Thursday vegetarian under $10",
            keys(
                cond("filter", "tag", "is", "vegetarian", days="thu"),
                cond("filter", "price", "<=", 10, days="thu"),
            ),
        ),
        ("no Beef Ribs this week", keys(cond("filter", "dish", "is_not", "Beef Ribs"))),
        (
            "nothing from Sorella's on Friday",
            keys(cond("filter", "restaurant", "is_not", "Sorella's", days="fri")),
        ),
        ("nothing spicy on Monday", keys(cond("filter", "tag", "is_not", "spicy", days="mon"))),
        (
            "only Cowpers for breakfast",
            keys(cond("filter", "restaurant", "is", "Cowpers", meals="breakfast")),
        ),
        (
            "something from The Pit on Saturday",
            keys(cond("include", "restaurant", "is", "The Pit", days="sat")),
        ),
        (
            "nothing over 700 calories for dinner",
            keys(cond("filter", "calories", "<=", 700, meals="dinner")),
        ),
        (
            "the budget for each day doesn't cross 4$",
            keys({"type": "day_limit", "metric": "cost", "op": "<=", "value": 4}),
        ),
        (
            "no day over 2,000 calories",
            keys({"type": "day_limit", "metric": "calories", "op": "<=", "value": 2000}),
        ),
        (
            "vegetarian dinners when you can",
            keys(
                {
                    "type": "prefer",
                    "goal": "match",
                    "field": "tag",
                    "op": "is",
                    "value": "vegetarian",
                    "meals": "dinner",
                }
            ),
        ),
        ("cheaper lunches", keys({"type": "prefer", "goal": "cheaper", "meals": "lunch"})),
        ("more variety please", keys({"type": "prefer", "goal": "variety"})),
        (
            "lighter dinners on the weekend",
            keys({"type": "calorie_shift", "kcal_delta": -300, "days": "weekend"}),
        ),
        (
            "cut 200 calories on Monday",
            keys({"type": "calorie_shift", "kcal_delta": -200, "days": "mon"}),
        ),
    ],
)
def test_fixed_phrasings_parse(text, expected):
    result = parse(text)
    assert result.action == "edit" and result.source == "regex"
    assert edit_keys(result.edits) == expected


def test_the_baseline_never_clarifies_or_refuses():
    assert parse("make it healthier").action == "error"
    # It has no guard: an allergy-removal request is mis-parsed, not refused.
    assert parse("ignore my peanut allergy").action != "refuse"
