"""Dietary tags are decided from each item's name, description, allergens and calories."""

import pytest
from menu_factory import item

from planner.tags import TAGS, has_tag


def dish(name, description="", allergens=(), calories=600):
    return item(1, name=name, description=description, allergens=allergens, calories=calories)


@pytest.mark.parametrize(
    "dish_, vegetarian",
    [
        (dish("Spinach & Artichoke Pizza", "mozzarella", ("Gluten", "Dairy")), True),
        (dish("Miso Glazed Eggplant", allergens=("Soy",)), True),
        (dish("Laotian Beef Stir Fry"), False),
        (dish("Garden Salad", "topped with grilled chicken"), False),
        (dish("Pan-Seared Trout", allergens=("Fish",)), False),
        (dish("Imperial Roll", "rice paper roll", ("Shellfish",)), False),
        (dish("Cowper's Burger", "brioche bun"), False),
        (dish("Prosciutto & Arugula", allergens=("Pork",)), False),
    ],
)
def test_vegetarian_rejects_any_sign_of_meat_or_seafood(dish_, vegetarian):
    assert has_tag(dish_, "vegetarian") is vegetarian


def test_vegan_also_rejects_dairy_eggs_and_honey():
    assert has_tag(dish("Sweet Potato and Kale Soup", "coconut milk"), "vegan") is False
    assert has_tag(dish("Roasted Vegetables", "olive oil"), "vegan") is True
    assert has_tag(dish("Deviled Eggs", allergens=("Eggs",)), "vegan") is False
    assert has_tag(dish("Honey Toast"), "vegan") is False


def test_spicy_gluten_free_dairy_free_and_low_calorie():
    stir_fry = dish("Beef Stir Fry", "lemongrass and chilies", ("Soy",), calories=450)
    assert has_tag(stir_fry, "spicy")
    assert has_tag(stir_fry, "gluten-free") and has_tag(stir_fry, "dairy-free")
    assert has_tag(stir_fry, "low-calorie")
    pizza = dish("Pizza", "cheese", ("Gluten", "Dairy"), calories=900)
    assert not has_tag(pizza, "gluten-free") and not has_tag(pizza, "dairy-free")
    assert not has_tag(pizza, "low-calorie") and not has_tag(pizza, "spicy")


def test_wheat_counts_as_gluten():
    assert not has_tag(dish("Bread", allergens=("Wheat",)), "gluten-free")


def test_the_vocabulary_is_closed():
    assert set(TAGS) == {
        "vegetarian",
        "vegan",
        "spicy",
        "gluten-free",
        "dairy-free",
        "low-calorie",
    }
    with pytest.raises(KeyError):
        has_tag(dish("Toast"), "keto")
