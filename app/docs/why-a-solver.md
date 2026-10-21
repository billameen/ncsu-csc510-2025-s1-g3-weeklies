# Why a solver, not an LLM, picks your meals

Weeklies promises 21 meals a week that never contain your allergens, keep every day within
10% of your calorie target, and keep the whole week, tax and fees included, within your
budget. Since M1 those meals are picked by a constraint solver (OR-Tools CP-SAT) instead of
an LLM. This page explains why, with the M0 evaluation's numbers.

## The problem is the whole week, not one meal

The budget is a limit on the sum of 21 prices. The calorie target is a limit on the sum of
each day's three meals. Whether a given lunch is a good pick depends on what the other 20
meals cost and how many calories they have.

The v1 planner asked an LLM for one meal at a time. Each prompt showed 10 random items and the
budget and calorie target as text. The LLM never saw the other meals of the week, so it could
not keep a running total, and nothing checked the totals afterwards. Picking well one meal at
a time cannot guarantee a weekly limit.

The solver chooses all 21 meals together. Every rule (allergens, opening hours, stock,
calories per day, the weekly budget) is a constraint on one model, and every plan it returns
meets all of them. When no week can meet them, it proves that and says which rule is the
reason.

## Before and after (M0 evaluation, seed 510)

The same 100 simulated users, the same menu, and the same validator for every planner. B2 is
v1 as shipped. M1 is the solver. 63 of the users can be served at all; 37 cannot (for example,
their budget is below the cheapest valid week). Full results are in `eval/results/m0.md`.

| | Target | v1 LLM (B2) | Solver (M1) |
|---|---|---|---|
| Feasible users who get a valid week (H1) | at least 90% | 0% | **100%** |
| Distinct items per week, median (H2) | at least 14 | 19 | **20** |
| Time to plan a week, 95th percentile (H3) | at most 5 s | 216 s | **2.8 s** |
| Infeasible users told "no valid week" (H4) | at least 90% | 0% | **100%** |
| Infeasible users told why | 100% | 0% (generic error) | **100%** |

Users whose week broke each rule:

| Rule broken | v1 LLM (B2) | Solver (M1) |
|---|---|---|
| Contains an allergen | 13 | 0 |
| A day under the calorie band | 99 | 0 |
| A day over the calorie band | 8 | 0 |
| Over budget | 28 | 0 |

## What changed for users

- **Every week fits.** No plan the solver returns breaks a rule, because the plan is the
  solution of a model that contains every rule.
- **Allergens are safe whatever the spelling.** v1 compared allergen tags exactly, so an item
  tagged "Egg" passed a profile that listed "Eggs". Every allergen v1 let through in M0 was
  such a mismatch: "Egg" against "Eggs", or "Peanuts" against "Nuts". The solver normalizes
  both sides first (Egg = Eggs, Peanuts and Tree Nuts count as nuts, Milk as dairy).
- **Impossible requests get a reason.** v1 either returned a week that broke the rules or
  failed with a generic error. The solver says, for example, "The cheapest week that meets
  your other requirements costs $317.73 with tax and fees; your weekly budget is $100.00."
- **Planning takes seconds.** v1 made 21 or more LLM calls per week; the solver needs no
  model, no API key and no GPU.
- **The same request gets the same week.** The solver's effort is capped in work done, not
  clock time, so a plan does not depend on timing, unless the server is so overloaded that
  the 4 second limit is reached first. Then the week can differ, but it still meets every rule.

## How it works

`/generate_plan` builds a `PlanRequest` from the profile (calorie target, budget, allergens,
preferences) and calls `plan_week`. For each meal slot and menu item there is a 0/1 variable,
"pick this item for this meal". Hard rules constrain those variables; soft rules add weighted
penalties for repeats, cost, and items that match none of your preferences, and the solver
looks for the plan with the lowest total penalty. It stops at 4 seconds (or after a fixed
amount of work, usually sooner) and returns the best plan found, marked `optimal: false` if
it has not proven that no better plan exists. Every rule is a plug-in; see
[Add a planner rule in 15 minutes](./planner-rules.html).

`PLANNER=llm` switches `/generate_plan` back to v1, which the evaluation keeps as baseline B2.

## Limits

- Preferences match whole words in item names and descriptions ("spicy" matches "Spicy
  Ramen"). There is no notion of cuisine or taste beyond that.
- Each meal is priced as its own delivery order, with both fees. Sharing a delivery between
  meals is milestone M4.
- Meal times are fixed at 10:00, 14:00 and 20:00.

## Next: Project 3 ideas

Each of these is a new rule file (or a small change to `PlanRequest`), not a new planner:

- **Macro targets:** a hard rule like `daily_calories` for protein, carbohydrate and fat,
  once menu items carry those numbers.
- **Group plans:** plan several users' weeks in one model so shared meals come from one order.
- **Pantry and leftovers:** zero-cost slots filled from what is already at home, as a soft
  rule that prefers them.
- **Skip-meal days:** let a request leave out meals on some days, and scale that day's
  calorie band to the meals that remain.
