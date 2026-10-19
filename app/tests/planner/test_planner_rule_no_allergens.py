"""no_allergens on its own, including allergen spelling variants."""

import pytest
from menu_factory import item, menu, request

from planner.registry import get
from planner.solver import plan_week

OneItemPerMeal, NoAllergens = get("one_item_per_meal"), get("no_allergens")


def plan(items, allergens, **kw):
    return plan_week(
        request(allergens=allergens, **kw), menu(items), rules=[OneItemPerMeal(), NoAllergens()]
    )


def test_items_with_the_users_allergens_are_never_planned():
    result = plan(
        [item(1, allergens=("Dairy",)), item(2, allergens=("Soy", "Fish")), item(3)],
        ("Fish", "Dairy"),
        days=7,
    )
    assert result.ok and {m.itm_id for m in result.meals} == {3}


@pytest.mark.parametrize(
    "item_tag, user_tag",
    [("Egg", "Eggs"), ("Eggs", "Egg"), ("EGGS", "eggs"), ("Peanuts", "Nuts"), ("Dairy", "Milk")],
)
def test_allergen_spelling_variants_are_still_blocked(item_tag, user_tag):
    result = plan([item(1, allergens=(item_tag,)), item(2)], (user_tag,))
    assert {m.itm_id for m in result.meals} == {2}


def test_a_user_without_allergens_can_get_anything():
    result = plan([item(1, allergens=("Dairy", "Eggs"))], ())
    assert result.ok


def test_every_item_blocked_by_allergens_is_explained_with_their_names():
    result = plan(
        [item(1, allergens=("Egg",)), item(2, allergens=("Dairy",))], ("Eggs", "Egg", "Milk")
    )
    assert result.explanation == (
        "No breakfast, lunch or dinner can be planned on Mon Oct 19: of 2 menu items, "
        "2 contain your allergens (eggs, dairy)."
    )
