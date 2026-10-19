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
        return not allergens_in(item.allergens, ctx.request.allergens)

    def describe_block(self, slot, ctx):
        names = dict.fromkeys(normalize_allergen(a) for a in ctx.request.allergens)
        return f"contain your allergens ({', '.join(names)})"
