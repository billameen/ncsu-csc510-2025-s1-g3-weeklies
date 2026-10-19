# Add a planner rule in 15 minutes

The weekly planner is a list of rules handed to a constraint solver. Every rule lives in its
own file in `app/planner/rules/`, and adding one never means touching the solver. A new rule
is **one file, one test file and one row** in the rule reference at the bottom of this
page.

This guide builds a real rule, `max_meals_per_restaurant` ("order from any one restaurant at
most N times a week"), which ships in `app/planner/rules/max_meals_per_restaurant.py`. Open
that file next to this page.

## 1. How a rule works (2 minutes)

For every meal slot (day and meal) and every menu item, the model has one 0/1 variable:
"pick this item for this slot". A rule adds to that model and never builds its own.

A rule is a class with two methods:

- `apply(ctx)` adds the rule to the model in `ctx` (a `PlanContext`).
- `explain(ctx)` is called only when no week can be planned. It returns the sentence shown to
  the user if this rule is the reason, or `None` if it is not.

There are three kinds:

| Kind | Subclass | You write | Use it for |
|---|---|---|---|
| Item filter (hard) | `ItemFilter` | `allows(item, slot, ctx)` and `blocked_reason` | "This item can never be picked for this meal": allergens, stock, opening hours |
| Hard rule | `Constraint` | `apply` and `explain` | Limits across meals: daily calories, weekly budget, meals per restaurant |
| Soft rule | `SoftConstraint` | `apply` with `ctx.add_penalty` | Preferences the solver trades off: variety, lower cost |

Hard rules must hold in every plan. Soft rules add a weighted penalty, and the solver picks
the plan with the lowest total. Weights are in cents: `prefer_low_cost` charges 1 per cent
spent, so a soft rule with weight 600 is worth $6 per unit of penalty.

## 2. Write the file (5 minutes)

Create `app/planner/rules/max_meals_per_restaurant.py`:

```python
from planner.constraint import Constraint
from planner.registry import register


@register
class MaxMealsPerRestaurant(Constraint):
    """At most `limit` meals of the plan come from the same restaurant."""

    name = "max_meals_per_restaurant"   # unique snake_case id, also its key in options
    summary = "No restaurant supplies more than a set number of meals."
    order = 70                          # filters 10-19, structure 20, limits 50-99, soft 200+
    enabled_by_default = False          # opt-in: requests turn it on in their options

    def __init__(self, limit: int = 3):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError(f"{self.name}: limit must be a whole number >= 1, got {limit!r}")
        self.limit = limit

    def apply(self, ctx):
        picks_by_restaurant = {}
        for slot in ctx.slots:
            for item, var in ctx.picks(slot):   # only items no filter has ruled out
                picks_by_restaurant.setdefault(item.rtr_id, []).append(var)
        for picks in picks_by_restaurant.values():
            ctx.model.Add(sum(picks) <= self.limit)
```

That is a working rule. `@register` adds it to the registry, and the registry imports every
module in `planner/rules/` on first use, so nothing else needs to list it.

`@register` also checks the class and refuses a broken one with a `PluginError` that says
what is wrong (see "What the registry rejects", below).

## 3. Explain it (3 minutes)

When a week is impossible, the solver asks every hard rule for its `explain(ctx)`. Only blame
your rule when you can prove it is the cause. Here, the rule is the cause if the plan works
once the rule is lifted, and `cheapest_without` answers exactly that:

```python
    def explain(self, ctx):
        from planner.solver import cheapest_without

        if cheapest_without(ctx, self) is None:   # still impossible without this rule
            return None                           # so another rule explains it
        # Claim only what was proven: a week exists without the limit, none with it.
        return (
            f"No week meets your other requirements with at most {self.limit} meals from any "
            f"one restaurant; allowing more meals per restaurant would make one possible."
        )
```

Write the sentence for the user: what is impossible, the numbers behind it, and what they
could change. Say no more than you proved: lifting this rule fixes the week, but that does not
mean there are too few restaurants (the cheap one may be capped while the budget is tight). `cheapest_without(ctx, rule)` re-solves without `rule` and returns the lowest
cost, or `None` if the other rules are impossible on their own. `weekly_budget` uses the same
helper to say "The cheapest week that meets your other requirements costs $212.40".

Item filters do not write `explain`. When a meal has no item left, `one_item_per_meal`
counts how many items each filter blocked and uses each filter's `blocked_reason` ("are out of
stock"), or `describe_block(slot, ctx)` if the filter overrides it.

## 4. Test it alone (4 minutes)

Create `app/tests/planner/test_planner_rule_max_meals_per_restaurant.py`. Test the rule with
`one_item_per_meal` and nothing else, on a hand-built menu, so a failure points at your rule:

```python
from menu_factory import item, menu, request

from planner.registry import get
from planner.solver import Status, plan_week

OneItemPerMeal = get("one_item_per_meal")
MaxMealsPerRestaurant = get("max_meals_per_restaurant")

SIX = menu([item(i, rtr_id=(i + 1) // 2) for i in range(1, 7)])  # 3 restaurants, 2 items each


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
    assert "allowing more meals per restaurant" in result.explanation
```

`menu_factory` (in `app/tests/planner/`) builds items, restaurants and requests with sensible
defaults. Cover at least: the rule holds when the week is possible, the explanation when it
is not, and that the explanation stays quiet when another rule is the cause.

## 5. Document it (1 minute)

Add a row to the rule reference at the bottom of this page.

## 6. Check it (1 minute)

```bash
pytest app/tests/planner -q        # the planner's tests, about 20 s
python -m eval.run --seed 510      # only if the rule is on by default: re-run M0
```

If the rule is on by default, it changes what every user gets, so re-run the M0 evaluation
and commit `eval/results/` with your change (see [How We Evaluate](./evaluation.html)). H1
must not drop, and H3 (p95 planning time) must stay at or below 5 s.

## Turning a rule on or off

A request's `options` configure rules by name:

```python
PlanRequest(..., options={
    "max_meals_per_restaurant": 3,          # one value: passed to __init__
    "prefer_variety": {"weight": 900},      # a dict: passed as keyword arguments
    "match_preferences": False,             # False: off for this request
})
```

`True` turns on an opt-in rule with its defaults. An unknown name raises `KeyError`, so a
typo never silently does nothing.

## What PlanContext gives you

| Helper | Returns |
|---|---|
| `ctx.request`, `ctx.menu`, `ctx.slots` | The request, the menu, every slot (day and meal) in order |
| `ctx.picks(slot)` | `(item, variable)` for every item still allowed for the slot |
| `ctx.candidates(slot)` | The items still allowed for the slot |
| `ctx.pick(slot, item)` | One 0/1 variable |
| `ctx.slots_by_day()` | `{date: (slots...)}` |
| `ctx.calories(slots)`, `ctx.cost_cents(slots=None)` | Linear expressions over the picks |
| `ctx.forbid(slot, item, rule)` | Never pick that item for that slot |
| `ctx.add_penalty(rule, expr)` | Soft rules only: add `rule.weight * expr` to the objective |
| `ctx.model` | The CP-SAT model, for anything else (`ctx.model.Add(...)`) |

Each `Slot` has `day`, `weekday` ("Mon"), `meal` (1, 2 or 3), `meal_name`, `time` (HHMM)
and `label` ("Mon Oct 19 breakfast"). Each `MenuItem` has `itm_id`, `rtr_id`, `name`,
`description`, `price_cents`, `cost_cents` (with tax and fees), `calories`, `allergens` and
`in_stock`.

## What the registry rejects

`@register` raises `PluginError` when the rule file loads if the class:

- is not a subclass of `Constraint`;
- has no `name`, or one that is not snake_case, or one another rule already uses;
- leaves an abstract method unimplemented (`apply`, or `allows` for an `ItemFilter`);
- has a `kind` that is not `Kind.HARD` or `Kind.SOFT`, or is soft without subclassing
  `SoftConstraint`;
- has no `summary`, or is an `ItemFilter` without a `blocked_reason`;
- has a non-integer `order`.

A rule file that raises while importing is reported the same way, naming the file.

## Rule reference

| Rule | Kind | Default | What it does | When the week is impossible it says |
|---|---|---|---|---|
| `in_stock` | filter | on | Only in-stock items | "2 are out of stock" |
| `restaurant_open` | filter | on | Restaurant open at the meal's time (10:00, 14:00, 20:00) | "come from restaurants closed at 10:00" |
| `no_allergens` | filter | on | No item with the user's allergens; spellings normalized (Egg = Eggs) | "contain your allergens (eggs)" |
| `one_item_per_meal` | hard | on | Exactly one item per meal | "No breakfast can be planned on any day: of 269 menu items, ..." |
| `daily_calories` | hard | on | Each day within 10% of the calorie target | "needs each day to total 2,250-2,750 kcal ... The closest is 2,100 kcal on Sat Oct 24" |
| `weekly_budget` | hard | on | Whole week, tax and fees included, within budget | "The cheapest week ... costs $212.40 with tax and fees; your weekly budget is $150.00." |
| `max_meals_per_restaurant` | hard | off | At most N meals from one restaurant (tutorial example) | "No week meets your other requirements with at most 2 meals from any one restaurant ..." |
| `match_preferences` | soft (400) | on | Prefer items whose name or description matches a preference word | |
| `prefer_low_cost` | soft (1) | on | Prefer cheaper weeks; 1 per cent | |
| `prefer_variety` | soft (600) | on | Prefer fewer repeats; the 1st, 2nd and later repeats of an item cost 1x, 2x and 3x the weight | |
