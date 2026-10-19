"""Soft rule: prefer items that match the user's preferences."""

import re

from planner.constraint import SoftConstraint
from planner.registry import register


@register
class MatchPreferences(SoftConstraint):
    """
    Penalty of weight x number of meals whose item matches none of the user's preferences.
    An item matches a preference when the preference appears as a whole word or phrase in
    its name or description, ignoring case ("spicy" matches "Spicy Ramen" but "ice" does not
    match "Fried Rice"). Users without preferences are unaffected.

    The default weight, 400, means a matching item is worth up to $4 more per meal.
    """

    name = "match_preferences"
    summary = "Prefer items that match your preferences."
    order = 200
    default_weight = 400

    def apply(self, ctx):
        """Penalize every pick whose item matches none of the preferences."""
        patterns = [
            re.compile(rf"\b{re.escape(p.strip())}\b", re.IGNORECASE)
            for p in ctx.request.preferences
            if p.strip()
        ]
        if not patterns:
            return
        misses = [
            var
            for slot in ctx.slots
            for item, var in ctx.picks(slot)
            if not any(p.search(f"{item.name} {item.description}") for p in patterns)
        ]
        ctx.add_penalty(self, sum(misses))
