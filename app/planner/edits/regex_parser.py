"""
The regex baseline from the M3 issue: keyword patterns, no model, no guard.

It recognizes common fixed phrasings of each edit type (tags, prices, calories, restaurants
and dishes to avoid, daily limits, calorie shifts, a few preferences) and never asks a
clarifying question or refuses anything, which is what the evaluation measures the LLM parser
against.
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
    r"\b(?:(no|not|nothing|non)[- ])?(vegetarian|veggie|vegan|spicy|gluten[- ]free|dairy[- ]free|"
    r"low[- ]calorie)\b",
    re.I,
)
_MONEY = r"\$\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*\$"
_UNDER = (
    r"(?:under|below|less than|max(?:imum)?|at most|no more than|cheaper than|up to|within|"
    r"(?:doesn'?t|does not|don'?t|do not|never|not)\s+(?:cross|exceed|go over|go above))"
)
_PRICE = re.compile(rf"\b{_UNDER}\s*(?:{_MONEY})", re.I)
_KCAL_UNDER = re.compile(
    rf"\b(?:{_UNDER}|over|more than)\s*(\d[\d,]*)\s*(?:k?cal|calories)\b", re.I
)
_KCAL_OVER = re.compile(r"\b(?:at least|min(?:imum)?)\s*(\d[\d,]*)\s*(?:k?cal|calories)\b", re.I)
_PER_DAY = re.compile(r"\b(each|every|per|a|any|no)\s+day\b|\bdaily\b|\bday's\b", re.I)
_STOP = r"(?=\s+(?:on|this|for|at|during|next|any|and|every|each)\b|[.,!?]|$)"
_ONLY_FROM = re.compile(rf"\bonly\s+(?:from\s+)?(?:the\s+)?(.+?){_STOP}", re.I)
_SOME_FROM = re.compile(rf"\bsomething\s+from\s+(?:the\s+)?(.+?){_STOP}", re.I)
_RESTAURANT = re.compile(
    rf"\b(?:nothing|no food|no meals|not|no orders)\s+from\s+(?:the\s+)?(.+?){_STOP}", re.I
)
_ITEM = re.compile(rf"\b(?:no|skip|avoid|without|drop|not)\s+(?:the\s+|any\s+)?(.+?){_STOP}", re.I)
_LESS = re.compile(r"\b(lighter|lower[- ]calorie|fewer calories|less food|smaller)\b", re.I)
_MORE = re.compile(r"\b(heavier|more calories|bigger|more food)\b", re.I)
_CUT = re.compile(r"\b(cut|remove|drop|lose)\s+(\d{2,4})\s*(k?cal|calories)\b", re.I)
_ADD = re.compile(r"\b(add|extra|gain)\s+(\d{2,4})\s*(k?cal|calories)\b", re.I)
_CHEAPER = re.compile(r"\bcheaper\b(?!\s+than)", re.I)
_VARIETY = re.compile(r"\b(more variety|mix it up|less repetit\w*|fewer repeats)\b", re.I)
_SOFT = re.compile(r"\b(if possible|when you can|where possible|prefer|ideally)\b", re.I)

DEFAULT_SHIFT = 300


def _money(match) -> float:
    return float(match.group(1) or match.group(2))


def parse(text: str) -> ParseResult:
    """Parse one request with keyword patterns."""
    days = [d for d, p in _DAYS.items() if re.search(p, text, re.I)] or ["all"]
    meals = [m for m, p in _MEALS.items() if re.search(p, text, re.I)] or ["all"]
    scope = {"days": days, "meals": meals}
    soft = bool(_SOFT.search(text))
    per_day = bool(_PER_DAY.search(text))
    edits = []

    def condition(field, op, value):
        if soft:
            edits.append(
                {
                    "type": "prefer",
                    "goal": "match",
                    "field": field,
                    "op": op,
                    "value": value,
                    **scope,
                }
            )
        else:
            edits.append({"type": "filter", "field": field, "op": op, "value": value, **scope})

    for match in _TAG.finditer(text):
        condition("tag", "is_not" if match.group(1) else "is", match.group(2))
    if match := _PRICE.search(text):
        if per_day:
            edits.append(
                {
                    "type": "day_limit",
                    "metric": "cost",
                    "op": "<=",
                    "value": _money(match),
                    "days": days,
                }
            )
        else:
            condition("price", "<=", _money(match))
    for pattern, op in ((_KCAL_UNDER, "<="), (_KCAL_OVER, ">=")):
        if match := pattern.search(text):
            kcal = int(match.group(1).replace(",", ""))
            if per_day:
                edits.append(
                    {
                        "type": "day_limit",
                        "metric": "calories",
                        "op": op,
                        "value": kcal,
                        "days": days,
                    }
                )
            else:
                condition("calories", op, kcal)
    if match := _RESTAURANT.search(text):
        condition("restaurant", "is_not", match.group(1))
    elif match := _ONLY_FROM.search(text):
        condition("restaurant", "is", match.group(1))
    elif match := _SOME_FROM.search(text):
        edits.append(
            {"type": "include", "field": "restaurant", "op": "is", "value": match.group(1), **scope}
        )
    elif (
        (match := _ITEM.search(text))
        and not _TAG.fullmatch(match.group(1).strip())
        and not any(e["type"] == "day_limit" for e in edits)  # "no day over 2,000 calories"
    ):
        condition("dish", "is_not", match.group(1))
    if match := _CUT.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": -int(match.group(2)), "days": days})
    elif match := _ADD.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": int(match.group(2)), "days": days})
    elif _LESS.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": -DEFAULT_SHIFT, "days": days})
    elif _MORE.search(text):
        edits.append({"type": "calorie_shift", "kcal_delta": DEFAULT_SHIFT, "days": days})
    if _CHEAPER.search(text) and not _PRICE.search(text):
        edits.append({"type": "prefer", "goal": "cheaper", **scope})
    if _VARIETY.search(text):
        edits.append({"type": "prefer", "goal": "variety", **scope})
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
