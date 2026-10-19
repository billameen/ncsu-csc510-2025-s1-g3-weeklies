"""
The LLM parser: the model proposes edits in the fixed format, and code checks them.

The request first passes the length check and the guard, so refusals never depend on the
model. The model's reply must be one JSON object that validates against
planner.edits.schema; if it does not, the model gets one retry with the error, and after
that the request is reported as not understood. Nothing the model writes is shown to the
user except a clarifying question.

The prompt is versioned in app/planner/prompts/edit_parser_<version>.txt. Changing it changes
every prompt the evaluation recorded, so a new version needs a new recording
(`python -m eval.edits --live`).
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from planner.edits import guard
from planner.edits.result import UNPARSED_MESSAGE, ParseResult
from planner.edits.schema import ParsedRequest
from planner.tags import TAGS

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
PROMPT_VERSION = "v2"
DEFAULT_TIMEOUT_S = 60.0  # the local model can take ~10 s a call on a laptop CPU
RETRIES = 1

REFUSE_MESSAGE = (
    "I can't make that change here. Plan edits can only add restrictions; allergies and the "
    "budget are changed on your profile page."
)
TIMEOUT_MESSAGE = "The assistant took too long to answer. Please try again in a moment."
UNAVAILABLE_MESSAGE = "The assistant is unavailable right now. Please try again later."

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edit-llm")
_FENCE = re.compile(r"```(?:json)?", re.I)


def load_prompt(version: str = PROMPT_VERSION) -> tuple[str, str]:
    """The (system, user template) pair from prompts/edit_parser_<version>.txt."""
    text = (PROMPTS_DIR / f"edit_parser_{version}.txt").read_text(encoding="utf-8")
    system, user = text.split("### USER", 1)
    system = system.replace("### SYSTEM", "", 1).strip()
    return system.replace("{tags}", ", ".join(f'"{t}"' for t in TAGS)), user.strip()


def extract_json(raw: str) -> dict:
    """
    The JSON object in a model reply, ignoring code fences and any text around it.
    Raises:
        ValueError: There is no parseable JSON object.
    """
    text = _FENCE.sub("", raw or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the reply")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    return data


class LLMEditParser:
    """
    Parses plan-edit requests with an LLM.
    Args:
        llm: Anything with generate(system, prompt) -> str, e.g. llm_toolkit.LLM, or a
            recording or replay of one in the evaluation.
        version: Prompt version to load.
        timeout_s: How long to wait for each model call.
        retries: Extra attempts after an invalid reply.
    """

    def __init__(
        self, llm, *, version=PROMPT_VERSION, timeout_s=DEFAULT_TIMEOUT_S, retries=RETRIES
    ):
        self.llm = llm
        self.version = version
        self.system, self.template = load_prompt(version)
        self.timeout_s = timeout_s
        self.retries = retries

    def prompt_for(self, text: str, today: date) -> str:
        """The user prompt for one request."""
        return self.template.replace("{today}", f"{today:%A}").replace("{request}", text)

    def parse(self, text: str, *, today: date) -> ParseResult:
        """
        Parse one request.
        Args:
            text: What the user typed.
            today: Today's date; the model is told the weekday so "tomorrow" can resolve.
        """
        try:
            text = guard.check_length(text)
        except guard.InvalidRequest as e:
            return ParseResult("error", message=str(e), source="input")
        refusal = guard.check(text)
        if refusal:
            return ParseResult("refuse", message=refusal.message, source="guard")

        prompt = self.prompt_for(text, today)
        attempts = 0
        for _ in range(1 + self.retries):
            attempts += 1
            try:
                raw = self._call(prompt)
            except FutureTimeout:
                return ParseResult(
                    "error", message=TIMEOUT_MESSAGE, source="llm", attempts=attempts
                )
            except Exception:
                return ParseResult(
                    "error", message=UNAVAILABLE_MESSAGE, source="llm", attempts=attempts
                )
            try:
                parsed = ParsedRequest.model_validate(extract_json(raw))
            except (ValueError, ValidationError) as e:
                prompt = (
                    f"{self.prompt_for(text, today)}\n\nYour previous reply was not valid: "
                    f"{_short(e)}. Reply with only the JSON object."
                )
                continue
            return self._result(parsed, attempts)
        return ParseResult("error", message=UNPARSED_MESSAGE, source="llm", attempts=attempts)

    def _call(self, prompt: str) -> str:
        return _POOL.submit(self.llm.generate, self.system, prompt).result(timeout=self.timeout_s)

    @staticmethod
    def _result(parsed: ParsedRequest, attempts: int) -> ParseResult:
        if parsed.action == "edit":
            return ParseResult("edit", tuple(parsed.edits), source="llm", attempts=attempts)
        if parsed.action == "clarify":
            return ParseResult(
                "clarify", message=parsed.question.strip(), source="llm", attempts=attempts
            )
        return ParseResult("refuse", message=REFUSE_MESSAGE, source="llm", attempts=attempts)


def _short(error: Exception) -> str:
    """The first line of an error, at most 200 characters, for the retry prompt."""
    first = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
    return first[:200]
