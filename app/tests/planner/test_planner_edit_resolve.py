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
        item(3, name="Caesar Salad", rtr_id=2),
    ],
    [restaurant(1, name="The Pit"), restaurant(2, name="Sorella's")],
)


def parse(data):
    return ParsedRequest.model_validate(data)


def test_days_map_to_the_dates_in_the_plan_window():
    edit = parse(
        {"action": "edit", "edits": [{"type": "require_tag", "tag": "vegan", "days": "thu"}]}
    ).edits[0]
    rule = to_rule(edit, WINDOW, MENU)
    assert rule.scope.days == {date(2026, 10, 22)} and rule.scope.meals is None


def test_dish_names_match_exactly_first_then_by_whole_words():
    assert [i.itm_id for i in find_items(MENU, "beef ribs")] == [1]
    assert [i.itm_id for i in find_items(MENU, "ribs")] == [1, 2]
    assert find_items(MENU, "rib") == []


def test_unknown_dishes_and_restaurants_become_questions():
    for edit in (
        {"type": "exclude_item", "item": "Lasagna"},
        {"type": "exclude_restaurant", "restaurant": "Nowhere Diner"},
    ):
        parsed = parse({"action": "edit", "edits": [edit]})
        with pytest.raises(Unresolvable, match="Which"):
            to_rule(parsed.edits[0], WINDOW, MENU)


def test_each_edit_type_becomes_its_rule():
    edits = parse(
        {
            "action": "edit",
            "edits": [
                {"type": "require_tag", "tag": "spicy", "meals": "dinner"},
                {"type": "max_price", "max_price": 12.5},
                {"type": "exclude_item", "item": "Caesar Salad"},
                {"type": "exclude_restaurant", "restaurant": "the pit"},
                {"type": "calorie_shift", "kcal_delta": -300, "days": "weekend"},
            ],
        }
    ).edits
    rules = [to_rule(e, WINDOW, MENU) for e in edits]
    assert [r.name for r in rules] == [
        "require_tag",
        "max_price",
        "exclude_item",
        "exclude_restaurant",
        "calorie_shift",
    ]
    assert rules[1].max_price_cents == 1250
    assert rules[2].itm_ids == {3} and rules[3].rtr_ids == {1}
    assert rules[4].days == {date(2026, 10, 24), date(2026, 10, 25)}
    assert affected_scope(edits[4], WINDOW).meals is None
