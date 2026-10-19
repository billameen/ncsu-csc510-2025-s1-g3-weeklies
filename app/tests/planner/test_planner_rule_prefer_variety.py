"""prefer_variety on its own, and traded off against cost."""

from menu_factory import item, menu, request

from planner.registry import get
from planner.solver import plan_week

OneItemPerMeal, PreferVariety, PreferLowCost = (
    get("one_item_per_meal"),
    get("prefer_variety"),
    get("prefer_low_cost"),
)


def test_items_are_not_repeated_while_there_are_others():
    result = plan_week(
        request(days=2),
        menu([item(i) for i in range(1, 7)]),
        rules=[OneItemPerMeal(), PreferVariety()],
    )
    assert len({m.itm_id for m in result.meals}) == 6


def test_unavoidable_repeats_are_spread_over_items_not_piled_on_one():
    result = plan_week(
        request(days=2),
        menu([item(1), item(2), item(3)]),
        rules=[OneItemPerMeal(), PreferVariety()],
    )
    # Six meals, three items: 2+2+2 costs 3 x weight; 3+2+1 would cost 4 x weight.
    counts = sorted(sum(m.itm_id == i for m in result.meals) for i in (1, 2, 3))
    assert counts == [2, 2, 2]


def test_a_best_value_item_is_not_used_for_most_of_the_week():
    # Item 1 saves $2.69 per meal delivered. With weight 100 ($1) its 2nd and 3rd uses cost
    # $1 and $2 more, so they pay off; a 4th use costs $3, more than it saves. A flat $1 per
    # repeat would put it in all 9 meals.
    items = [item(1, price_cents=750)] + [item(i, price_cents=1000) for i in range(2, 11)]
    result = plan_week(
        request(days=3),
        menu(items),
        rules=[OneItemPerMeal(), PreferVariety(weight=100), get("prefer_low_cost")()],
    )
    assert sum(m.itm_id == 1 for m in result.meals) == 3


def test_every_item_is_used_before_any_is_repeated():
    result = plan_week(
        request(days=2),
        menu([item(1), item(2), item(3)]),
        rules=[OneItemPerMeal(), PreferVariety()],
    )
    # Six meals from three items: the fewest repeats possible is 3, with all three used.
    assert {m.itm_id for m in result.meals} == {1, 2, 3}


def test_a_repeat_is_worth_it_only_if_it_saves_more_than_the_weight():
    def distinct(price_gap_cents):
        result = plan_week(
            request(days=1, meals=(1, 2)),
            menu([item(1, price_cents=1000), item(2, price_cents=1000 + price_gap_cents)]),
            rules=[OneItemPerMeal(), PreferVariety(), PreferLowCost()],
        )
        return len({m.itm_id for m in result.meals})

    # Tax makes the delivered price gap about 7% larger than the menu price gap.
    assert distinct(400) == 2  # ~$4.29 extra for variety: worth it at weight 600
    assert distinct(700) == 1  # ~$7.51 extra: repeat the cheap item instead
