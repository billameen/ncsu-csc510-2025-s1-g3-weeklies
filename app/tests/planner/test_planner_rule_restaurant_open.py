"""restaurant_open on its own: items only from restaurants open at that meal."""

from menu_factory import OPEN_ALL_DAY, item, menu, request, restaurant

from planner.registry import get
from planner.solver import plan_week

OneItemPerMeal, RestaurantOpen = get("one_item_per_meal"), get("restaurant_open")

DINNER_ONLY = {day: (1700, 2200) for day in OPEN_ALL_DAY}


def test_each_meal_comes_from_a_restaurant_open_at_that_time():
    result = plan_week(
        request(),
        menu(
            [item(1, rtr_id=1), item(2, rtr_id=2)],
            [restaurant(1, hours=DINNER_ONLY), restaurant(2, hours={"Mon": (900, 1500)})],
        ),
        rules=[OneItemPerMeal(), RestaurantOpen()],
    )
    assert result.ok
    assert [(m.meal, m.itm_id) for m in result.meals] == [(1, 2), (2, 2), (3, 1)]


def test_closed_status_and_unknown_restaurants_are_skipped():
    result = plan_week(
        request(meals=(2,)),
        menu(
            [item(1, rtr_id=1), item(2, rtr_id=2), item(3, rtr_id=99)],
            [restaurant(1, status_open=False), restaurant(2)],
        ),
        rules=[OneItemPerMeal(), RestaurantOpen()],
    )
    assert [m.itm_id for m in result.meals] == [2]


def test_everything_closed_is_explained_with_the_meal_time():
    result = plan_week(
        request(days=7, meals=(1,)),
        menu([item(1)], [restaurant(1, hours=DINNER_ONLY)]),
        rules=[OneItemPerMeal(), RestaurantOpen()],
    )
    assert result.explanation == (
        "No breakfast can be planned on any day: of 1 menu items, "
        "1 come from restaurants closed at 10:00."
    )


def test_no_restaurant_taking_orders_is_one_sentence_without_meal_times():
    result = plan_week(
        request(days=7),
        menu([item(1)], [restaurant(1, status_open=False)]),
        rules=[OneItemPerMeal(), RestaurantOpen()],
    )
    assert result.explanation == (
        "No breakfast, lunch or dinner can be planned on any day: of 1 menu items, "
        "1 come from restaurants that are not taking orders."
    )
