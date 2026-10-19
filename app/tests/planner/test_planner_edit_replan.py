"""Re-planning only the edited meals, with everything else pinned."""

from datetime import date

from menu_factory import MONDAY, item, menu, request

from planner.registry import get
from planner.tags import has_tag
from planner.edits.replan import CLOSEST, IMPOSSIBLE, PREVIEW, preview_edits
from planner.scope import MealScope

TUESDAY = date(2026, 10, 20)
RequireTag = get("require_tag")

MENU = menu(
    [
        item(1, name="Steak Frites", price_cents=900, calories=600),
        item(2, name="Pork Chop", price_cents=950, calories=600),
        item(3, name="Mushroom Risotto", price_cents=1100, calories=600),
        item(4, name="Garden Salad", price_cents=700, calories=300),
        item(5, name="Chicken Wings", price_cents=800, calories=600),
        item(6, name="Bean Chili", price_cents=1000, calories=600),
        item(7, name="Vegetable Lasagna", price_cents=1200, calories=1100),
    ]
)
# A two-day plan: Monday and Tuesday, three 600 kcal meals each (1,800 kcal target).
CURRENT = {
    (MONDAY, 1): 1,
    (MONDAY, 2): 2,
    (MONDAY, 3): 5,
    (TUESDAY, 1): 1,
    (TUESDAY, 2): 2,
    (TUESDAY, 3): 5,
}


def edit(rule_cls, *args, scope):
    return [rule_cls(*args, scope)], [scope]


def test_only_the_edited_day_changes_and_it_meets_the_edit():
    rules, affected = edit(RequireTag, "vegetarian", scope=MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)

    assert preview.status == PREVIEW
    assert {c.slot.day for c in preview.changes} == {TUESDAY}
    assert all(has_tag(c.after, "vegetarian") for c in preview.changes)
    assert len(preview.changes) == 3
    assert preview.met == preview.edited == 3
    assert preview.replaced_unavailable == ()


def test_pinned_meals_are_saved_unchanged_in_the_new_entries():
    # Only Tuesday's dinner (Chicken Wings) is edited; it has to become vegetarian.
    rules, affected = edit(RequireTag, "vegetarian", scope=MealScope(days={TUESDAY}, meals={3}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)
    assert preview.status == PREVIEW
    assert [(c.slot.day, c.slot.meal) for c in preview.changes] == [(TUESDAY, 3)]
    assert "[2026-10-19,1,1]" in preview.entries and "[2026-10-20,2,2]" in preview.entries
    assert len(preview.entries) == 6


def test_costs_and_calories_before_and_after_are_reported():
    rules, affected = edit(RequireTag, "vegetarian", scope=MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)
    assert preview.kcal_before == {MONDAY: 1800, TUESDAY: 1800}
    assert preview.kcal_after[MONDAY] == 1800
    assert preview.cost_before_cents == sum(MENU.items[i].cost_cents for i in CURRENT.values())
    after_ids = [int(e.strip("[]").split(",")[1]) for e in preview.entries]
    assert preview.cost_after_cents == sum(MENU.items[i].cost_cents for i in after_ids)


def test_an_edit_that_cannot_be_met_returns_the_closest_option():
    # Only the 300 kcal salad is low-calorie, and three of it (900 kcal) cannot reach the
    # 1,620 kcal floor. Closest: two salads and the 1,100 kcal lasagna (1,700 kcal).
    rules, affected = edit(RequireTag, "low-calorie", scope=MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)

    assert preview.status == CLOSEST
    assert "kcal" in preview.explanation
    assert (preview.met, preview.edited) == (2, 3)
    assert {c.slot.day for c in preview.changes} == {TUESDAY}


def test_when_not_even_a_close_plan_exists_the_edit_is_impossible():
    # The pinned Monday meals alone already exceed a $30 budget.
    rules, affected = edit(RequireTag, "vegetarian", scope=MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2, budget_cents=3000), MENU, CURRENT, rules, affected)
    assert preview.status == IMPOSSIBLE
    assert preview.changes == () and preview.entries == ()
    assert "budget" in preview.explanation


def test_a_pinned_item_that_is_gone_is_replaced_and_reported():
    gone = menu([*MENU.items.values()][:4] + [item(5, in_stock=False), item(6, price_cents=1000)])
    rules, affected = edit(RequireTag, "vegetarian", scope=MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), gone, CURRENT, rules, affected)
    assert preview.status == PREVIEW
    assert [(s.day, s.meal) for s in preview.replaced_unavailable] == [(MONDAY, 3)]


def test_a_one_day_edit_is_fast():
    rules, affected = edit(RequireTag, "vegetarian", scope=MealScope(days={TUESDAY}))
    assert preview_edits(request(days=2), MENU, CURRENT, rules, affected).seconds < 2


def test_meals_that_already_meet_the_edit_are_kept():
    # Tuesday lunch is already vegetarian (Bean Chili); only breakfast and dinner should change.
    current = {**CURRENT, (TUESDAY, 2): 6}
    rules, affected = edit(RequireTag, "vegetarian", scope=MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, current, rules, affected)
    assert [c.slot.meal for c in preview.changes] == [1, 3]


def test_the_closest_option_keeps_the_meal_it_cannot_fix():
    # Breakfast is the 1,100 kcal lasagna. Low-calorie means the 300 kcal salad, and only
    # salad + salad + lasagna (1,700 kcal) fits the band, so breakfast stays as it is and
    # lunch and dinner become salads.
    current = {**CURRENT, (TUESDAY, 1): 7}
    rules, affected = edit(RequireTag, "low-calorie", scope=MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, current, rules, affected)
    assert preview.status == CLOSEST and (preview.met, preview.edited) == (2, 3)
    assert [(c.slot.meal, c.after.itm_id) for c in preview.changes] == [(2, 4), (3, 4)]
