"""
Deterministic checks a request passes before any model sees it.

Edits may only add restrictions. Anything that would loosen an allergy or raise the budget
belongs on the profile page, and anything that tries to instruct the assistant is not a meal
edit. These are refused here, in plain code, so a model can never be talked into them; the
solver would still enforce allergies and the budget regardless.
"""

import re
from dataclasses import dataclass

MAX_REQUEST_CHARS = 300

ALLERGY_MESSAGE = (
    "I can't loosen your allergies from here; plan edits can only add restrictions. "
    "If your allergies have changed, update them on your profile page."
)
BUDGET_MESSAGE = (
    "I can't raise or remove your budget from here; plan edits can only add restrictions. "
    "You can change your weekly budget on your profile page."
)
INJECTION_MESSAGE = (
    'I can only make meal edits, like "make Thursday vegetarian" or "no Beef Ribs this week".'
)

_ALLERGENS = (
    r"(peanut|nut|tree nut|egg|dairy|milk|lactose|gluten|wheat|soy|fish|shellfish|sesame)s?"
)
_LOOSEN = (
    r"(ignore|remove|forget|drop|disable|turn off|skip|override|delete|clear|lift|waive|"
    r"bypass|cancel|get rid of|take off|stop)"
)

# A budget pattern is let through only when its own clause says the budget is per day
# ("set a daily budget of $40", "change my budget to $30 a day"). Clauses end at punctuation
# or "and"/"but", so "set my budget to $900, and a daily budget of $40" is still refused.
_PER_DAY = r"\b(daily|day'?s|per day|a day|each day|every day|per-day)\b"
_CLAUSE_END = re.compile(r"[.,;:!?]|\b(and|but|then|also)\b", re.I)

# Each pattern refuses the request when it matches, unless it is a (pattern, unless) pair
# and `unless` matches too.
_RULES = (
    (
        "allergy",
        ALLERGY_MESSAGE,
        (
            rf"\b{_LOOSEN}\b[^.?!]{{0,40}}\ballerg",
            r"\ballerg\w*\b[^.?!]{0,30}\b(doesn'?t|does not|don'?t|do not|won'?t)\s+"
            r"(matter|count|apply|exist)",
            r"\b(i'?m|i am|im)\s+(not|no longer)\s+allergic\b",
            r"\ballergic\b[^.?!]{0,25}\b(any ?more|after all)\b",
            r"\ballerg\w*\b[^.?!]{0,20}\b(is|are|was|were)\s+(fake|wrong|a mistake|gone|over)\b",
            rf"\b(i can|i could|let me|i want to|i'?ll)\s+(eat|have)\b[^.?!]{{0,30}}\b{_ALLERGENS}\b"
            r"[^.?!]{0,25}\b(now|again|anyway|any ?more|after all|this week)\b",
            rf"\b(add|put|include)\b[^.?!]{{0,20}}\b{_ALLERGENS}\b[^.?!]{{0,15}}\bback\b",
        ),
    ),
    (
        "budget",
        BUDGET_MESSAGE,
        (
            r"\b(raise|increase|bump|up|double|triple|extend|lift|ignore|exceed|go over|blow|"
            r"remove|forget|drop|skip|scrap|max out)\b[^.?!]{0,30}\bbudget\b",
            # Setting the budget to an amount could raise it; a daily budget is a new limit on
            # top of the weekly one (day_limit), so only that may be set from here.
            (r"\b(change|set)\b[^.?!]{0,30}\bbudget\b", _PER_DAY),
            (r"\bbudget\b[^.?!]{0,20}\b(to|=|of)\s*\$?\s*\d", _PER_DAY),
            r"\bover (my |the )?budget\b",
            r"\bno (more )?budget\b",
            r"\bspend (more|whatever|as much|unlimited)\b",
            r"\b(cost|money|price) (doesn'?t|does not|is no) (matter|object)\b",
        ),
    ),
    (
        "injection",
        INJECTION_MESSAGE,
        (
            r"\b(ignore|disregard|forget|override)\b[^.?!]{0,40}\b(instructions?|rules?|prompts?|"
            r"above|previous|prior|system|guidelines?|constraints?)\b",
            r"\bsystem\s+prompt\b",
            r"\byou are now\b",
            r"\b(developer|admin|god|debug)\s+mode\b",
            r"\bjailbreak",
            r"\bpretend\b[^.?!]{0,30}\b(you|to be|that)\b",
            r"\bact as\b",
            r"\bnew instructions?\b",
            r"</?\s*(system|assistant|user|instructions?)\s*>",
            r"\"(action|type|edits)\"\s*:",
            r"\b(reveal|print|show|repeat)\b[^.?!]{0,30}\b(prompt|instructions|rules)\b",
        ),
    ),
)


def _compile(pattern):
    pattern, unless = pattern if isinstance(pattern, tuple) else (pattern, None)
    return re.compile(pattern, re.I), unless and re.compile(unless, re.I)


_COMPILED = tuple(
    (category, message, tuple(_compile(p) for p in patterns))
    for category, message, patterns in _RULES
)


class InvalidRequest(ValueError):
    """The text is empty or too long. The message is shown to the user."""


@dataclass(frozen=True)
class Refusal:
    """Why a request is refused: its category and the message for the user."""

    category: str  # "allergy", "budget" or "injection"
    message: str


def check_length(text: str | None) -> str:
    """
    The request with surrounding whitespace removed.
    Raises:
        InvalidRequest: It is not text, is empty, or is longer than MAX_REQUEST_CHARS.
    """
    if not isinstance(text, str | None):
        text = None  # a number or list in the JSON body: treat it as no request
    text = (text or "").strip()
    if not text:
        raise InvalidRequest('Type what you would like to change, like "make Thursday vegetarian".')
    if len(text) > MAX_REQUEST_CHARS:
        raise InvalidRequest(
            f"Please keep edits under {MAX_REQUEST_CHARS} characters; yours has {len(text):,}."
        )
    return text


def _clause(text: str, start: int, end: int) -> str:
    """The clause of text that contains text[start:end]."""
    before = [m.end() for m in _CLAUSE_END.finditer(text, 0, start)]
    after = _CLAUSE_END.search(text, end)
    return text[before[-1] if before else 0 : after.start() if after else len(text)]


def _refuses(pattern, unless, text: str) -> bool:
    """True if some match of pattern is not excused by `unless` in its own clause."""
    return any(
        not (unless and unless.search(_clause(text, m.start(), m.end())))
        for m in pattern.finditer(text)
    )


def check(text: str) -> Refusal | None:
    """The refusal for a request that tries to loosen a rule or instruct the assistant."""
    flat = " ".join(text.split())
    for category, message, patterns in _COMPILED:
        if any(_refuses(p, unless, flat) for p, unless in patterns):
            return Refusal(category, message)
    return None
