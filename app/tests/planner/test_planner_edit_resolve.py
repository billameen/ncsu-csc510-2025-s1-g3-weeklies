"""Turning parsed edits into rule plug-ins for a plan window."""

from datetime import date, timedelta

import pytest
from menu_factory import item, menu, restaurant

from planner.edits.resolve import Unresolvable, affected_scope, find_items, to_rule
from planner.edits.schema import ParsedRequest

WINDOW = [date(2026, 10, 20) + timedelta(days=i) for i in range(7)]  # Tue..Mon
MENU = menu(
    [
        item(1, name="Beef Ribs", rtr_id=1),
        item(2, name="Smoked Beef Ribs", rtr_id=1),
        item(3, name="Caesar Salad", description="with anchovy dressing", rtr_id=2),
    ],
    [restaurant(1, name="The Pit"), restaurant(2, name="Sorella's")],
)


def parse(data):
    return ParsedRequest.model_validate(data)


def edit(**fields):
    return parse({"action": "edit", "edits": [fields]}).edits[0]


def test_days_map_to_the_dates_in_the_plan_window():
    rule = to_rule(
        edit(type="filter", field="tag", op="is", value="vegan", days="thu"), WINDOW, MENU
    )
    assert rule.scope.days == {date(2026, 10, 22)} and rule.scope.meals is None


def test_dish_words_match_exactly_first_then_whole_words_in_name_or_description():
    assert [i.itm_id for i in find_items(MENU, "beef ribs")] == [1]
    assert [i.itm_id for i in find_items(MENU, "ribs")] == [1, 2]
    assert [i.itm_id for i in find_items(MENU, "rib")] == [1, 2]  # singular or plural
    assert [i.itm_id for i in find_items(MENU, "salads")] == [3]
    assert [i.itm_id for i in find_items(MENU, "anchovy")] == [3]  # from the description
    assert find_items(MENU, "beef rib eye") == []


def test_unknown_dishes_and_restaurants_become_questions():
    for unknown in (
        edit(type="filter", field="dish", op="is_not", value="Lasagna"),
        edit(type="include", field="restaurant", op="is", value="Nowhere Diner"),
        edit(type="prefer", goal="match", field="dish", op="is", value="sushi"),
    ):
        with pytest.raises(Unresolvable, match="Which"):
            to_rule(unknown, WINDOW, MENU)


def test_each_edit_type_becomes_its_rule():
    edits = parse(
        {
            "action": "edit",
            "edits": [
                {"type": "filter", "field": "tag", "op": "is", "value": "spicy", "meals": "dinner"},
                {"type": "filter", "field": "price", "op": "<=", "value": 12.5},
                {"type": "include", "field": "dish", "op": "is", "value": "ribs", "times": 2},
                {"type": "day_limit", "metric": "cost", "op": "<=", "value": 40, "days": "thu"},
                {"type": "calorie_shift", "kcal_delta": -300, "days": "weekend"},
            ],
        }
    ).edits
    rules = [to_rule(e, WINDOW, MENU) for e in edits]
    assert [r.name for r in rules] == [
        "filter_meals",
        "filter_meals",
        "include_meals",
        "day_limit",
        "calorie_shift",
    ]
    assert rules[1].condition.value == 1250  # cents
    assert rules[2].condition.ids == {1, 2} and rules[2].times == 2
    assert (rules[3].value, rules[3].days) == (4000, {date(2026, 10, 22)})
    assert rules[4].days == {date(2026, 10, 24), date(2026, 10, 25)}


def test_restaurant_names_and_preferences_resolve():
    pit = to_rule(
        edit(type="filter", field="restaurant", op="is_not", value="the pit"), WINDOW, MENU
    )
    assert pit.condition.ids == {1}
    match = to_rule(
        edit(type="prefer", goal="match", field="restaurant", op="is", value="Sorella's"),
        WINDOW,
        MENU,
    )
    assert (match.name, match.goal, match.condition.ids) == ("prefer_meals", "match", {2})
    cheaper = to_rule(edit(type="prefer", goal="cheaper", meals="lunch"), WINDOW, MENU)
    assert (cheaper.goal, cheaper.condition, cheaper.scope.meals) == ("cheaper", None, {2})


def test_shifts_and_daily_limits_replan_whole_days():
    for whole_day in (
        edit(type="calorie_shift", kcal_delta=-300, days="weekend"),
        edit(type="day_limit", metric="calories", op="<=", value=2000, days="sat"),
    ):
        assert affected_scope(whole_day, WINDOW).meals is None
    dinner = edit(type="filter", field="tag", op="is", value="vegan", meals="dinner")
    assert affected_scope(dinner, WINDOW).meals == {3}
