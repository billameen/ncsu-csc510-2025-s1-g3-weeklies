# Teach the parser a new request

Plan edits ("make Thursday vegetarian under $10") reach the solver as typed edits. The
parser can only produce edit types that exist, so a new kind of request needs three
things: a **rule plug-in** the solver enforces, an **entry in the format** the parser
fills in, and **three labelled examples** so the evaluation measures it.

This guide adds `max_calories`, for requests like "dinners under 600 calories".

## How a request becomes an edit

```
"dinners under 600 calories"
   │  guard.py         refuses loosening and injection, in code
   │  llm_parser.py    model fills in the format; Pydantic checks it (one retry)
   ▼
{"action": "edit", "edits": [{"type": "max_calories", "max_kcal": 600, "meals": ["dinner"]}]}
   │  resolve.py       days and meals → dates; edit → rule plug-in
   │  replan.py        pins every other meal, re-solves, returns a diff
   ▼
Accept / Discard
```

An edit type may only **add** a restriction. Never add one that removes an allergy,
raises the budget or relaxes a rule: those belong on the profile page, and the guard
refuses requests for them.

## 1. The rule plug-in

Item-level edits are `ScopedItemFilter`s: write `allows`, and the base class applies it
only to the meals in the edit's scope. Create `app/planner/rules/max_calories.py`:

```python
from planner.constraint import ScopedItemFilter
from planner.registry import register


@register
class MaxCalories(ScopedItemFilter):
    """Inside its scope, only items with at most `max_kcal` calories."""

    name = "max_calories"
    summary = "Some meals must have at most a set number of calories."
    blocked_reason = "have too many calories"

    def __init__(self, max_kcal: int, scope=None):
        if not isinstance(max_kcal, int) or max_kcal <= 0:
            raise ValueError(f"{self.name}: max_kcal must be a positive whole number")
        super().__init__(scope)
        self.max_kcal = max_kcal

    def allows(self, item, slot, ctx):
        return item.calories <= self.max_kcal

    def describe_block(self, slot, ctx):
        return f"have more than {self.max_kcal:,} calories"
```

Test it alone, like the other rules (see [Planner Rules](./planner-rules.html)):
`app/tests/planner/test_planner_rule_max_calories.py`.

## 2. The format entry

In `app/planner/edits/schema.py`, add the edit class and list it in `Edit` and
`EDIT_TYPES`:

```python
class MaxCalories(_Scoped):
    """Only items at or under a calorie count ("dinners under 600 calories")."""

    type: Literal["max_calories"]
    max_kcal: int = Field(gt=0, le=3000)

    def key(self):
        return (self.type, self.max_kcal, self.day_codes(), self.meal_codes())


Edit = Annotated[
    Union[RequireTag, MaxPrice, ExcludeItem, ExcludeRestaurant, CalorieShift, MaxCalories],
    Field(discriminator="type"),
]
```

`key()` is what the evaluation compares, so include every field that changes the meaning.

In `app/planner/edits/resolve.py`, map it to the rule in `to_rule`:

```python
    if isinstance(edit, MaxCalories):
        return get("max_calories")(edit.max_kcal, scope)
```

Then tell the model. Prompts are versioned: copy
`app/planner/prompts/edit_parser_v1.txt` to `edit_parser_v2.txt`, add the line

```
{"type": "max_calories", "max_kcal": WHOLE_NUMBER, "days": DAYS, "meals": MEALS}
```

and one example of it, and set `PROMPT_VERSION = "v2"` in `llm_parser.py`. Keep v1 in
the repo so older recordings can still be explained.

## 3. Three labelled examples

Add at least three normal requests to `eval/data/edit_requests.json`, each with the exact
edits expected, and vary the wording, days and meals:

```json
{"id": "n41", "category": "normal", "text": "Dinners under 600 calories",
 "expected": [{"type": "max_calories", "max_kcal": 600, "meals": ["dinner"]}]},
{"id": "n42", "category": "normal", "text": "Keep Tuesday's lunch below 500 kcal",
 "expected": [{"type": "max_calories", "max_kcal": 500, "days": ["tue"], "meals": ["lunch"]}]},
{"id": "n43", "category": "normal", "text": "No meal over 900 calories on the weekend",
 "expected": [{"type": "max_calories", "max_kcal": 900, "days": ["weekend"]}]}
```

Don't reuse the prompt's own example as a labelled request; the evaluation should measure
requests the model has not been shown.

## 4. Re-record and check

A new prompt changes every prompt the evaluation recorded, so record again with the app's
model, then re-run:

```bash
python -m eval.edits --live --readme   # records the model's answers, updates the README table
pytest app/tests/planner app/tests/eval -q
```

Commit the rule, its test, the schema and prompt changes, the new examples, and the
updated `eval/fixtures/m3_edits_cassette.json`, `eval/results/m3.*` and README. CI replays
the recording and fails if any edit breaks a rule.

## Checklist

- [ ] The edit only adds a restriction.
- [ ] Rule plug-in plus its isolated test.
- [ ] Schema class, listed in `Edit` and `EDIT_TYPES`, with a `key()`.
- [ ] `to_rule` mapping.
- [ ] New prompt version with the format line and one example.
- [ ] Three or more labelled examples.
- [ ] Re-recorded, and `python -m eval.edits` passes.
