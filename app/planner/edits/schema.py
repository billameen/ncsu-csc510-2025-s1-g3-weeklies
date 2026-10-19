"""
The format the parser must produce, checked with Pydantic: a small edit language.

An edit is one of five types, each applied to some days and meals:

- filter: every meal meets a condition ("make Thursday vegetarian", "dinners under $15").
- include: at least some meals meet a condition ("pizza on Friday night").
- day_limit: each day's cost or calories under or over a limit ("each day under $40").
- prefer: a preference, never a requirement ("cheaper lunches if possible").
- calorie_shift: move some days' calorie target ("lighter on the weekend").

A condition is a field (tag, dish, restaurant, allergen, price, calories), an operator and a
value; see planner.match. Every edit can only add a restriction or a preference: nothing in
the language removes an allergy, raises the budget or relaxes a rule, and the solver enforces
those whatever the edits say. Anything that does not fit the format is rejected.
"""

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from planner.allergens import normalize_allergen
from planner.match import FIELDS, NUMERIC_FIELDS
from planner.tags import TAGS

WEEKDAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MEAL_CODES = ("breakfast", "lunch", "dinner")
MAX_EDITS = 5

DayWord = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun", "weekend", "weekdays", "all"]
MealWord = Literal["breakfast", "lunch", "dinner", "all"]

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
    "night": "dinner",
    "evening": "dinner",
    "morning": "breakfast",
    "noon": "lunch",
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


_FIELD_ALIASES = {
    "item": "dish",
    "food": "dish",
    "name": "dish",
    "keyword": "dish",
    "ingredient": "dish",
    "cost": "price",
    "kcal": "calories",
    "calorie": "calories",
    "diet": "tag",
    "allergy": "allergen",
}
_OP_ALIASES = {
    "=": "is",
    "==": "is",
    "equals": "is",
    "is not": "is_not",
    "isnt": "is_not",
    "not": "is_not",
    "!=": "is_not",
    "<": "<=",
    "=<": "<=",
    "under": "<=",
    "below": "<=",
    "at most": "<=",
    "max": "<=",
    ">": ">=",
    "=>": ">=",
    "over": ">=",
    "above": ">=",
    "at least": ">=",
    "min": ">=",
}
FieldWord = Literal[tuple(FIELDS)]  # type: ignore[valid-type]
OpWord = Literal["is", "is_not", "<=", ">="]
MAX_PRICE_DOLLARS = 100  # one menu item
MAX_ITEM_KCAL = 3000
MAX_DAY_COST_DOLLARS = 1000
MAX_DAY_KCAL = 6000


def _alias(value, aliases):
    if isinstance(value, str):
        value = " ".join(value.strip().lower().split())
        return aliases.get(value, value)
    return value


def _number(value):
    """A number from 12, 12.5, "12", "$12.50", "4$" or "1,200 kcal"; anything else unchanged."""
    if isinstance(value, str):
        text = value.strip().lower().replace(",", "").replace("$", "").strip()
        text = re.sub(r"\s*(k?cal(orie)?s?|dollars?|usd)$", "", text)
        try:
            return float(text)
        except ValueError:
            return value
    return value


class _Condition(_Scoped):
    """A condition on one menu item (planner.match): a field, an operator and a value."""

    field: FieldWord
    op: OpWord
    value: str | float

    @field_validator("field", mode="before")
    @classmethod
    def _field(cls, value):
        return _alias(value, _FIELD_ALIASES)

    @field_validator("op", mode="before")
    @classmethod
    def _op(cls, value):
        return _alias(value, _OP_ALIASES)

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("value must be a name or a number")
        return value

    @model_validator(mode="after")
    def _check_condition(self):
        self.value = condition_value(self.field, self.op, self.value)
        return self

    def condition_key(self) -> tuple:
        return (self.field, self.op, _value_key(self.value))


def _value_key(value):
    """For comparing parses: names lowercased without a leading "the" ("The Pit" is "pit")."""
    if not isinstance(value, str):
        return value
    value = value.lower()
    return value[4:] if value.startswith("the ") else value


def condition_value(field: str, op: str, value):
    """
    The value checked and normalized for the field: a tag name, an allergen, a dish or
    restaurant name, a price in dollars (2 decimals) or whole calories.
    Raises:
        ValueError: The operator does not go with the field, or the value does not fit it.
    """
    if op not in FIELDS[field]:
        raise ValueError(f"{field} takes {' or '.join(FIELDS[field])}, not {op!r}")
    if field in NUMERIC_FIELDS:
        number = _number(value)
        if isinstance(number, str) or number <= 0:
            raise ValueError(f"{field} needs a positive number, got {value!r}")
        if field == "price":
            if number > MAX_PRICE_DOLLARS:
                raise ValueError(f"price is per item, at most ${MAX_PRICE_DOLLARS}")
            return round(float(number), 2)
        if number > MAX_ITEM_KCAL:
            raise ValueError(f"calories are per item, at most {MAX_ITEM_KCAL}")
        return int(round(number))
    if not isinstance(value, str):
        raise ValueError(f"{field} needs a name, got {value!r}")
    value = " ".join(value.split())
    if not 1 <= len(value) <= 80:
        raise ValueError(f"{field} name must be 1 to 80 characters")
    if field == "tag":
        value = _TAG_ALIASES.get(value.lower(), value.lower())
        if value not in TAGS:
            raise ValueError(f"unknown tag {value!r}; known: {', '.join(TAGS)}")
    if field == "allergen":
        value = normalize_allergen(value)
    return value


class Filter(_Condition):
    """Every meal in the scope meets the condition ("make Thursday vegetarian")."""

    type: Literal["filter"]

    def key(self):
        return (self.type, *self.condition_key(), self.day_codes(), self.meal_codes())


class Include(_Condition):
    """At least `times` meals in the scope meet the condition ("pizza on Friday night")."""

    type: Literal["include"]
    times: int = Field(default=1, ge=1, le=21)

    def key(self):
        return (
            self.type,
            *self.condition_key(),
            self.times,
            self.day_codes(),
            self.meal_codes(),
        )


class DayLimit(_Scoped):
    """Each day's total cost or calories under or over a limit ("each day under $40")."""

    type: Literal["day_limit"]
    metric: Literal["cost", "calories"]
    op: Literal["<=", ">="]
    value: float

    @field_validator("metric", mode="before")
    @classmethod
    def _metric(cls, value):
        return {"price": "cost", "budget": "cost", "money": "cost", "kcal": "calories"}.get(
            _alias(value, {}), _alias(value, {})
        )

    @field_validator("op", mode="before")
    @classmethod
    def _op(cls, value):
        return _alias(value, _OP_ALIASES)

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value):
        return _number(value)

    @model_validator(mode="after")
    def _check_limit(self):
        self.meals = ["all"]  # a day's total covers all of its meals
        limit = MAX_DAY_COST_DOLLARS if self.metric == "cost" else MAX_DAY_KCAL
        if not 0 < self.value <= limit:
            raise ValueError(f"a daily {self.metric} limit must be above 0 and at most {limit}")
        self.value = round(self.value, 2) if self.metric == "cost" else float(round(self.value))
        return self

    def key(self):
        return (self.type, self.metric, self.op, self.value, self.day_codes())


class Prefer(_Scoped):
    """
    A preference, never a requirement ("cheaper lunches if possible"). Goal "match" takes a
    condition (field, op, value) like filter; the other goals take none.
    """

    type: Literal["prefer"]
    goal: Literal["cheaper", "fewer_calories", "more_calories", "variety", "match"]
    field: FieldWord | None = None
    op: OpWord | None = None
    value: str | float | None = None

    @field_validator("goal", mode="before")
    @classmethod
    def _goal(cls, value):
        return _alias(
            value,
            {
                "cheap": "cheaper",
                "lower cost": "cheaper",
                "lighter": "fewer_calories",
                "fewer calories": "fewer_calories",
                "heavier": "more_calories",
                "more calories": "more_calories",
                "more variety": "variety",
                "different": "variety",
            },
        )

    @field_validator("field", mode="before")
    @classmethod
    def _field(cls, value):
        return _alias(value, _FIELD_ALIASES)

    @field_validator("op", mode="before")
    @classmethod
    def _op(cls, value):
        return _alias(value, _OP_ALIASES)

    @model_validator(mode="after")
    def _check_goal(self):
        parts = (self.field, self.op, self.value)
        if self.goal == "match":
            if None in parts:
                raise ValueError("goal 'match' needs field, op and value")
            self.value = condition_value(self.field, self.op, self.value)
        elif any(p is not None for p in parts):
            raise ValueError(f"goal {self.goal!r} takes no field, op or value")
        return self

    def key(self):
        return (
            self.type,
            self.goal,
            self.field,
            self.op,
            _value_key(self.value),
            self.day_codes(),
            self.meal_codes(),
        )


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
    Union[Filter, Include, DayLimit, Prefer, CalorieShift],
    Field(discriminator="type"),
]
EDIT_TYPES = ("filter", "include", "day_limit", "prefer", "calorie_shift")


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
    return sorted((e.key() for e in edits), key=_sort_key)


def _sort_key(key) -> str:
    # A frozenset's repr depends on how it was built; sort its members so equal keys sort alike.
    return repr(tuple(sorted(part) if isinstance(part, frozenset) else part for part in key))
