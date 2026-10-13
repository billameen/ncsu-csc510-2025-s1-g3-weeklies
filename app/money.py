"""Money helpers: every amount is an integer number of cents.

Why money is never a float here
-------------------------------
Binary floating point cannot represent most decimal fractions exactly.
``0.29`` is really ``0.28999999999999998``, so ``int(0.29 * 100)`` is ``28``:
the old ``_dollars_to_cents`` helper silently lost a cent on 4,586 of the first
100,000 cent amounts. Here, user input is parsed with :class:`decimal.Decimal`
straight from its text, rounded once with ``ROUND_HALF_UP``, and stored and
added as an ``int``. Floats are only ever produced for display, never stored.
"""
import re
from decimal import Decimal, DecimalException, ROUND_HALF_UP

#: Largest absolute amount accepted for a single money value ($1,000,000.00).
MAX_CENTS = 100_000_000

#: Longest input text accepted, so oversized form values are rejected before parsing.
MAX_INPUT_LENGTH = 32

# Plain ASCII decimal only: no exponents, underscores, Unicode digits, NaN or Infinity.
_AMOUNT_RE = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", re.ASCII)

_ONE = Decimal(1)
_HUNDRED = Decimal(100)


class MoneyError(ValueError):
    """Base class for amounts that cannot be turned into cents."""


class InvalidAmount(MoneyError):
    """The value is missing, non-numeric, NaN or infinite."""


class AmountOutOfRange(MoneyError):
    """The value's magnitude exceeds :data:`MAX_CENTS`."""


def parse_cents(value) -> int:
    """Convert a dollar amount to integer cents, rounding half up.

    Accepts ``str`` (e.g. ``"12.34"``, ``" $0.29 "``, ``"-1.5"``), ``int``,
    ``Decimal`` and, for older callers that still pass computed totals,
    binary floats (converted through their shortest repr, so ``0.29`` stays
    ``"0.29"``). Extra decimal places are rounded half up: ``"1.005"`` -> 101.
    Text must be a plain ASCII decimal of at most ``MAX_INPUT_LENGTH``
    characters; exponents (``"1e5"``), underscores and non-ASCII digits are
    rejected.

    Raises:
        InvalidAmount: missing, non-numeric, boolean, NaN or infinite input.
        AmountOutOfRange: ``abs(result) > MAX_CENTS``.
    """
    if value is None or isinstance(value, bool):
        raise InvalidAmount(f"not an amount: {value!r}")
    if isinstance(value, Decimal):
        amount = value
    else:
        text = str(value).strip()
        if len(text) > MAX_INPUT_LENGTH:
            raise InvalidAmount("amount text too long")
        negative = text.startswith("-")
        if negative:
            text = text[1:].lstrip()
        if text.startswith("$"):
            text = text[1:].lstrip()
        if not _AMOUNT_RE.fullmatch(text):
            raise InvalidAmount(f"not an amount: {value!r}")
        amount = Decimal(text)
        if negative:
            amount = -amount
    if not amount.is_finite():
        raise InvalidAmount(f"not a finite amount: {value!r}")
    try:
        if abs(amount) * _HUNDRED > MAX_CENTS:
            raise AmountOutOfRange(f"amount too large: {value!r}")
        return int((amount * _HUNDRED).quantize(_ONE, rounding=ROUND_HALF_UP))
    except DecimalException:
        raise AmountOutOfRange(f"amount too large: {value!r}") from None


def cents_to_str(cents: int) -> str:
    """Plain decimal string for an amount in cents: ``1234 -> "12.34"``."""
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"


def format_cents(cents: int) -> str:
    """Display string with a dollar sign and thousands separators.

    ``123456 -> "$1,234.56"``, ``-100 -> "-$1.00"``.
    """
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{frac:02d}"
