"""
Which meals of a plan a rule applies to, e.g. "Thursday", "the weekend" or "all dinners".

Plan edits ("make Thursday vegetarian") turn into rules limited to a `MealScope`. A scope is a
set of days and a set of meal numbers; None means "all of them".
"""

from dataclasses import dataclass
from datetime import date

from planner.menu import MEAL_NAMES, WEEKDAYS


@dataclass(frozen=True)
class MealScope:
    """
    The meals a rule covers.
    Attributes:
        days: Dates covered, or None for every day of the plan.
        meals: Meal numbers covered (1 breakfast, 2 lunch, 3 dinner), or None for all.
    """

    days: frozenset[date] | None = None
    meals: frozenset[int] | None = None

    def __post_init__(self):
        if self.days is not None:
            object.__setattr__(self, "days", frozenset(self.days))
        if self.meals is not None:
            object.__setattr__(self, "meals", frozenset(self.meals))
            if not self.meals <= set(MEAL_NAMES):
                raise ValueError(f"unknown meal numbers in {sorted(self.meals)}")

    def covers(self, slot) -> bool:
        """True if the scope includes the slot (anything with .day and .meal)."""
        return (self.days is None or slot.day in self.days) and (
            self.meals is None or slot.meal in self.meals
        )

    def describe(self) -> str:
        """For messages, e.g. "Thu Oct 22 dinner", "every day" or "Sat, Sun lunch and dinner"."""
        days = (
            "every day"
            if self.days is None
            else ", ".join(f"{WEEKDAYS[d.weekday()]} {d:%b} {d.day}" for d in sorted(self.days))
        )
        if self.meals is None:
            return days
        names = [MEAL_NAMES[m] for m in sorted(self.meals)]
        meals = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        return f"{days} {meals}"


EVERY_MEAL = MealScope()
