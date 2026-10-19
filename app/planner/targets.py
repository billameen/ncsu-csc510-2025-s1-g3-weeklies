"""
The two numbers the planner plans around, as the user types them on Edit Profile.

- Daily calorie target: whole calories per day. Each planned day must land within 10% of it.
- Weekly budget: dollars for the whole week (21 meals), tax and fees included. Stored in cents
  in ``User.weekly_budget_cents``, like ``User.wallet``.

The bounds only catch typos and unit mix-ups (a budget typed in cents, a monthly calorie
count). Whether a week can actually be planned within them is the solver's job.
"""

from decimal import Decimal, InvalidOperation

MIN_DAILY_KCAL = 800
MAX_DAILY_KCAL = 6000

MIN_WEEKLY_BUDGET_CENTS = 1_00  # $1
MAX_WEEKLY_BUDGET_CENTS = 5_000_00  # $5,000


class TargetError(ValueError):
    """A target the user typed is not usable. The message is shown on the form as is."""


def parse_daily_calorie_target(raw: str | None) -> int | None:
    """
    Parse the daily calorie target field.
    Args:
        raw: The submitted text, e.g. "2,200" or " 2200 ". None or blank means "not set".
    Returns:
        int | None: Calories per day, or None when not set.
    Raises:
        TargetError: Not a whole number, or outside MIN_DAILY_KCAL..MAX_DAILY_KCAL.
    """
    text = _clean(raw)
    if not text:
        return None
    if not text.isdigit():
        raise TargetError("Daily calorie target must be a whole number, like 2000.")
    kcal = int(text)
    if not MIN_DAILY_KCAL <= kcal <= MAX_DAILY_KCAL:
        raise TargetError(
            f"Daily calorie target must be between {MIN_DAILY_KCAL:,} and "
            f"{MAX_DAILY_KCAL:,} calories."
        )
    return kcal


def parse_weekly_budget(raw: str | None) -> int | None:
    """
    Parse the weekly budget field, typed in dollars.
    Args:
        raw: The submitted text, e.g. "150", "$150.50" or "1,200". None or blank means
            "not set".
    Returns:
        int | None: The budget in cents, or None when not set.
    Raises:
        TargetError: Not an amount in dollars and cents, or outside the allowed range.
    """
    text = _clean(raw).removeprefix("$").strip()
    if not text:
        return None
    try:
        dollars = Decimal(text)
    except InvalidOperation:
        raise TargetError("Weekly budget must be an amount in dollars, like 150 or 150.50.")
    # Decimal accepts "NaN", "Infinity" and "1e3"; only plain amounts with at most cents pass.
    if not dollars.is_finite() or "e" in text.lower() or dollars.as_tuple().exponent < -2:
        raise TargetError("Weekly budget must be an amount in dollars, like 150 or 150.50.")
    cents = int(dollars * 100)
    if not MIN_WEEKLY_BUDGET_CENTS <= cents <= MAX_WEEKLY_BUDGET_CENTS:
        raise TargetError(
            f"Weekly budget must be between ${MIN_WEEKLY_BUDGET_CENTS / 100:,.2f} and "
            f"${MAX_WEEKLY_BUDGET_CENTS / 100:,.2f}."
        )
    return cents


def format_budget(cents: int | None) -> str:
    """Cents as the dollar text the form shows, e.g. 15050 -> "150.50"; None -> ""."""
    return "" if cents is None else f"{cents / 100:.2f}"


def _clean(raw: str | None) -> str:
    """Strip whitespace and thousands separators."""
    return (raw or "").strip().replace(",", "")
