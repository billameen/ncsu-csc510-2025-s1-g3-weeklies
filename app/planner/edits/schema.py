"""
The fixed format the parser must produce, checked with Pydantic.

Only edit types that exist as M1 rule plug-ins are allowed, and each one can only add a
restriction: there is no edit type that removes an allergy, raises the budget or relaxes a
rule. Anything that does not fit this format is rejected.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from planner.tags import TAGS

WEEKDAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MEAL_CODES = ("breakfast", "lunch", "dinner")
MAX_EDITS = 5

DayWord = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun", "weekend", "weekdays", "all"]
MealWord = Literal["breakfast", "lunch", "dinner", "all"]
TagWord = Literal[tuple(TAGS)]  # type: ignore[valid-type]

# Spellings a model (or a person) might use -> the canonical word.
_DAY_ALIASES = {
    "monday": "mon",
    "tuesday": "tue",
    "tues": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "thur": "thu",
    "thurs": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
    "weekends": "weekend",
    "weekday": "weekdays",
    "every day": "all",
    "everyday": "all",
    "daily": "all",
    "week": "all",
    "all week": "all",
    "whole week": "all",
    "any": "all",
}
_MEAL_ALIASES = {
    "breakfasts": "breakfast",
    "brunch": "breakfast",
    "lunches": "lunch",
    "dinners": "dinner",
    "supper": "dinner",
    "all meals": "all",
    "every meal": "all",
    "meals": "all",
    "any": "all",
}
_TAG_ALIASES = {
    "veggie": "vegetarian",
    "meatless": "vegetarian",
    "no meat": "vegetarian",
    "plant-based": "vegan",
    "plant based": "vegan",
    "gluten free": "gluten-free",
    "dairy free": "dairy-free",
    "low calorie": "low-calorie",
    "light": "low-calorie",
    "hot": "spicy",
}


def _words(value, aliases):
    """A word or list of words, lowercased with aliases resolved."""
    if value is None:
        return ["all"]
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return value  # let Pydantic report the type error
    return [aliases.get(str(v).strip().lower(), str(v).strip().lower()) for v in value] or ["all"]


class _Scoped(BaseModel):
    """Days and meals an edit applies to. Missing means all."""

    model_config = ConfigDict(extra="forbid")

    days: list[DayWord] = ["all"]
    meals: list[MealWord] = ["all"]

    @field_validator("days", mode="before")
    @classmethod
    def _days(cls, value):
        return _words(value, _DAY_ALIASES)

    @field_validator("meals", mode="before")
    @classmethod
    def _meals(cls, value):
        return _words(value, _MEAL_ALIASES)

    def day_codes(self) -> frozenset[str]:
        """The days as weekday codes: "weekend" -> {"sat", "sun"}, "all" -> all seven."""
        days = set()
        for d in self.days:
            if d == "all":
                days.update(WEEKDAY_CODES)
            elif d == "weekend":
                days.update(("sat", "sun"))
            elif d == "weekdays":
                days.update(WEEKDAY_CODES[:5])
            else:
                days.add(d)
        return frozenset(days)

    def meal_codes(self) -> frozenset[str]:
        """The meals: "all" -> breakfast, lunch and dinner."""
        return frozenset(MEAL_CODES if "all" in self.meals else self.meals)


class RequireTag(_Scoped):
    """Only items with a dietary tag ("make Thursday vegetarian")."""

    type: Literal["require_tag"]
    tag: TagWord

    @field_validator("tag", mode="before")
    @classmethod
    def _tag(cls, value):
        return _TAG_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())

    def key(self):
        return (self.type, self.tag, self.day_codes(), self.meal_codes())


class MaxPrice(_Scoped):
    """Only items at or under a menu price, in dollars ("under $10")."""

    type: Literal["max_price"]
    max_price: float = Field(gt=0, le=100)

    @field_validator("max_price", mode="before")
    @classmethod
    def _price(cls, value):
        if isinstance(value, str):
            value = value.strip().lstrip("$").replace(",", "")
        return value

    def key(self):
        return (self.type, round(self.max_price, 2), self.day_codes(), self.meal_codes())


class ExcludeItem(_Scoped):
    """Never a given dish ("no Beef Ribs")."""

    type: Literal["exclude_item"]
    item: str = Field(min_length=2, max_length=80)

    def key(self):
        return (self.type, self.item.strip().lower(), self.day_codes(), self.meal_codes())


class ExcludeRestaurant(_Scoped):
    """Never a given restaurant ("nothing from Sorella's")."""

    type: Literal["exclude_restaurant"]
    restaurant: str = Field(min_length=2, max_length=80)

    def key(self):
        return (self.type, self.restaurant.strip().lower(), self.day_codes(), self.meal_codes())


class CalorieShift(_Scoped):
    """Move whole days' calorie target ("lighter on the weekend" is about -300)."""

    type: Literal["calorie_shift"]
    kcal_delta: int = Field(ge=-1000, le=1000)

    @field_validator("kcal_delta")
    @classmethod
    def _nonzero(cls, value):
        if value == 0:
            raise ValueError("kcal_delta must not be 0")
        return value

    @model_validator(mode="after")
    def _whole_days(self):
        # A calorie target is per day, so the shift always covers whole days.
        self.meals = ["all"]
        return self

    def key(self):
        return (self.type, self.kcal_delta, self.day_codes(), self.meal_codes())


Edit = Annotated[
    Union[RequireTag, MaxPrice, ExcludeItem, ExcludeRestaurant, CalorieShift],
    Field(discriminator="type"),
]
EDIT_TYPES = ("require_tag", "max_price", "exclude_item", "exclude_restaurant", "calorie_shift")


class ParsedRequest(BaseModel):
    """
    What the parser returns for one sentence.
    action:
        "edit": apply `edits` (1 to MAX_EDITS of them).
        "clarify": the request is ambiguous; ask `question`.
        "refuse": the request would loosen a rule or is not a meal edit.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["edit", "clarify", "refuse"]
    edits: list[Edit] = Field(default_factory=list, max_length=MAX_EDITS)
    question: str | None = Field(default=None, max_length=300)
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _consistent(self):
        if self.action == "edit" and not self.edits:
            raise ValueError("action 'edit' needs at least one edit")
        if self.action == "clarify" and not (self.question or "").strip():
            raise ValueError("action 'clarify' needs a question")
        if self.action != "edit":
            self.edits = []
        shifted = set()
        for e in self.edits:
            if isinstance(e, CalorieShift):
                if shifted & e.day_codes():
                    # Two shifts on one day would add up past the 1,000 kcal limit.
                    raise ValueError("at most one calorie_shift per day")
                shifted |= e.day_codes()
        return self


def edit_keys(edits) -> list:
    """Order-independent comparison keys for a list of edits (used to score parsers)."""
    return sorted((e.key() for e in edits), key=repr)
