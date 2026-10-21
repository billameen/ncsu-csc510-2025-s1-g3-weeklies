"""
Dietary tags the plan-edit parser may ask for ("make Thursday vegetarian").

The menu has no tag column, so each tag is decided from what the menu does record: the
item's name, description, allergen tags and calories. The rules are deliberately strict: an
item gets a tag only when nothing in its data argues against it (a "Garden Salad with
Grilled Chicken" is not vegetarian). The vocabulary is closed: the parser can only name tags
listed in `TAGS`, and anything else is rejected before it reaches the solver.
"""

import re
from collections.abc import Callable

from planner.allergens import normalize_allergen
from planner.menu import MenuItem

# Words that mean an item contains meat or seafood.
MEAT_WORDS = (
    "anchovy",
    "bacon",
    "beef",
    "bison",
    "brisket",
    "burger",
    "calamari",
    "chicken",
    "chorizo",
    "clam",
    "crab",
    "duck",
    "fish",
    "filet mignon",
    "gyro",
    "ham",
    "hot dog",
    "lamb",
    "lobster",
    "meat",
    "meatball",
    "mussel",
    "octopus",
    "oyster",
    "pancetta",
    "pastrami",
    "pepperoni",
    "pork",
    "prosciutto",
    "ribs",
    "salami",
    "salmon",
    "sausage",
    "scallop",
    "shrimp",
    "steak",
    "trout",
    "tuna",
    "turkey",
    "veal",
    "venison",
    "wings",
)
# Allergen tags that mean an item contains animal flesh.
MEAT_ALLERGENS = {"fish", "shellfish", "pork", "poultry"}
# Words and allergen tags that mean an item contains other animal products.
ANIMAL_WORDS = (
    "butter",
    "cheese",
    "cheddar",
    "cream",
    "egg",
    "gelato",
    "ghee",
    "honey",
    "ice cream",
    "milk",
    "mozzarella",
    "parmesan",
    "yogurt",
)
ANIMAL_ALLERGENS = {"dairy", "eggs"}
SPICY_WORDS = (
    "buffalo",
    "cajun",
    "chili",
    "chile",
    "chilies",
    "chipotle",
    "curry",
    "harissa",
    "hot",
    "jalapeno",
    "jalapeño",
    "jerk",
    "kimchi",
    "pepper flakes",
    "sriracha",
    "spicy",
    "szechuan",
)
LOW_CALORIE_MAX = 500


def _text(item: MenuItem) -> str:
    return f"{item.name} {item.description}".lower()


def _mentions(item: MenuItem, words) -> bool:
    text = _text(item)
    return any(re.search(rf"\b{re.escape(w)}s?\b", text) for w in words)


def _allergens(item: MenuItem) -> set[str]:
    return {normalize_allergen(a) for a in item.allergens}


def is_vegetarian(item: MenuItem) -> bool:
    """No meat or seafood in the name, description or allergen tags."""
    return not _mentions(item, MEAT_WORDS) and not (_allergens(item) & MEAT_ALLERGENS)


def is_vegan(item: MenuItem) -> bool:
    """Vegetarian, and no dairy, eggs or other animal products."""
    return (
        is_vegetarian(item)
        and not _mentions(item, ANIMAL_WORDS)
        and not (_allergens(item) & ANIMAL_ALLERGENS)
    )


def is_spicy(item: MenuItem) -> bool:
    """Name or description mentions a spicy ingredient or style."""
    return _mentions(item, SPICY_WORDS)


def is_gluten_free(item: MenuItem) -> bool:
    """No gluten (or wheat) allergen tag."""
    return "gluten" not in _allergens(item)


def is_dairy_free(item: MenuItem) -> bool:
    """No dairy allergen tag and no cheese, cream or butter in the text."""
    return "dairy" not in _allergens(item) and not _mentions(
        item, ("butter", "cheese", "cheddar", "cream", "mozzarella", "parmesan", "milk")
    )


def is_low_calorie(item: MenuItem) -> bool:
    """At most LOW_CALORIE_MAX calories."""
    return item.calories <= LOW_CALORIE_MAX


# Tag name -> test. The parser's output format lists exactly these names.
TAGS: dict[str, Callable[[MenuItem], bool]] = {
    "vegetarian": is_vegetarian,
    "vegan": is_vegan,
    "spicy": is_spicy,
    "gluten-free": is_gluten_free,
    "dairy-free": is_dairy_free,
    "low-calorie": is_low_calorie,
}


def has_tag(item: MenuItem, tag: str) -> bool:
    """
    True if the item qualifies for the tag.
    Raises:
        KeyError: The tag is not in TAGS.
    """
    return TAGS[tag](item)
