import pandas as pd
import pytest

from menu_generation import ALLERGEN_TAGS, allergen_tags, filter_allergens, invalid_allergies


def _menu():
    return pd.DataFrame({
        "itm_id": [1, 2, 3, 4, 5, 6, 7],
        "allergens": ["Dairy", "Nuts", "Egg", "Gluten, Soy", None, float("nan"), "Fish"],
    })


def _kept(allergies, strict):
    return sorted(filter_allergens(_menu(), allergies, strict=strict)["itm_id"].tolist())


@pytest.mark.parametrize(
    "allergy,excluded_item",
    [("Milk", 1), ("Lactose", 1), ("Tree Nuts", 2), ("Eggs", 3), ("Wheat", 4)],
)
def test_strict_mode_translates_selectable_allergies_into_menu_tags(allergy, excluded_item):
    assert excluded_item not in _kept(allergy, strict=True)


def test_strict_mode_excludes_items_with_unknown_allergens_for_a_user_with_allergies():
    assert _kept("Fish", strict=True) == [1, 2, 3, 4]


def test_strict_mode_filters_nothing_for_a_user_without_allergies():
    assert _kept("", strict=True) == [1, 2, 3, 4, 5, 6, 7]


def test_default_mode_keeps_v1_matching_but_no_longer_crashes_on_nan():
    # v1 behavior, kept for the M0 evaluation's recorded run: matched as typed, unknowns kept
    assert _kept("Milk", strict=False) == [1, 2, 3, 4, 5, 6, 7]
    assert _kept("Dairy, eggs", strict=False) == [2, 3, 4, 5, 6, 7]


def test_allergen_tags_matches_case_insensitively_and_passes_unknown_entries_through():
    assert allergen_tags(" milk , EGGS ") == {"dairy", "eggs", "egg"}
    assert allergen_tags("Coconut") == {"coconut"}


def test_invalid_allergies_reports_only_unselectable_entries():
    assert invalid_allergies("Peanuts, peenuts, , Sulphites") == ["peenuts", "Sulphites"]
    assert invalid_allergies("") == []


def test_sulphites_is_not_selectable():
    assert "Sulphites" not in ALLERGEN_TAGS
