"""
Allergen tags, normalized so that different spellings of the same allergen match.

The menu data spells some allergens more than one way ("Egg" and "Eggs"), and the profile
form offers names the menu never uses ("Milk", "Tree Nuts", "Wheat"). Both sides go through
`normalize_allergen` before they are compared, so "Egg" on a menu item matches "Eggs" on a
profile.

The mapping errs on the side of blocking: "Peanuts" and "Tree Nuts" both count as "nuts",
and "Wheat" counts as "gluten", because the menu data has a single "Nuts" tag and no
"Wheat" tag. A user who lists wheat therefore never gets an item tagged Gluten.
"""

from collections.abc import Iterable

# Lowercased spelling -> canonical tag. Anything not listed is its own canonical tag.
ALIASES = {
    "egg": "eggs",
    "milk": "dairy",
    "lactose": "dairy",
    "nut": "nuts",
    "peanut": "nuts",
    "peanuts": "nuts",
    "tree nut": "nuts",
    "tree nuts": "nuts",
    "wheat": "gluten",
}


def normalize_allergen(tag: str) -> str:
    """
    Canonical form of one allergen tag: lowercase, whitespace collapsed, aliases resolved.
    Examples: "Egg" -> "eggs", " Tree  Nuts " -> "nuts", "Dairy" -> "dairy".
    """
    tag = " ".join(tag.lower().split())
    return ALIASES.get(tag, tag)


def parse_allergens(text: str | None) -> tuple[str, ...]:
    """
    Split a comma-separated allergen string (as stored in User.allergies and
    MenuItem.allergens) into tags, dropping blanks. Tags keep their original spelling.
    """
    if not text:
        return ()
    return tuple(tag.strip() for tag in text.split(",") if tag.strip())


def allergens_in(item_tags: Iterable[str], avoid: Iterable[str]) -> list[str]:
    """
    The allergens to avoid that an item contains, normalized and deduplicated, in the
    item's tag order. Empty if the item is safe.
    Args:
        item_tags: The item's allergen tags, any spelling.
        avoid: The user's allergens, any spelling.
    """
    avoid_set = {normalize_allergen(a) for a in avoid}
    tags = (normalize_allergen(t) for t in item_tags)
    return [t for t in dict.fromkeys(tags) if t in avoid_set]
