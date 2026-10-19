"""Allergen spellings are normalized before they are compared (Egg = Eggs)."""

import pytest

from planner.allergens import allergens_in, normalize_allergen, parse_allergens


@pytest.mark.parametrize(
    "spelling, canonical",
    [
        ("Egg", "eggs"),
        ("Eggs", "eggs"),
        ("EGGS", "eggs"),
        ("  eggs ", "eggs"),
        ("Milk", "dairy"),
        ("Lactose", "dairy"),
        ("Peanuts", "nuts"),
        ("Tree  Nuts", "nuts"),
        ("Wheat", "gluten"),
        ("Sesame", "sesame"),
    ],
)
def test_spelling_variants_normalize_to_one_tag(spelling, canonical):
    assert normalize_allergen(spelling) == canonical


@pytest.mark.parametrize(
    "item_tags, avoid",
    [
        (("Egg",), ("Eggs",)),
        (("Eggs",), ("egg",)),
        (("Dairy", "Gluten"), ("Milk",)),
        (("Nuts",), ("Peanuts",)),
        (("Peanuts",), ("Tree Nuts",)),
        (("Gluten",), ("Wheat",)),
    ],
)
def test_an_item_is_blocked_whichever_spelling_either_side_uses(item_tags, avoid):
    assert allergens_in(item_tags, avoid)


def test_safe_items_and_users_without_allergens_pass():
    assert allergens_in(("Dairy", "Soy"), ("Eggs", "Fish")) == []
    assert allergens_in(("Dairy",), ()) == []
    assert allergens_in((), ("Dairy",)) == []


def test_found_allergens_are_deduplicated_in_item_order():
    assert allergens_in(("Soy", "Egg", "Eggs", "Dairy"), ("dairy", "eggs", "soy")) == [
        "soy",
        "eggs",
        "dairy",
    ]


def test_parse_allergens_splits_and_drops_blanks():
    assert parse_allergens("Peanuts, Tree Nuts,,Eggs ,") == ("Peanuts", "Tree Nuts", "Eggs")
    assert parse_allergens(None) == ()
    assert parse_allergens("") == ()
