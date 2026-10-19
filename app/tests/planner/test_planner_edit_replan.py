"""Re-planning only the edited meals, with everything else pinned."""

from datetime import date

from menu_factory import MONDAY, item, menu, request

from planner.registry import get
from planner.tags import has_tag
from planner.edits.replan import CLOSEST, IMPOSSIBLE, PREVIEW, check_proposal, preview_edits
from planner.match import Condition
from planner.scope import MealScope

TUESDAY = date(2026, 10, 20)
FilterMeals = get("filter_meals")

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


def tag_edit(tag, scope):
    """A "make these meals <tag>" edit: its rules and the meals it re-plans."""
    return [FilterMeals(Condition("tag", "is", tag), scope)], [scope]


def test_only_the_edited_day_changes_and_it_meets_the_edit():
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)

    assert preview.status == PREVIEW
    assert {c.slot.day for c in preview.changes} == {TUESDAY}
    assert all(has_tag(c.after, "vegetarian") for c in preview.changes)
    assert len(preview.changes) == 3
    assert preview.unmet == ()
    assert preview.replaced_unavailable == ()


def test_pinned_meals_are_saved_unchanged_in_the_new_entries():
    # Only Tuesday's dinner (Chicken Wings) is edited; it has to become vegetarian.
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}, meals={3}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)
    assert preview.status == PREVIEW
    assert [(c.slot.day, c.slot.meal) for c in preview.changes] == [(TUESDAY, 3)]
    assert "[2026-10-19,1,1]" in preview.entries and "[2026-10-20,2,2]" in preview.entries
    assert len(preview.entries) == 6


def test_costs_and_calories_before_and_after_are_reported():
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)
    assert preview.kcal_before == {MONDAY: 1800, TUESDAY: 1800}
    assert preview.kcal_after[MONDAY] == 1800
    assert preview.cost_before_cents == sum(MENU.items[i].cost_cents for i in CURRENT.values())
    after_ids = [int(e.strip("[]").split(",")[1]) for e in preview.entries]
    assert preview.cost_after_cents == sum(MENU.items[i].cost_cents for i in after_ids)


def test_an_edit_that_cannot_be_met_returns_the_closest_option():
    # Only the 300 kcal salad is low-calorie, and three of it (900 kcal) cannot reach the
    # 1,620 kcal floor. Closest: two salads and the 1,100 kcal lasagna (1,700 kcal).
    rules, affected = tag_edit("low-calorie", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, CURRENT, rules, affected)

    assert preview.status == CLOSEST
    assert "kcal" in preview.explanation
    assert preview.unmet == ("1 of 3 meals (Tue Oct 20) are not low-calorie",)
    assert {c.slot.day for c in preview.changes} == {TUESDAY}


def test_when_not_even_a_close_plan_exists_the_edit_is_impossible():
    # The pinned Monday meals alone already exceed a $30 budget.
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2, budget_cents=3000), MENU, CURRENT, rules, affected)
    assert preview.status == IMPOSSIBLE
    assert preview.changes == () and preview.entries == ()
    assert "budget" in preview.explanation


def test_a_pinned_item_that_is_gone_is_replaced_and_reported():
    gone = menu([*MENU.items.values()][:4] + [item(5, in_stock=False), item(6, price_cents=1000)])
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), gone, CURRENT, rules, affected)
    assert preview.status == PREVIEW
    assert [(s.day, s.meal) for s in preview.replaced_unavailable] == [(MONDAY, 3)]


def test_a_one_day_edit_is_fast():
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}))
    assert preview_edits(request(days=2), MENU, CURRENT, rules, affected).seconds < 2


def test_meals_that_already_meet_the_edit_are_kept():
    # Tuesday lunch is already vegetarian (Bean Chili); only breakfast and dinner should change.
    current = {**CURRENT, (TUESDAY, 2): 6}
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, current, rules, affected)
    assert [c.slot.meal for c in preview.changes] == [1, 3]


def test_the_closest_option_keeps_the_meal_it_cannot_fix():
    # Breakfast is the 1,100 kcal lasagna. Low-calorie means the 300 kcal salad, and only
    # salad + salad + lasagna (1,700 kcal) fits the band, so breakfast stays as it is and
    # lunch and dinner become salads.
    current = {**CURRENT, (TUESDAY, 1): 7}
    rules, affected = tag_edit("low-calorie", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, current, rules, affected)
    assert preview.status == CLOSEST
    assert preview.unmet == ("1 of 3 meals (Tue Oct 20) are not low-calorie",)
    assert [(c.slot.meal, c.after.itm_id) for c in preview.changes] == [(2, 4), (3, 4)]


def vegetarian_tuesday():
    rules, affected = tag_edit("vegetarian", MealScope(days={TUESDAY}))
    return preview_edits(request(days=2), MENU, CURRENT, rules, affected), rules


def test_a_fresh_proposal_passes_the_check_before_saving():
    preview, rules = vegetarian_tuesday()
    assert check_proposal(request(days=2), MENU, preview.entries, rules) is None


def test_a_proposal_is_rejected_if_an_item_went_out_of_stock_since():
    preview, rules = vegetarian_tuesday()
    chosen = preview.changes[0].after
    gone = menu([i for i in MENU.items.values() if i.itm_id != chosen.itm_id])
    assert check_proposal(request(days=2), gone, preview.entries, rules) == (
        "A proposed meal is no longer available."
    )
    sold_out = menu(
        [
            item(i.itm_id, i.price_cents, i.calories, name=i.name, in_stock=i != chosen)
            for i in MENU.items.values()
        ]
    )
    assert check_proposal(request(days=2), sold_out, preview.entries, rules) == (
        f"{chosen.name} is no longer available."
    )


def test_a_proposal_is_rejected_if_the_profile_got_stricter_since():
    preview, rules = vegetarian_tuesday()
    cost = preview.cost_after_cents
    assert check_proposal(request(days=2, budget_cents=cost - 1), MENU, preview.entries, rules)
    allergic = menu(
        [
            item(
                i.itm_id, i.price_cents, i.calories, ("Soy",) if i.itm_id == 1 else (), name=i.name
            )
            for i in MENU.items.values()
        ]
    )
    assert check_proposal(
        request(days=2, allergens=("Soy",)), allergic, preview.entries, rules
    ), "Monday's pinned breakfast (item 1) now has an allergen"


def test_a_calorie_shift_proposal_is_checked_against_the_shifted_target():
    shift = get("calorie_shift")(600, days={TUESDAY})
    preview = preview_edits(request(days=2), MENU, CURRENT, [shift], [MealScope(days={TUESDAY})])
    assert preview.status == PREVIEW
    assert check_proposal(request(days=2), MENU, preview.entries, [shift]) is None
    assert check_proposal(request(days=2), MENU, preview.entries) is not None


def test_a_day_limit_that_cannot_be_met_gets_the_closest_option_too():
    limit = get("day_limit")("cost", "<=", 400, days={TUESDAY})
    preview = preview_edits(request(days=2), MENU, CURRENT, [limit], [MealScope(days={TUESDAY})])
    assert preview.status == CLOSEST
    assert "you asked for at most $4.00 a day" in preview.explanation
    # The cheapest Tuesday that still meets the calorie target, and the miss said in words.
    tuesday = [e for e in preview.entries if e.startswith("[2026-10-20,")]
    tuesday_cost = sum(MENU.items[int(e.split(",")[1])].cost_cents for e in tuesday)
    assert preview.unmet == (
        f"Tue Oct 20 costs ${tuesday_cost / 100:,.2f} (you asked for at most $4.00 a day)",
    )


def test_an_include_that_cannot_be_met_gets_the_closest_option():
    lasagna = Condition("dish", "is", "Vegetable Lasagna", ids={7})
    include = get("include_meals")(lasagna, MealScope(days={TUESDAY}), times=2)
    preview = preview_edits(request(days=2), MENU, CURRENT, [include], [MealScope(days={TUESDAY})])
    assert preview.status == CLOSEST
    assert sum(c.after.itm_id == 7 for c in preview.changes) == 1
    assert preview.unmet == (
        'Only 1 of the 2 meals you asked for (Tue Oct 20) are "Vegetable Lasagna"',
    )


def test_a_preference_never_makes_an_edit_impossible():
    cheaper = get("prefer_meals")("cheaper", MealScope(days={TUESDAY}))
    preview = preview_edits(request(days=2), MENU, CURRENT, [cheaper], [MealScope(days={TUESDAY})])
    assert preview.status == PREVIEW and preview.unmet == ()
    assert all(c.after.cost_cents < c.before.cost_cents for c in preview.changes)
