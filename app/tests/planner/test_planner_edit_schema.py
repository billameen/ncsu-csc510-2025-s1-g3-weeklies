"""The fixed format the parser must produce."""

import pytest
from pydantic import ValidationError

from planner.edits.schema import ParsedRequest, edit_keys


def parse(data):
    return ParsedRequest.model_validate(data)


def test_a_two_edit_request_parses_and_normalizes_spellings():
    parsed = parse(
        {
            "action": "edit",
            "edits": [
                {"type": "require_tag", "tag": "Veggie", "days": "Thursday"},
                {"type": "max_price", "max_price": "$10", "days": ["thu"], "meals": "dinners"},
            ],
        }
    )
    tag, price = parsed.edits
    assert (tag.tag, tag.day_codes(), tag.meal_codes()) == (
        "vegetarian",
        {"thu"},
        {"breakfast", "lunch", "dinner"},
    )
    assert (price.max_price, price.meal_codes()) == (10.0, {"dinner"})


@pytest.mark.parametrize(
    "days, expected",
    [
        ("weekend", {"sat", "sun"}),
        ("weekdays", {"mon", "tue", "wed", "thu", "fri"}),
        ("every day", {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}),
        (None, {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}),
        (["Saturday", "sunday"], {"sat", "sun"}),
    ],
)
def test_day_phrases_resolve(days, expected):
    edit = parse(
        {"action": "edit", "edits": [{"type": "require_tag", "tag": "vegan", "days": days}]}
    )
    assert edit.edits[0].day_codes() == expected


@pytest.mark.parametrize(
    "bad",
    [
        {"action": "edit", "edits": []},
        {"action": "edit", "edits": [{"type": "remove_allergy", "allergen": "peanuts"}]},
        {"action": "edit", "edits": [{"type": "raise_budget", "amount": 500}]},
        {"action": "edit", "edits": [{"type": "require_tag", "tag": "keto"}]},
        {"action": "edit", "edits": [{"type": "max_price", "max_price": -5}]},
        {"action": "edit", "edits": [{"type": "calorie_shift", "kcal_delta": 0}]},
        {"action": "edit", "edits": [{"type": "calorie_shift", "kcal_delta": 5000}]},
        {"action": "edit", "edits": [{"type": "require_tag", "tag": "vegan", "days": "someday"}]},
        {"action": "edit", "edits": [{"type": "require_tag", "tag": "vegan", "extra": 1}]},
        {"action": "clarify"},
        {"action": "explode"},
        {"action": "edit", "edits": [{"type": "exclude_item", "item": "x"}] * 6},
    ],
)
def test_anything_outside_the_format_is_rejected(bad):
    with pytest.raises(ValidationError):
        parse(bad)


def test_calorie_shifts_always_cover_whole_days():
    edit = parse(
        {
            "action": "edit",
            "edits": [{"type": "calorie_shift", "kcal_delta": -300, "meals": "dinner"}],
        }
    ).edits[0]
    assert edit.meal_codes() == {"breakfast", "lunch", "dinner"}


def test_refuse_and_clarify_drop_any_edits():
    parsed = parse(
        {"action": "refuse", "edits": [{"type": "require_tag", "tag": "vegan"}], "reason": "no"}
    )
    assert parsed.edits == []


def test_edit_keys_ignore_order_and_spelling():
    a = parse(
        {
            "action": "edit",
            "edits": [
                {"type": "max_price", "max_price": 10, "days": "thu"},
                {"type": "require_tag", "tag": "vegetarian", "days": ["Thursday"]},
            ],
        }
    )
    b = parse(
        {
            "action": "edit",
            "edits": [
                {"type": "require_tag", "tag": "veggie", "days": "thu"},
                {"type": "max_price", "max_price": "10.00", "days": "thu", "meals": "all"},
            ],
        }
    )
    assert edit_keys(a.edits) == edit_keys(b.edits)


def test_calorie_shifts_cannot_stack_on_one_day():
    """Five +1000 shifts would add 5,000 kcal; each day gets at most one shift."""
    stacked = [{"type": "calorie_shift", "kcal_delta": 1000, "days": "mon"}] * 2
    with pytest.raises(ValidationError, match="one calorie_shift per day"):
        parse({"action": "edit", "edits": stacked})
    with pytest.raises(ValidationError, match="one calorie_shift per day"):
        parse(
            {
                "action": "edit",
                "edits": [
                    {"type": "calorie_shift", "kcal_delta": 500, "days": "weekend"},
                    {"type": "calorie_shift", "kcal_delta": 500, "days": "sun"},
                ],
            }
        )
    separate = parse(
        {
            "action": "edit",
            "edits": [
                {"type": "calorie_shift", "kcal_delta": 300, "days": "mon"},
                {"type": "calorie_shift", "kcal_delta": -300, "days": "tue"},
            ],
        }
    )
    assert len(separate.edits) == 2


def test_edit_keys_sort_the_same_however_the_days_were_listed():
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    edits = [
        {"type": "require_tag", "tag": "vegan", "days": days},
        {"type": "require_tag", "tag": "vegan", "days": "thu"},
    ]
    forward = parse({"action": "edit", "edits": edits})
    backward = parse(
        {"action": "edit", "edits": [{**edits[0], "days": days[::-1]}, edits[1]][::-1]}
    )
    assert edit_keys(forward.edits) == edit_keys(backward.edits)
