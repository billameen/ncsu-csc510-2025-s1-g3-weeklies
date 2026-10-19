"""prefer_low_cost on its own: a tiny menu with a known best answer."""

from menu_factory import item, menu, request

from planner.registry import get
from planner.solver import Status, plan_week

OneItemPerMeal, DailyCalories = get("one_item_per_meal"), get("daily_calories")
PreferLowCost = get("prefer_low_cost")


def test_the_cheapest_item_is_picked_for_every_meal():
    result = plan_week(
        request(days=2),
        menu([item(1, price_cents=900), item(2, price_cents=400), item(3, price_cents=700)]),
        rules=[OneItemPerMeal(), PreferLowCost()],
    )
    assert result.status is Status.OPTIMAL
    assert {m.itm_id for m in result.meals} == {2}


def test_known_best_answer_under_a_calorie_band():
    # Target 1,500 kcal (1,350-1,650). Options: A 300 kcal $3, B 500 kcal $5, C 700 kcal $6.
    # Valid days: A+B+C = 1,500 for $14, or B+B+B = 1,500 for $15, or A+C+C... = 1,700 (too
    # many), A+A+C = 1,300 (too few). Best is one each of A, B and C: $14 plus tax and fees.
    result = plan_week(
        request(kcal=1500),
        menu(
            [
                item(1, price_cents=300, calories=300),
                item(2, price_cents=500, calories=500),
                item(3, price_cents=600, calories=700),
            ]
        ),
        rules=[OneItemPerMeal(), DailyCalories(), PreferLowCost()],
    )
    assert result.status is Status.OPTIMAL
    assert sorted(m.itm_id for m in result.meals) == [1, 2, 3]
    assert result.kcal_by_day() == {result.meals[0].day: 1500}
