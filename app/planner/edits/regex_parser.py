"""
The regex baseline from the M3 issue: keyword patterns, no model, no guard.

It recognizes the five edit types from fixed phrasings and never asks a clarifying question
or refuses anything, which is what the evaluation measures the LLM parser against.
"""

import re

from planner.edits.result import UNPARSED_MESSAGE, ParseResult
from planner.edits.schema import ParsedRequest

_DAYS = {
    "mon": r"\bmon(day)?s?\b",
    "tue": r"\btue(s|sday)?s?\b",
    "wed": r"\bwed(nesday)?s?\b",
    "thu": r"\bthu(r|rs|rsday)?s?\b",
    "fri": r"\bfri(day)?s?\b",
    "sat": r"\bsat(urday)?s?\b",
    "sun": r"\bsun(day)?s?\b",
    "weekend": r"\bweekends?\b",
    "weekdays": r"\bweekdays?\b",
}
_MEALS = {
    "breakfast": r"\bbreakfasts?\b",
    "lunch": r"\blunch(es)?\b",
    "dinner": r"\b(dinners?|suppers?)\b",
}
_TAG = re.compile(
    r"\b(vegetarian|veggie|vegan|spicy|gluten[- ]free|dairy[- ]free|low[- ]calorie)\b", re.I
)
_PRICE = re.compile(
    r"\b(?:under|below|less than|max(?:imum)?|at most|no more than|cheaper than|up to)\s*"
    r"\$\s*(\d+(?:\.\d{1,2})?)",
    re.I,
)
_STOP = r"(?=\s+(?:on|this|for|at|during|next|any|and)\b|[.,!?]|$)"
_RESTAURANT = re.compile(
    rf"\b(?:nothing|no food|no meals|not|no orders)\s+from\s+(?:the\s+)?(.+?){_STOP}", re.I
)
_ITEM = re.compile(rf"\b(?:no|skip|avoid|without|drop|not)\s+(?:the\s+|any\s+)?(.+?){_STOP}", re.I)
_LESS = re.compile(r"\b(lighter|lower[- ]calorie|fewer calories|less food|smaller)\b", re.I)
_MORE = re.compile(r"\b(heavier|more calories|bigger|more food)\b", re.I)
_CUT = re.compile(r"\b(cut|remove|drop|lose)\s+(\d{2,4})\s*(k?cal|calories)\b", re.I)
_ADD = re.compile(r"\b(add|extra|gain)\s+(\d{2,4})\s*(k?cal|calories)\b", re.I)

DEFAULT_SHIFT = 300


def parse(text: str) -> ParseResult:
    """Parse one request with keyword patterns."""
    days = [d for d, p in _DAYS.items() if re.search(p, text, re.I)] or ["all"]
    meals = [m for m, p in _MEALS.items() if re.search(p, text, re.I)] or ["all"]
    scope = {"days": days, "meals": meals}
    edits = []
    for match in _TAG.finditer(text):
        edits.append({"type": "require_tag", "tag": match.group(1), **scope})
    if match := _PRICE.search(text):
        edits.append({"type": "max_price", "max_price": float(match.group(1)), **scope})
    if match := _RESTAURANT.search(text):
        edits.append({"type": "exclude_restaurant", "restaurant": match.group(1), **scope})
    elif (match := _ITEM.search(text)) and not _TAG.fullmatch(match.group(1).strip()):
        edits.append({"type": "exclude_item", "item": match.group(1), **scope})
    if match := _CUT.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": -int(match.group(2)), "days": days})
    elif match := _ADD.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": int(match.group(2)), "days": days})
    elif _LESS.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": -DEFAULT_SHIFT, "days": days})
    elif _MORE.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": DEFAULT_SHIFT, "days": days})
    if not edits:
        return ParseResult("error", message=UNPARSED_MESSAGE, source="regex")
    try:
        parsed = ParsedRequest.model_validate({"action": "edit", "edits": edits[:5]})
    except ValueError:
        return ParseResult("error", message=UNPARSED_MESSAGE, source="regex")
    return ParseResult("edit", tuple(parsed.edits), source="regex")


class GuardedRegexParser:
    """
    The regex parser behind the same length check and guard as the LLM parser, for running
    the app without a model (EDIT_PARSER=regex). The bare `parse` above is the evaluation
    baseline and has no guard.
    """

    def parse(self, text: str, *, today=None) -> ParseResult:
        """Same interface as LLMEditParser.parse; `today` is unused."""
        from planner.edits import guard

        try:
            text = guard.check_length(text)
        except guard.InvalidRequest as e:
            return ParseResult("error", message=str(e), source="input")
        refusal = guard.check(text)
        if refusal:
            return ParseResult("refuse", message=refusal.message, source="guard")
        return parse(text)
