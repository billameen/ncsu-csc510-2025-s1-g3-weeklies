"""match_preferences on its own, and preferences breaking ties under the default rules."""

from menu_factory import item, menu, request

from planner.registry import get
from planner.solver import Status, plan_week

OneItemPerMeal, MatchPreferences = get("one_item_per_meal"), get("match_preferences")


def plan(items, preferences, **kw):
    return plan_week(
        request(preferences=preferences, **kw),
        menu(items),
        rules=[OneItemPerMeal(), MatchPreferences()],
    )


def test_matching_items_are_picked_by_name_or_description():
    result = plan(
        [
            item(1, name="Plain Toast"),
            item(2, name="Ramen", description="A spicy broth"),
            item(3, name="Vegan Bowl"),
        ],
        ("spicy", "vegan"),
        days=2,
    )
    assert result.status is Status.OPTIMAL
    assert {m.itm_id for m in result.meals} <= {2, 3}


def test_preferences_match_whole_words_only_and_ignore_case():
    result = plan([item(1, name="Fried Rice"), item(2, name="ICE Cream")], ("ice",))
    assert {m.itm_id for m in result.meals} == {2}


def test_no_preferences_means_no_penalty():
    result = plan([item(1)], ())
    assert result.ok


def test_preferences_break_ties_between_otherwise_equal_items():
    """Two items with the same price and calories: the default rules pick the matching one."""
    plain = item(1, name="Grilled Chicken", price_cents=1000, calories=800)
    spicy = item(2, name="Spicy Chicken", price_cents=1000, calories=800)
    for preferences, expected in ((("spicy",), 2), (("grilled",), 1)):
        result = plan_week(
            request(kcal=800, preferences=preferences, meals=(2,), days=1),
            menu([plain, spicy]),
        )
        assert [m.itm_id for m in result.meals] == [expected]
