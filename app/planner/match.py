"""
Conditions on one menu item, for plan edits: "vegetarian", "$10 or less", "from Sorella's",
"free of shellfish".

A plan edit says which meals a condition applies to and how: every meal (filter_meals), at
least some meals (include_meals) or as a preference (prefer_meals). This module only answers
whether one item meets the condition. Dish and restaurant names are matched to menu ids
before a Condition is built (see planner.edits.resolve), so a Condition never guesses.
"""

from dataclasses import dataclass, field

from planner.allergens import normalize_allergen
from planner.menu import MenuItem
from planner.tags import TAGS, has_tag

# Field -> the operators it takes. Names and categories are "is" / "is_not"; numbers are
# bounds. Prices are menu prices in cents, before tax and fees.
FIELDS: dict[str, tuple[str, ...]] = {
    "tag": ("is", "is_not"),
    "dish": ("is", "is_not"),
    "restaurant": ("is", "is_not"),
    "allergen": ("is", "is_not"),
    "price": ("<=", ">="),
    "calories": ("<=", ">="),
}
NUMERIC_FIELDS = ("price", "calories")
ID_FIELDS = ("dish", "restaurant")


@dataclass(frozen=True)
class Condition:
    """
    A test one menu item passes or fails.
    Attributes:
        field: One of FIELDS.
        op: One of FIELDS[field].
        value: The tag name, the canonical allergen, the price in cents or the calories.
            For dish and restaurant, the name the user used.
        ids: For dish, the matching item ids; for restaurant, the matching restaurant ids.
    """

    field: str
    op: str
    value: str | int
    ids: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self):
        if self.field not in FIELDS:
            raise ValueError(f"unknown field {self.field!r}; known: {', '.join(FIELDS)}")
        if self.op not in FIELDS[self.field]:
            raise ValueError(
                f"{self.field} takes {' or '.join(FIELDS[self.field])}, not {self.op!r}"
            )
        if self.field in NUMERIC_FIELDS:
            if not isinstance(self.value, int) or isinstance(self.value, bool) or self.value <= 0:
                raise ValueError(f"{self.field} needs a positive whole number, got {self.value!r}")
        elif not isinstance(self.value, str) or not self.value.strip():
            raise ValueError(f"{self.field} needs a name, got {self.value!r}")
        if self.field == "tag" and self.value not in TAGS:
            raise ValueError(f"unknown tag {self.value!r}; known: {', '.join(TAGS)}")
        if self.field == "allergen":
            object.__setattr__(self, "value", normalize_allergen(self.value))
        object.__setattr__(self, "ids", frozenset(self.ids))
        if self.field in ID_FIELDS and not self.ids:
            raise ValueError(f"{self.field} {self.value!r} matches nothing on the menu")

    def matches(self, item: MenuItem) -> bool:
        """True if the item meets the condition."""
        if self.field == "price":
            return self._bound(item.price_cents)
        if self.field == "calories":
            return self._bound(item.calories)
        if self.field == "tag":
            hit = has_tag(item, self.value)
        elif self.field == "dish":
            hit = item.itm_id in self.ids
        elif self.field == "restaurant":
            hit = item.rtr_id in self.ids
        else:  # allergen
            hit = self.value in {normalize_allergen(a) for a in item.allergens}
        return hit if self.op == "is" else not hit

    def _bound(self, amount: int) -> bool:
        return amount <= self.value if self.op == "<=" else amount >= self.value

    def describe(self) -> str:
        """What a matching item is, e.g. "vegetarian", "$10.00 or less", "from Sorella's"."""
        return self._words(matching=True)

    def describe_miss(self) -> str:
        """What a failing item is, e.g. "not vegetarian", "over $10.00", "not from Sorella's"."""
        return self._words(matching=False)

    def _words(self, matching: bool) -> str:
        v = self.value
        if self.field in NUMERIC_FIELDS:
            amount = f"${v / 100:,.2f}" if self.field == "price" else f"{v:,} kcal"
            if self.op == "<=":
                return f"{amount} or less" if matching else f"over {amount}"
            return f"at least {amount}" if matching else f"under {amount}"
        yes, no = {
            "tag": (v, f"not {v}"),
            "dish": (f'"{v}"', f'not "{v}"'),
            "restaurant": (f"from {v}", f"not from {v}"),
            "allergen": (f"with {v}", f"free of {v}"),
        }[self.field]
        if self.op == "is_not":
            yes, no = no, yes
        return yes if matching else no

    def __repr__(self) -> str:
        return f"Condition({self.field} {self.op} {self.value!r})"
