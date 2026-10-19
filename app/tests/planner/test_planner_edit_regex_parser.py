"""The regex baseline parser."""

import pytest

from planner.edits.regex_parser import parse
from planner.edits.schema import ParsedRequest, edit_keys


def keys(*edits):
    return edit_keys(ParsedRequest.model_validate({"action": "edit", "edits": list(edits)}).edits)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "make Thursday vegetarian under $10",
            keys(
                {"type": "require_tag", "tag": "vegetarian", "days": "thu"},
                {"type": "max_price", "max_price": 10, "days": "thu"},
            ),
        ),
        ("no Beef Ribs this week", keys({"type": "exclude_item", "item": "Beef Ribs"})),
        (
            "nothing from Sorella's on Friday",
            keys({"type": "exclude_restaurant", "restaurant": "Sorella's", "days": "fri"}),
        ),
        (
            "lighter dinners on the weekend",
            keys({"type": "calorie_shift", "kcal_delta": -300, "days": "weekend"}),
        ),
        ("spicy dinners", keys({"type": "require_tag", "tag": "spicy", "meals": "dinner"})),
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
