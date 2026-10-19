"""Hard rule: never plan an item containing one of the user's allergens."""

from planner.allergens import allergens_in, normalize_allergen
from planner.constraint import ItemFilter
from planner.registry import register


@register
class NoAllergens(ItemFilter):
    """
    Skip items tagged with any of the request's allergens. Both sides are normalized first
    (see planner.allergens), so "Egg" on an item matches "Eggs" on a profile.
    """

    name = "no_allergens"
    summary = "No item contains one of your allergens."
    blocked_reason = "contain your allergens"
    order = 12

    def allows(self, item, slot, ctx):
        """True if the item has none of the request's allergens."""
        return not allergens_in(item.allergens, ctx.request.allergens)

    def describe_block(self, slot, ctx):
        """Names the allergens, e.g. "contain your allergens (eggs, dairy)"."""
        names = dict.fromkeys(normalize_allergen(a) for a in ctx.request.allergens)
        return f"contain your allergens ({', '.join(names)})"
