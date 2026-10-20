# Teach the parser a new request

Plan edits ("make Thursday vegetarian under $10") reach the solver in a small edit language.
Each edit is one of `filter`, `include`, `day_limit`, `prefer` or `calorie_shift`, applied to
some days and meals, and most take a condition on one menu item: a field (`tag`, `dish`,
`restaurant`, `allergen`, `price`, `calories`), an operator and a value. See
[The LLM proposes, the solver decides](./llm-proposes-solver-decides.html) for the whole list.

A new kind of request needs one of three things, from least to most work:

1. **It can already be said in the language** ("no dish over 900 calories on the weekend" is
   a `filter` on `calories`). Add labelled examples (step 4) and, if the model gets it wrong,
   an example to a new prompt version (step 3).
2. **It needs a new tag** ("high-protein"). Add a test function to `TAGS` in
   `app/planner/tags.py`; the prompt lists the tags on its own. Then add labelled examples.
3. **It needs a new edit type.** A rule plug-in the solver enforces, an entry in the format,
   a prompt version and labelled examples. The rest of this guide adds one: `repeat_limit`,
   for requests like "no dish more than twice this week". (`prefer` with goal `variety` asks
   for fewer repeats; `repeat_limit` makes it a rule.)

## How a request becomes an edit

```
"no dish more than twice this week"
   │  guard.py         refuses loosening and injection, in code
   │  llm_parser.py    model fills in the format; Pydantic checks it (one retry)
   ▼
{"action": "edit", "edits": [{"type": "repeat_limit", "max_times": 2}]}
   │  resolve.py       days and meals → dates; edit → rule plug-in
   │  replan.py        pins every other meal, re-solves, returns a diff
   ▼
Accept / Discard
```

An edit type may only **add** a restriction or a preference. Never add one that removes an
allergy, raises the budget or relaxes a rule: those belong on the profile page, and the guard
refuses requests for them.

## 1. The rule plug-in

Create `app/planner/rules/repeat_limit.py`:

```python
"""Edit rule: no dish more than a set number of times ("no dish more than twice")."""

from planner.constraint import Constraint
from planner.registry import register
from planner.scope import EVERY_MEAL


@register
class RepeatLimit(Constraint):
    """Inside its scope, each item is picked at most `max_times` times."""

    name = "repeat_limit"
    summary = "No dish is planned more than a set number of times."
    order = 75
    enabled_by_default = False

    def __init__(self, max_times: int, scope=None):
        if not isinstance(max_times, int) or isinstance(max_times, bool) or max_times < 1:
            raise ValueError(f"{self.name}: max_times must be a whole number of at least 1")
        self.max_times = max_times
        self.scope = scope or EVERY_MEAL

    def apply(self, ctx):
        """For each item, its picks over the covered slots <= max_times."""
        uses = {}
        for slot in ctx.slots:
            if self.scope.covers(slot):
                for item, var in ctx.picks(slot):
                    uses.setdefault(item.itm_id, []).append(var)
        for picks in uses.values():
            if len(picks) > self.max_times:
                ctx.model.Add(sum(picks) <= self.max_times)

    def unmet(self, plan):
        """E.g. "Beef Ribs is planned 3 times"; None when every dish is within the limit."""
        counts = {}
        for slot, item in plan.items():
            if self.scope.covers(slot):
                counts[item] = counts.get(item, 0) + 1
        over = [f"{item.name} is planned {n} times" for item, n in counts.items() if n > self.max_times]
        return "; ".join(over) or None
```

Two optional methods connect a rule to plan edits:

- `unmet(plan)` says in words what a plan misses of the edit. The preview shows it when the
  edit could only be met partly, and the evaluation fails if a plan the solver called a full
  match misses an edit.
- `soften()` returns a preference version of the rule. When an edit can't be met exactly,
  the closest option is planned with every edit softened (see `include_meals` and
  `day_limit` for examples). Without it, an edit that can't be met is reported as impossible
  with the solver's explanation.

Test the rule alone, like the other rules (see [Planner Rules](./planner-rules.html)), in
`app/tests/planner/test_planner_rule_repeat_limit.py`:

```python
from menu_factory import item, menu, request

from planner.registry import get
from planner.solver import plan_week

OneItemPerMeal, PreferLowCost = get("one_item_per_meal"), get("prefer_low_cost")
RepeatLimit = get("repeat_limit")
MENU = menu([item(1, price_cents=500), item(2, price_cents=900)])


def test_no_item_more_than_the_limit_even_when_it_is_cheapest():
    result = plan_week(request(), MENU, rules=[OneItemPerMeal(), PreferLowCost(), RepeatLimit(2)])
    assert sorted(m.itm_id for m in result.meals) == [1, 1, 2]
```

## 2. The format entry

In `app/planner/edits/schema.py`, add the edit class and list it in `Edit` and `EDIT_TYPES`:

```python
class RepeatLimit(_Scoped):
    """No dish more than `max_times` times ("no dish more than twice this week")."""

    type: Literal["repeat_limit"]
    max_times: int = Field(ge=1, le=21)

    def key(self):
        return (self.type, self.max_times, self.day_codes(), self.meal_codes())


Edit = Annotated[
    Union[Filter, Include, DayLimit, Prefer, CalorieShift, RepeatLimit],
    Field(discriminator="type"),
]
EDIT_TYPES = ("filter", "include", "day_limit", "prefer", "calorie_shift", "repeat_limit")
```

`key()` is what the evaluation compares, so include every field that changes the meaning.

In `app/planner/edits/resolve.py`, import it and map it to the rule in `to_rule`:

```python
    if isinstance(edit, RepeatLimit):
        return get("repeat_limit")(edit.max_times, scope)
```

## 3. Tell the model

Prompts are versioned: copy `app/planner/prompts/edit_parser_v3.txt` to
`edit_parser_v4.txt`, add the edit type to the list

```
{"type": "repeat_limit", "max_times": NUMBER, "days": DAYS, "meals": MEALS}
  No dish more than "max_times" times in those days and meals.
```

and one example of it

```
Request: never the same lunch twice
{"action": "edit", "edits": [{"type": "repeat_limit", "max_times": 1, "meals": ["lunch"]}]}
```

then set `PROMPT_VERSION = "v4"` in `llm_parser.py`. Keep v3 in the repo so older
recordings can still be explained. A test checks that the prompt names every edit type and
that each of its examples is valid, so a format change the prompt does not describe fails.

## 4. Three labelled examples

Add at least three normal requests to `eval/data/edit_requests.json`, each with the exact
edits expected, and vary the wording, days and meals:

```json
{"id": "n61", "category": "normal", "text": "No dish more than twice this week",
 "expected": [{"type": "repeat_limit", "max_times": 2}]},
{"id": "n62", "category": "normal", "text": "Don't repeat any dinner on weekdays",
 "expected": [{"type": "repeat_limit", "max_times": 1, "days": ["weekdays"], "meals": ["dinner"]}]},
{"id": "n63", "category": "normal", "text": "Each breakfast at most three times",
 "expected": [{"type": "repeat_limit", "max_times": 3, "meals": ["breakfast"]}]}
```

Update the counts in `test_the_dataset_has_..._requests` in `app/tests/eval/test_edits.py`.
Don't reuse the prompt's own example as a labelled request; the evaluation should measure
requests the model has not been shown.

## 5. Re-record and check

A new prompt changes every prompt the evaluation recorded, so record again with the app's
model, then re-run:

```bash
python -m eval.edits --live --readme   # records the model's answers, updates the README table
pytest app/tests/planner app/tests/eval -q
```

Commit the rule, its test, the schema and prompt changes, the new examples, and the updated
`eval/fixtures/m3_edits_cassette.json`, `eval/results/m3.*` and README. CI replays the
recording and fails if any edit breaks a rule, changes a meal outside the edit, or is missed
in a plan the solver called a full match.

## Checklist

- [ ] The edit only adds a restriction or a preference.
- [ ] Rule plug-in plus its isolated test, with `unmet` (and `soften` if a closest option
      makes sense).
- [ ] Schema class, listed in `Edit` and `EDIT_TYPES`, with a `key()`.
- [ ] `to_rule` mapping (and `affected_scope`, if the edit re-plans whole days).
- [ ] New prompt version with the edit type and one example.
- [ ] Three or more labelled examples, and the counts in the dataset test.
- [ ] Re-recorded, and `python -m eval.edits` passes.
