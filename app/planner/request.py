"""
What the user asks the planner for: the week to plan, their targets, and their allergens and
preferences. A `PlanRequest` is checked when it is built, so the solver never sees bad input.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import MappingProxyType

from planner.allergens import parse_allergens
from planner.menu import MEAL_NAMES, MEAL_TIMES, WEEKDAYS
from planner.targets import (
    MAX_DAILY_KCAL,
    MAX_WEEKLY_BUDGET_CENTS,
    MIN_DAILY_KCAL,
    MIN_WEEKLY_BUDGET_CENTS,
)

MAX_DAYS = 14


class InvalidPlanRequest(ValueError):
    """The request cannot be planned as given. The message is meant for the user."""


@dataclass(frozen=True)
class Slot:
    """One meal to plan: a day and a meal number (1 breakfast, 2 lunch, 3 dinner)."""

    index: int  # position in PlanRequest.slots(), 0-based
    day: date
    meal: int

    @property
    def weekday(self) -> str:
        """ "Mon".."Sun"."""
        return WEEKDAYS[self.day.weekday()]

    @property
    def time(self) -> int:
        """Order time, HHMM."""
        return MEAL_TIMES[self.meal]

    @property
    def meal_name(self) -> str:
        """ "breakfast", "lunch" or "dinner"."""
        return MEAL_NAMES[self.meal]

    @property
    def label(self) -> str:
        """For messages, e.g. "Mon Oct 19 breakfast"."""
        return f"{self.weekday} {self.day:%b} {self.day.day} {self.meal_name}"


@dataclass(frozen=True)
class PlanRequest:
    """
    A week to plan for one user.
    Attributes:
        daily_calorie_target: Calories per day; each day must land within 10% of it.
        weekly_budget_cents: Most the whole plan may cost, tax and fees included.
        start: First day of the plan.
        allergens: Allergens to avoid, any spelling ("Egg" and "Eggs" both work).
        preferences: Words to look for in item names and descriptions, e.g. ("spicy",).
        days: Number of days to plan, starting at start.
        meals: Meal numbers to plan each day.
        options: Per-rule settings keyed by rule name, e.g.
            {"max_meals_per_restaurant": 3} or {"prefer_variety": {"weight": 900}}.
            True enables a rule that is off by default; False disables one.
    """

    daily_calorie_target: int
    weekly_budget_cents: int
    start: date
    allergens: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()
    days: int = 7
    meals: tuple[int, ...] = (1, 2, 3)
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if not _is_int(self.daily_calorie_target) or not (
            MIN_DAILY_KCAL <= self.daily_calorie_target <= MAX_DAILY_KCAL
        ):
            raise InvalidPlanRequest(
                f"Daily calorie target must be a whole number from {MIN_DAILY_KCAL:,} to "
                f"{MAX_DAILY_KCAL:,}; got {self.daily_calorie_target!r}."
            )
        if not _is_int(self.weekly_budget_cents) or not (
            MIN_WEEKLY_BUDGET_CENTS <= self.weekly_budget_cents <= MAX_WEEKLY_BUDGET_CENTS
        ):
            raise InvalidPlanRequest(
                f"Weekly budget must be from ${MIN_WEEKLY_BUDGET_CENTS / 100:,.2f} to "
                f"${MAX_WEEKLY_BUDGET_CENTS / 100:,.2f}; got {self.weekly_budget_cents!r} cents."
            )
        if not isinstance(self.start, date):
            raise InvalidPlanRequest(f"start must be a date; got {self.start!r}.")
        if not _is_int(self.days) or not 1 <= self.days <= MAX_DAYS:
            raise InvalidPlanRequest(f"days must be from 1 to {MAX_DAYS}; got {self.days!r}.")
        meals = tuple(self.meals)
        if not meals or len(set(meals)) != len(meals) or not set(meals) <= set(MEAL_TIMES):
            raise InvalidPlanRequest(
                f"meals must be distinct meal numbers from {sorted(MEAL_TIMES)}; got {meals!r}."
            )
        # Frozen dataclass: normalize through object.__setattr__.
        object.__setattr__(self, "meals", tuple(sorted(meals)))
        object.__setattr__(self, "allergens", tuple(self.allergens))
        object.__setattr__(self, "preferences", tuple(self.preferences))
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))

    @classmethod
    def from_profile(
        cls,
        *,
        daily_calorie_target: int | None,
        weekly_budget_cents: int | None,
        allergies: str | None,
        preferences: str | None,
        start: date,
        **kwargs,
    ) -> "PlanRequest":
        """
        Build a request from a User row's fields as stored.
        Args:
            daily_calorie_target: User.daily_calorie_target (None if not set).
            weekly_budget_cents: User.weekly_budget_cents (None if not set).
            allergies: User.allergies, comma-separated.
            preferences: User.preferences, comma-separated.
            start: First day to plan.
            **kwargs: Any other PlanRequest field (days, meals, options).
        Raises:
            InvalidPlanRequest: A target is missing or invalid.
        """
        missing = [
            label
            for label, value in (
                ("daily calorie target", daily_calorie_target),
                ("weekly budget", weekly_budget_cents),
            )
            if value is None
        ]
        if missing:
            raise InvalidPlanRequest(
                f"Set your {' and '.join(missing)} on your profile before planning a week."
            )
        return cls(
            daily_calorie_target=daily_calorie_target,
            weekly_budget_cents=weekly_budget_cents,
            start=start,
            allergens=parse_allergens(allergies),
            preferences=parse_allergens(preferences),  # same comma-separated format
            **kwargs,
        )

    def dates(self) -> tuple[date, ...]:
        """The days planned, in order."""
        return tuple(self.start + timedelta(days=i) for i in range(self.days))

    def slots(self) -> tuple[Slot, ...]:
        """Every meal to plan, day by day, breakfast first."""
        pairs = [(day, meal) for day in self.dates() for meal in self.meals]
        return tuple(Slot(index, day, meal) for index, (day, meal) in enumerate(pairs))


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
