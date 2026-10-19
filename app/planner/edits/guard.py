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

_RULES = (
    (
        "allergy",
        ALLERGY_MESSAGE,
        (
            rf"\b{_LOOSEN}\b[^.?!]{{0,40}}\ballerg",
            r"\ballerg\w*\b[^.?!]{0,30}\b(doesn'?t|does not|don'?t|do not|won'?t)\s+(matter|count|apply)",
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
            r"remove|forget|drop|skip|scrap|change|set|max out)\b[^.?!]{0,30}\bbudget\b",
            r"\bbudget\b[^.?!]{0,20}\b(to|=|of)\s*\$?\s*\d",
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
_COMPILED = tuple(
    (category, message, tuple(re.compile(p, re.IGNORECASE) for p in patterns))
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
        InvalidRequest: It is empty or longer than MAX_REQUEST_CHARS.
    """
    text = (text or "").strip()
    if not text:
        raise InvalidRequest('Type what you would like to change, like "make Thursday vegetarian".')
    if len(text) > MAX_REQUEST_CHARS:
        raise InvalidRequest(
            f"Please keep edits under {MAX_REQUEST_CHARS} characters; yours has {len(text):,}."
        )
    return text


def check(text: str) -> Refusal | None:
    """The refusal for a request that tries to loosen a rule or instruct the assistant."""
    flat = " ".join(text.split())
    for category, message, patterns in _COMPILED:
        if any(p.search(flat) for p in patterns):
            return Refusal(category, message)
    return None
