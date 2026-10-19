"""max_meals_per_restaurant: the tutorial's example rule, tested on its own."""

import pytest
from menu_factory import item, menu, request

from planner.registry import get, rules_for
from planner.solver import Status, plan_week

OneItemPerMeal = get("one_item_per_meal")
MaxMealsPerRestaurant = get("max_meals_per_restaurant")

# Three restaurants with two items each.
SIX = menu([item(i, rtr_id=(i + 1) // 2) for i in range(1, 7)])


def test_no_restaurant_supplies_more_than_the_limit():
    result = plan_week(
        request(days=2), SIX, rules=[OneItemPerMeal(), MaxMealsPerRestaurant(limit=2)]
    )
    assert result.ok
    per_restaurant = [sum(m.item.rtr_id == r for m in result.meals) for r in (1, 2, 3)]
    assert per_restaurant == [2, 2, 2]


def test_too_strict_a_limit_is_explained():
    result = plan_week(
        request(days=7), SIX, rules=[OneItemPerMeal(), MaxMealsPerRestaurant(limit=2)]
    )
    assert result.status is Status.INFEASIBLE
    assert result.explanation == (
        "With at most 2 meals from any one restaurant, the 21 meals need at least 11 "
        "different restaurants that fit your other requirements, and there are not enough. "
        "Allow more meals per restaurant."
    )


def test_it_is_off_unless_the_request_turns_it_on():
    assert not any(r.name == "max_meals_per_restaurant" for r in rules_for(request()))
    on = rules_for(request(options={"max_meals_per_restaurant": 4}))
    assert [r.limit for r in on if r.name == "max_meals_per_restaurant"] == [4]


@pytest.mark.parametrize("limit", [0, -1, 2.5, True])
def test_the_limit_must_be_a_positive_whole_number(limit):
    with pytest.raises(ValueError, match="limit"):
        MaxMealsPerRestaurant(limit=limit)


def test_it_stays_quiet_when_another_rule_is_the_problem():
    in_stock = get("in_stock")
    result = plan_week(
        request(),
        menu([item(1, in_stock=False)]),
        rules=[in_stock(), OneItemPerMeal(), MaxMealsPerRestaurant(limit=1)],
    )
    assert "from any one restaurant" not in result.explanation
    assert "out of stock" in result.explanation
