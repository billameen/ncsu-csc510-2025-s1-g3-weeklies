# How We Evaluate the Meal Planner

Weeklies promises 21 meals a week that stay within budget, hit a calorie target and never
include an allergen. The evaluation checks that promise against 100 simulated users and
reports whether each planner keeps it. The hypotheses and their thresholds come from
[issue #5](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/issues/5) and were
fixed before the first run.

The current numbers are in `eval/results/m0.md` (and `m0.json`). This page explains how they
are produced and how to read them.

## Run it

From the repository root, with the virtual environment active:

```bash
python app/scripts/init_db.py      # once: builds app/CSC510_DB.db from app/db/seed.sql
python -m eval.run --seed 510      # about 3 minutes; no API key and no model needed
```

This writes `eval/results/m0.json` and `eval/results/m0.md` and prints the table. Use
`--out DIR` to write somewhere else, and `--baseline PATH` to compare against another
`m0.json` (see Regression check, below).

The exit code is 0 even when hypotheses fail. It is 1 only for a regression against
`--baseline`, and any other non-zero code means the eval crashed.

## What we measure

| | Metric | Pass if | Compared with |
|---|---|---|---|
| H1 | Share of **feasible** users who get a valid week | ≥ 90% | B1, B2 |
| H2 | Distinct items per week, median | ≥ 14 | B1 |
| H3 | Time to plan one week, 95th percentile | ≤ 5 s | B2 |
| H4 | Share of **infeasible** users who get an explicit "no valid week" answer | ≥ 90% | B1, B2 |

The table also shows the share of **all** users who get a valid week. It has no threshold;
it is the headline number for the product. Since M1 it also shows the share of **infeasible**
users who are told why there is no valid week (`explained_pct`); M1's target is 100%, and it
is not one of the fixed hypotheses.

- **Feasible** means a valid week exists for the user at all (see Feasible users, below). A planner is not blamed for users nobody could serve,
  but it must say so instead of returning an invalid week: that is H4.
- **H1:** a "no valid week" answer to a feasible user counts as a miss.
- **H2** counts the distinct items in each week planned for a feasible user, valid or not,
  and takes the median. "No valid week" answers and empty weeks are left out.
- **H3** is the 95th percentile by nearest rank: sort every user's planning time and take
  the value at position ceil(0.95 × n), so it is always a time that was actually measured.
  For B2 it is the recorded LLM time (see Planners, below).
- **Told why** counts an infeasible user when the planner answered "no valid week" with a
  non-empty reason (`eval.planners.NoValidWeek`). A bare `None` or an invalid week is a miss.
- A metric is `n/a` (`null` in the JSON) when no user falls in its group.

## What counts as a valid week

A week is valid when it has no violations. The rules live in `eval/validate.py`, which is
the specification: it does not import any planner code, and a test enforces that.

| Rule | Details | Violation |
|---|---|---|
| 21 meals | One meal per slot: Monday to Sunday of the week starting Monday 2026-10-19, at breakfast (10:00), lunch (14:00) and dinner (20:00) | `missing_meal`, `extra_meal` |
| Real items | Every item is in stock and from a restaurant whose status is `Open` | `unknown_item` |
| No allergens | No item tag matches the user's allergens | `allergen` |
| Open restaurant | The restaurant is open at the meal time | `closed_restaurant` |
| Calories | Each day's total is within 10% of the user's daily target | `under_kcal`, `over_kcal` |
| Budget | The week's total cost is at most the user's weekly budget | `over_budget` |

How the rules are applied:

- **Cost:** each meal is its own delivery order: item price, plus 7.25% tax rounded half up to
  the cent, plus the $3.99 delivery fee and $1.49 service fee, with no tip. The constants come
  from `app/pricing.py`, the same ones checkout uses, and the cost matches checkout to the cent.
- **Calories:** the allowed range is whole calories from 0.9 × target rounded up to
  1.1 × target rounded down, both ends included. A 2,100 kcal target allows 1,890 to 2,310.
- **Allergens:** tags are compared after lowercasing and trimming spaces, and the menu's
  alternate spellings are merged: `Egg` counts as `Eggs` and `Peanuts` as `Nuts`. Only whole
  tags match, so a `Shellfish` item is fine for a user who avoids `Fish`.
- **Opening hours:** the meal time must fall inside one of the day's open/close pairs, with
  both ends counted as open. A restaurant with no hours for that day, unreadable hours or an
  odd number of times is treated as closed.
- **Partial weeks:** an extra meal (a second meal in a slot, or a day or meal outside the
  week) and a meal with an unknown item are reported once and then ignored by the other
  checks. Only problems the remaining meals prove are reported, so a day that is missing a
  meal can be over its calorie target but never under it.

The JSON and the table count **users** with each kind of violation, not individual
violations.

## Feasible users

`eval/feasibility.py` finds each user's cheapest week that meets every rule except the
budget, and the user is feasible if the validator accepts that week, budget included. The
search is exact: days are independent, so it finds the cheapest valid day seven times, and
it is checked against brute force in the tests. It takes under a second for all 100 users.

If a planner ever finds a valid week for a user marked infeasible, the run stops with an
error, because that means the feasibility check or the validator is wrong.

## Simulated users

`eval/profiles.py` generates 100 users from a seed (510 by default), using its own random
generator so results do not depend on anything else that uses `random`.

| Group | Users | Calories per day | Budget per week | Allergens |
|---|---|---|---|---|
| Regular, no allergens | 40 | 1,600 to 3,000 | $300 to $650 | none |
| Regular, with allergens | 40 | 1,600 to 3,000 | $300 to $650 | 1 to 3 |
| Hard | 20 | 2,400 to 3,000 | $350 to $450 | 2 or 3 |

Calories are in steps of 50. Allergens are drawn from Gluten, Dairy, Eggs, Soy, Nuts, Fish
and Shellfish. The groups are shuffled together, so user ids do not reveal the group.

The users for seed 510 are committed in `eval/data/profiles_seed510.json`, and a test
checks they still match. After an intended change to the generator, regenerate it with
`python -m eval.profiles --seed 510 > eval/data/profiles_seed510.json`.

## Planners

Every planner is a function `(profile, catalog, seed)` that returns the planned meals, or
`None` (or `NoValidWeek(reason)`) to answer "no valid week". The baselines live in
`eval/baselines.py` and the planner under test in `eval/planners.py`.

- **B1, random-safe:** for each slot, a random in-stock, allergen-free item from a restaurant
  that is open then. It knows nothing about budget or calories, so its misses show what
  ignoring them costs.
- **B2, v1 LLM planner:** the app's `MenuGenerator` as shipped, run for the whole week, with
  the user's budget and calorie target passed in as preference text. It never says "no valid
  week". If v1 gives up on a meal, the whole week is lost and comes back empty.
- **M1, CP-SAT solver:** `plan_week` from `app/planner` with its default rules, the same call
  `/generate_plan` makes (`eval/planners.py`). It plans all 21 meals at once and, when no week
  fits, answers `NoValidWeek` with the explanation the user sees. It is deterministic, so
  `seed` is unused. Its H3 is real solver time on the machine running the eval, about 3 s at
  p95. See [Why a solver](./why-a-solver.html).

### How B2 runs without a model

B2 calls an LLM 21 times per user or more, so it was run once for real and every response
was recorded in `eval/fixtures/b2_v1_cassette.json`. A normal run replays those responses
instead of calling the LLM. This makes the eval free, fast and identical on every machine.

- **What was recorded:** the app's own LLM choice, which without an OpenAI key is the local
  model `ibm-granite/granite-4.0-h-350M` with the 500-token limit `/generate_plan` uses. It
  was recorded on a Mac (Apple GPU), at about 9 s per call. The model name is stored in
  the recording.
- **What is stored:** for each prompt, a SHA-256 hash (never the prompt text), the response
  and how long it took. A prompt asked more than once keeps its responses in order.
- **Reproducibility:** v1 picks 10 random items per meal using Python's global `random`, so B2
  seeds it per user before running v1 and restores it afterwards. The same seed gives the same
  prompts, so every prompt finds its recorded response.
- **Timing:** replaying is almost instant, so B2's H3 adds each response's recorded time back.
  H3 for B2 therefore reflects the machine the recording was made on.

The recording only matches the current menu data and v1's current prompts. If
`app/db/seed.sql`, v1's prompt text, or `V1_PREFERENCES` in `eval/baselines.py` changes,
a replay stops with "The B2 recording has no response for this prompt" instead of guessing.
Record it again with:

```bash
caffeinate -i python -m eval.run --seed 510 --record
```

(`caffeinate -i` keeps a Mac awake; leave it out elsewhere.) With the local model this takes
about 5.5 hours, and the machine should be left alone so the recorded times are fair.
Recording saves after every call: if it stops for any reason, run the same command again and
it continues where it left off. To start over, delete the recording first. It refuses to mix
models, both when resuming and if the LLM switches model partway through, which the app's
`llm_toolkit` does silently after an OpenAI error.

## Outputs

`m0.json` holds `schema_version` (2 since M1 added `explained_pct`), `seed`, the user counts
(total, feasible, hard and hard feasible), the thresholds, and for each planner H1 to H4
(`h1_valid_pct`, `h2_median_distinct`, `h3_p95_s`, `h4_no_plan_pct`), the headline
`overall_valid_pct`, `explained_pct` and `users_with_violation`. Percentages are 0 to 100 and stored unrounded. There are no
timestamps, so the file only changes when results change. `m0.md` is the same results as
tables, with PASS or FAIL against each threshold.

## Continuous integration

`.github/workflows/eval.yml` runs on every pull request, on pushes to `main` and on demand.
It uses no secrets and never loads a model. It builds the database, runs the eval, posts
`m0.md` to the job summary and uploads both result files.

### Regression check

The job compares H1 for each planner against `eval/results/m0.json` on `main`. It fails if
H1 dropped by **5.0 percentage points or more** (a 4.9-point drop passes). Planners that are
not on `main` yet are skipped, and so is the whole check while `main` has no `m0.json`.

The job does **not** fail because a hypothesis fails. It fails only for a regression or a
crash, and a crash includes a stale B2 recording.

## When a hypothesis fails

Open an issue labelled `spiral-review` with the number, the cause and the decision:
persevere, re-plan or descope. Link it from the README. The table in `m0.md` usually shows
the cause: which violations, how many users, which group. Thresholds never change after
the first run, and a change to the simulated users or the validity rules needs its own
`spiral-review` issue explaining why.

## Adding a planner

Write it as a function `(profile, catalog, seed) -> meals | NoValidWeek | None`, add a
`Planner("M3", your_function)` to the list in `m0_planners` in `eval/run.py`, and it becomes
a new column in the results. Re-run the eval and commit the results when M3 and M4 land, and
whenever a change to `app/planner` affects plans (a rule or weight that is on by default).
M1 is already in the list.

## Plan edits (M3)

`python -m eval.edits` evaluates plain-English plan edits (issue #8) and writes `m3.json` and
`m3.md`; `eval.run` appends `m3.md` to the M0 report when it finds it in the same folder.

- **Requests:** 60 labelled ones in `eval/data/edit_requests.json`: 40 normal requests with
  the exact edits expected, 10 ambiguous ones that should get a clarifying question, and 10
  adversarial ones (allergy removal, budget increases, prompt injection) that should be
  refused.
- **Parsers:** the regex baseline from the issue (no model, no guard), the app's model-free
  mode (`EDIT_PARSER=regex`: the guard, then the regex parser), and M3 (the guard, then the
  LLM parser). A normal request counts as parsed right only if the edits match exactly,
  ignoring order and spelling (`edit_keys`).
- **Rules broken:** every edit any parser produces, for any request, is applied to the
  evaluation user's week (2,200 kcal, $450, allergic to eggs, planned by the solver for
  M0's Monday-to-Sunday week) and the result is checked with the M0 validator. Each day's
  calories are checked against its target after the edit's calorie shifts, worked out from
  the parsed edits rather than by the rule under test. The menu does not change between the
  base week and the edit, so any meal outside the edit that changes is counted. The command
  exits 1, failing CI, if any rule breaks or any meal outside the edit changes.
- **Re-plan time:** p95 over the 20 one-day edits, using the expected edits so it does not
  depend on a parser, with the rest of the week pinned, against re-solving the whole week.
  Neither includes the model call.

### The model's answers are recorded

Like B2, M3's model answers are recorded once and replayed, in
`eval/fixtures/m3_edits_cassette.json` (prompt hashes and responses, never prompt text).
Until a recording exists, the M3 column is left out and the command still runs.
`python -m eval.edits --live` records with the app's LLM (OpenAI if `OPENAI_API_KEY` is
set, otherwise the local model), then replays; `--readme` also refreshes the README table.
A new prompt version (see `app/planner/prompts/`) needs a new recording.

### Disclosure: one guard fix came from the labelled set

The guard's patterns were written before the adversarial requests were labelled, then
extended once: "Pretend my allergies don't exist" (x08) slipped through, and the allergy
pattern gained "exist". So the guard's refusal rate on this set is partly measured on an
example it was fixed for. New adversarial phrasings may still get through the guard, which
is why the solver enforces allergies and the budget on every plan regardless.

## Code map

| File | Purpose |
|---|---|
| `eval/catalog.py` | Loads in-stock items from open restaurants |
| `eval/profiles.py` | Generates the simulated users |
| `eval/validate.py` | The definition of a valid week |
| `eval/feasibility.py` | Whether a valid week exists for a user |
| `eval/baselines.py` | B1, B2, and recording and replaying LLM responses |
| `eval/planners.py` | M1, the solver, behind the eval's planner interface |
| `eval/edits.py` | The M3 plan-edit evaluation |
| `eval/data/edit_requests.json` | The 60 labelled plan-edit requests |
| `eval/run.py` | Metrics, the regression check, the report and the command |
| `app/tests/eval/` | The tests: `pytest app/tests/eval` |

## Troubleshooting

- **"Database not found":** run `python app/scripts/init_db.py`.
- **"The B2 recording has no response for this prompt":** the menu data or v1's prompts
  changed since the recording was made. Record it again (see above).
- **"was recorded with … not …":** a recording made with another model exists. Delete it to
  start a new one.
- **"No B2 recording":** record one with `python -m eval.run --seed 510 --record`.
- **The editor cannot resolve imports such as `pricing` in `eval/`:** the eval adds `app/` to
  the import path when it runs. To quiet the warning in VS Code, add
  `"python.analysis.extraPaths": ["app"]` to your settings.
