"""What any edit parser returns."""

from dataclasses import dataclass, field
from typing import Literal

UNPARSED_MESSAGE = (
    "Sorry, I couldn't turn that into a plan edit. Try something like "
    '"make Thursday vegetarian under $10" or "no Beef Ribs this week".'
)


@dataclass(frozen=True)
class ParseResult:
    """
    The outcome of parsing one request.
    Attributes:
        action: "edit" (apply `edits`), "clarify" (ask `message`), "refuse" (show `message`)
            or "error" (the request could not be parsed; show `message`).
        edits: Validated edits from planner.edits.schema, when action is "edit".
        message: The question, refusal or error for the user.
        source: Who decided: "input" (length check), "guard", "llm" or "regex".
        attempts: Model calls made (0 when the guard or input check decided).
    """

    action: Literal["edit", "clarify", "refuse", "error"]
    edits: tuple = field(default=())
    message: str = ""
    source: str = ""
    attempts: int = 0
