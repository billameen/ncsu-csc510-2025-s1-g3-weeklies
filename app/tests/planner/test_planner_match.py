"""Conditions on one menu item, the building block of plan edits."""

import pytest
from menu_factory import item

from planner.match import FIELDS, Condition

RIBS = item(1, name="Beef Ribs", price_cents=1800, calories=900, allergens=("Soy",), rtr_id=7)
SALAD = item(2, name="Garden Salad", price_cents=800, calories=300, allergens=("Egg",), rtr_id=8)


@pytest.mark.parametrize(
    "condition, ribs, salad",
    [
        (Condition("tag", "is", "vegetarian"), False, True),
        (Condition("tag", "is_not", "vegetarian"), True, False),
        (Condition("price", "<=", 1000), False, True),
        (Condition("price", ">=", 1000), True, False),
        (Condition("calories", "<=", 900), True, True),
        (Condition("calories", ">=", 400), True, False),
        (Condition("dish", "is", "ribs", ids={1}), True, False),
        (Condition("dish", "is_not", "ribs", ids={1}), False, True),
        (Condition("restaurant", "is", "The Pit", ids={7}), True, False),
        (Condition("restaurant", "is_not", "The Pit", ids={7}), False, True),
        (Condition("allergen", "is_not", "Eggs"), True, False),
        (Condition("allergen", "is", "soy"), True, False),
    ],
)
def test_each_field_and_operator(condition, ribs, salad):
    assert (condition.matches(RIBS), condition.matches(SALAD)) == (ribs, salad)


def test_allergen_spellings_are_normalized():
    assert Condition("allergen", "is_not", "Egg").value == "eggs"
    assert not Condition("allergen", "is_not", "egg").matches(SALAD)


@pytest.mark.parametrize(
    "condition, matching, failing",
    [
        (Condition("tag", "is", "vegan"), "vegan", "not vegan"),
        (Condition("tag", "is_not", "spicy"), "not spicy", "spicy"),
        (Condition("price", "<=", 1000), "$10.00 or less", "over $10.00"),
        (Condition("price", ">=", 1250), "at least $12.50", "under $12.50"),
        (Condition("calories", "<=", 700), "700 kcal or less", "over 700 kcal"),
        (Condition("calories", ">=", 1200), "at least 1,200 kcal", "under 1,200 kcal"),
        (Condition("dish", "is", "pizza", ids={3}), '"pizza"', 'not "pizza"'),
        (Condition("restaurant", "is_not", "The Pit", ids={7}), "not from The Pit", "from The Pit"),
        (Condition("allergen", "is_not", "Shellfish"), "free of shellfish", "with shellfish"),
    ],
)
def test_descriptions_read_as_plain_english(condition, matching, failing):
    assert (condition.describe(), condition.describe_miss()) == (matching, failing)


@pytest.mark.parametrize(
    "args",
    [
        ("colour", "is", "red"),  # unknown field
        ("price", "is", 1000),  # wrong operator for a number
        ("tag", "<=", "vegan"),  # wrong operator for a name
        ("price", "<=", 0),
        ("calories", ">=", "lots"),
        ("tag", "is", "keto"),  # unknown tag
        ("dish", "is", "pizza"),  # names must be matched to ids first
        ("restaurant", "is_not", ""),
    ],
)
def test_malformed_conditions_are_rejected(args):
    with pytest.raises(ValueError):
        Condition(*args)


def test_every_field_has_operators():
    assert set(FIELDS) == {"tag", "dish", "restaurant", "allergen", "price", "calories"}
    assert all(FIELDS.values())
