"""calorie_shift: some days aim for a different calorie total."""

from datetime import date

import pytest
from menu_factory import item, menu, request

from planner.context import PlanContext
from planner.registry import get
from planner.solver import Status, plan_week

OneItemPerMeal, DailyCalories, CalorieShift = (
    get("one_item_per_meal"),
    get("daily_calories"),
    get("calorie_shift"),
)
TUESDAY = date(2026, 10, 20)
ITEMS = menu([item(1, calories=400), item(2, calories=600), item(3, calories=800)])


def test_shifted_days_land_in_the_band_around_the_new_target():
    result = plan_week(
        request(kcal=1800, days=2),
        ITEMS,
        rules=[OneItemPerMeal(), CalorieShift(-600, days={TUESDAY}), DailyCalories()],
    )
    kcal = result.kcal_by_day()
    assert 1620 <= kcal[date(2026, 10, 19)] <= 1980  # unchanged day
    assert 1080 <= kcal[TUESDAY] <= 1320  # 1,200 +/- 10%


def test_without_days_every_day_shifts():
    ctx = PlanContext(request(kcal=1800, days=3), ITEMS)
    CalorieShift(300).apply(ctx)
    assert set(ctx.kcal_targets.values()) == {2100}


def test_shifts_are_clamped_to_the_profile_bounds():
    ctx = PlanContext(request(kcal=1000, days=1), ITEMS)
    CalorieShift(-900).apply(ctx)
    assert ctx.kcal_target(date(2026, 10, 19)) == 800


def test_an_unreachable_adjusted_target_is_explained_as_adjusted():
    result = plan_week(
        request(kcal=1800, days=2),
        ITEMS,
        rules=[OneItemPerMeal(), CalorieShift(1000, days={TUESDAY}), DailyCalories()],
    )
    assert result.status is Status.INFEASIBLE
    assert result.explanation.startswith("Your adjusted target of 2,800 kcal")
    assert "Tue Oct 20" in result.explanation


@pytest.mark.parametrize("bad", [0, 1001, -1001, 2.5, True])
def test_shifts_must_be_non_zero_and_bounded(bad):
    with pytest.raises(ValueError):
        CalorieShift(bad)
