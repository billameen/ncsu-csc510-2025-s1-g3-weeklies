"""The edit language the parser must produce."""

import pytest
from pydantic import ValidationError

from planner.edits.schema import ParsedRequest, edit_keys


VEGAN = {"type": "filter", "field": "tag", "op": "is", "value": "vegan"}


def parse(data):
    return ParsedRequest.model_validate(data)


def test_a_two_edit_request_parses_and_normalizes_spellings():
    parsed = parse(
        {
            "action": "edit",
            "edits": [
                {
                    "type": "filter",
                    "field": "diet",
                    "op": "=",
                    "value": "Veggie",
                    "days": "Thursday",
                },
                {
                    "type": "filter",
                    "field": "cost",
                    "op": "under",
                    "value": "$10",
                    "days": ["thu"],
                    "meals": "dinners",
                },
            ],
        }
    )
    tag, price = parsed.edits
    assert (tag.field, tag.op, tag.value, tag.day_codes(), tag.meal_codes()) == (
        "tag",
        "is",
        "vegetarian",
        {"thu"},
        {"breakfast", "lunch", "dinner"},
    )
    assert (price.field, price.op, price.value, price.meal_codes()) == (
        "price",
        "<=",
        10.0,
        {"dinner"},
    )


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
    edit = parse({"action": "edit", "edits": [{**VEGAN, "days": days}]})
    assert edit.edits[0].day_codes() == expected


@pytest.mark.parametrize(
    "bad",
    [
        {"action": "edit", "edits": []},
        {"action": "edit", "edits": [{"type": "remove_allergy", "allergen": "peanuts"}]},
        {"action": "edit", "edits": [{"type": "raise_budget", "amount": 500}]},
        {"action": "edit", "edits": [{"type": "require_tag", "tag": "vegan"}]},  # v1 format
        {"action": "edit", "edits": [{**VEGAN, "value": "keto"}]},
        {"action": "edit", "edits": [{**VEGAN, "op": "<="}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "colour"}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "price", "op": "<=", "value": -5}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "price", "op": "<=", "value": 500}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "price", "op": "<=", "value": "cheap"}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "calories", "op": ">=", "value": 9000}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "dish", "op": "is", "value": ""}]},
        {"action": "edit", "edits": [{**VEGAN, "value": True}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "price", "op": "<=", "value": 0.001}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "price", "op": "<=", "value": "nan"}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "price", "op": "<=", "value": "inf"}]},
        {"action": "edit", "edits": [{**VEGAN, "field": "calories", "op": "<=", "value": 0.4}]},
        {"action": "edit", "edits": [{**VEGAN, "days": []}]},
        {"action": "edit", "edits": [{**VEGAN, "meals": []}]},
        {"action": "edit", "edits": [{**VEGAN, "type": "include", "times": True}]},
        {"action": "edit", "edits": [{"type": "calorie_shift", "kcal_delta": True}]},
        {
            "action": "edit",
            "edits": [{"type": "day_limit", "metric": "cost", "op": "<=", "value": 0.001}],
        },
        {
            "action": "edit",
            "edits": [{"type": "day_limit", "metric": "calories", "op": "<=", "value": True}],
        },
        {
            "action": "edit",
            "edits": [
                {"type": "prefer", "goal": "match", "field": "price", "op": "<=", "value": True}
            ],
        },
        {"action": "edit", "edits": [{**VEGAN, "type": "include", "times": 0}]},
        {"action": "edit", "edits": [{**VEGAN, "type": "include", "times": 30}]},
        {
            "action": "edit",
            "edits": [{"type": "day_limit", "metric": "protein", "op": "<=", "value": 10}],
        },
        {
            "action": "edit",
            "edits": [{"type": "day_limit", "metric": "cost", "op": "<=", "value": 0}],
        },
        {
            "action": "edit",
            "edits": [{"type": "day_limit", "metric": "cost", "op": "<=", "value": 5000}],
        },
        {"action": "edit", "edits": [{"type": "prefer", "goal": "tastier"}]},
        {"action": "edit", "edits": [{"type": "prefer", "goal": "match"}]},
        {"action": "edit", "edits": [{"type": "prefer", "goal": "cheaper", "field": "tag"}]},
        {"action": "edit", "edits": [{"type": "calorie_shift", "kcal_delta": 0}]},
        {"action": "edit", "edits": [{"type": "calorie_shift", "kcal_delta": 5000}]},
        {"action": "edit", "edits": [{**VEGAN, "days": "someday"}]},
        {"action": "edit", "edits": [{**VEGAN, "extra": 1}]},
        {"action": "clarify"},
        {"action": "explode"},
        {"action": "edit", "edits": [VEGAN] * 6},
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
    parsed = parse({"action": "refuse", "edits": [VEGAN], "reason": "no"})
    assert parsed.edits == []


def test_edit_keys_ignore_order_and_spelling():
    a = parse(
        {
            "action": "edit",
            "edits": [
                {"type": "filter", "field": "price", "op": "<=", "value": 10, "days": "thu"},
                {**VEGAN, "value": "vegetarian", "days": ["Thursday"]},
            ],
        }
    )
    b = parse(
        {
            "action": "edit",
            "edits": [
                {**VEGAN, "value": "veggie", "days": "thu"},
                {"type": "filter", "field": "cost", "op": "<", "value": "10.00", "days": "thu"},
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
        {**VEGAN, "days": days},
        {**VEGAN, "days": "thu"},
    ]
    forward = parse({"action": "edit", "edits": edits})
    backward = parse(
        {"action": "edit", "edits": [{**edits[0], "days": days[::-1]}, edits[1]][::-1]}
    )
    assert edit_keys(forward.edits) == edit_keys(backward.edits)


@pytest.mark.parametrize(
    "edit, key",
    [
        (
            {"type": "include", "field": "food", "op": "is", "value": "Pizza", "meals": "night"},
            ("include", "dish", "is", "pizza", 1),
        ),
        (
            {"type": "filter", "field": "allergen", "op": "not", "value": "Egg"},
            ("filter", "allergen", "is_not", "eggs"),
        ),
        (
            {"type": "filter", "field": "kcal", "op": "at most", "value": "700 kcal"},
            ("filter", "calories", "<=", 700),
        ),
        (
            {"type": "day_limit", "metric": "budget", "op": "<=", "value": "4$"},
            ("day_limit", "cost", "<=", 4.0),
        ),
        ({"type": "prefer", "goal": "lighter"}, ("prefer", "fewer_calories", None, None, None)),
        (
            {"type": "prefer", "goal": "match", "field": "tag", "op": "is", "value": "veggie"},
            ("prefer", "match", "tag", "is", "vegetarian"),
        ),
    ],
)
def test_each_edit_type_normalizes_what_a_model_might_write(edit, key):
    parsed = parse({"action": "edit", "edits": [edit]}).edits[0]
    assert parsed.key()[: len(key)] == key


def test_daily_limits_always_cover_whole_days():
    limit = parse(
        {
            "action": "edit",
            "edits": [
                {
                    "type": "day_limit",
                    "metric": "calories",
                    "op": ">=",
                    "value": 2000,
                    "meals": "lunch",
                }
            ],
        }
    ).edits[0]
    assert limit.meal_codes() == {"breakfast", "lunch", "dinner"}


def test_edit_keys_treat_one_edit_per_day_like_one_edit_for_both_days():
    shift = {"type": "calorie_shift", "kcal_delta": -300}
    split = parse({"action": "edit", "edits": [{**shift, "days": "mon"}, {**shift, "days": "tue"}]})
    joined = parse({"action": "edit", "edits": [{**shift, "days": ["mon", "tue"]}]})
    assert edit_keys(split.edits) == edit_keys(joined.edits)
    # include is not merged: "pizza on Monday and pizza on Tuesday" is two pizzas, not one.
    pizza = {"type": "include", "field": "dish", "op": "is", "value": "pizza"}
    two = parse({"action": "edit", "edits": [{**pizza, "days": "mon"}, {**pizza, "days": "tue"}]})
    one = parse({"action": "edit", "edits": [{**pizza, "days": ["mon", "tue"]}]})
    assert edit_keys(two.edits) != edit_keys(one.edits)
    # Different meals are different edits.
    lunch = parse({"action": "edit", "edits": [{**VEGAN, "days": "mon", "meals": "lunch"}]})
    dinner = parse({"action": "edit", "edits": [{**VEGAN, "days": "tue", "meals": "dinner"}]})
    both = parse(
        {
            "action": "edit",
            "edits": [{**VEGAN, "days": ["mon", "tue"], "meals": ["lunch", "dinner"]}],
        }
    )
    assert edit_keys(lunch.edits + dinner.edits) != edit_keys(both.edits)
