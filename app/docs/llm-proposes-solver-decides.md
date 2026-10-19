# The LLM proposes, the solver decides

Users think in sentences ("make Thursday vegetarian under $10"), not settings. Since M3
they can type one into the calendar's **Change your week** box. The risk with putting an
LLM in that path is that it quietly breaks a rule: drops an allergy, goes over budget, or
does whatever a cleverly worded request tells it to. Weeklies avoids that by giving the
model one narrow job.

**The LLM only turns the sentence into typed edits. The M1 solver re-plans and enforces
every rule.** Nothing the model says can loosen an allergy or the budget, and nothing is
saved until the user accepts a diff.

## The pipeline

1. **Guard (code, no model).** The request must be 1 to 300 characters. Requests to drop
   or ignore an allergy, raise or remove the budget, or instruct the assistant ("ignore
   previous instructions", role tags, pasted JSON) are refused here with a fixed message
   that points to the profile page where relevant. A model is never asked.
2. **Parser (model).** The model writes the request in the edit language below, as JSON
   with `action` set to `edit`, `clarify` or `refuse`. Pydantic checks the reply. An
   invalid reply gets one retry, then the request is reported as not understood, with a
   list of what can be asked for. The model's own words are shown only when it asks a
   clarifying question.
3. **Resolve (code).** "Thursday" becomes a date in the plan window, "dinners" a meal
   number, and dish words or restaurant names become menu ids (a dish word matches item
   names or descriptions, singular or plural, so "pork" finds every pork dish). A name
   that matches nothing turns into a question ("I couldn't find "Lasagna" on the menu.
   Which dish did you mean?").
4. **Re-plan (solver).** Every meal outside the edit is pinned. The edit's rules are added
   to the plan's usual rules (allergens, opening hours, stock, daily calories, weekly
   budget, variety), and the solver re-plans the rest, changing as few meals as it can.
   If the edit can't be met, the user gets the reason and the closest plan: each filter,
   inclusion and daily limit becomes a strong preference (a calorie shift stays as asked,
   and wishes only break ties), and the preview says what that plan still misses ("Every
   day costs $42.18 (you asked for at most $4.00 a day)"). If even that plan changes
   nothing, the edit is reported as impossible, with the reason.
5. **Accept or Discard.** The diff shows each changed meal, its price change, and the
   week's cost and calories before and after. Accept checks the proposal again against the
   menu and profile as they are now (stock, opening hours, allergies, budget, calories) and
   saves it; it is refused if anything changed since the preview. Discard leaves the plan
   untouched.

## The edit language

Each edit applies to some days and meals (`days`, `meals`; all of them if left out).

| Edit | Means | Example request |
|---|---|---|
| `filter` | Every meal meets a condition | "make Thursday vegetarian", "dinners under $15", "no pork this week", "only Cowpers for breakfast" |
| `include` | At least `times` meals meet a condition | "pizza on Friday night", "chicken twice this week" |
| `day_limit` | Each day's cost (with tax and fees) or calories under or over a limit | "keep each day under $40", "no day over 2,000 calories" |
| `prefer` | A wish, never a rule: cheaper, fewer or more calories, more variety, or meals that meet a condition | "cheaper lunches if possible", "vegetarian dinners when you can" |
| `calorie_shift` | Move a day's calorie target by up to 1,000 kcal | "lighter days on the weekend" |

A condition is a field, an operator and a value:

| Field | Operators | Value |
|---|---|---|
| `tag` | `is`, `is_not` | vegetarian, vegan, spicy, gluten-free, dairy-free, low-calorie |
| `dish` | `is`, `is_not` | a dish name or food word |
| `restaurant` | `is`, `is_not` | a restaurant name |
| `allergen` | `is`, `is_not` | an allergen word, such as shellfish |
| `price` | `<=`, `>=` | dollars for one meal (menu price) |
| `calories` | `<=`, `>=` | calories for one meal |

Every edit only adds a restriction or a preference. Nothing in the language can remove an
allergy, raise the weekly budget or relax a rule: a daily cost limit is checked on top of
the weekly budget, and a preference is weighed against the plan's other preferences but
never against a hard rule. Requests the language can't express get a clarifying question.

## Why this is safe even when the model is wrong

The parser can only *add* restrictions and preferences, and the solver enforces every rule
whatever the parser produces. A wrong parse can give the user a week they didn't ask for, which they
see in the diff and can discard. It cannot give them a week that breaks a rule.

The evaluation checks this directly. It applies **every** edit any parser produces, even
for ambiguous and adversarial requests, to a real week and runs the M0 validator on the
result. CI fails if a single rule is broken or a meal outside the edit changes.

## Results

Run `python -m eval.edits` (no key or model needed: it replays recorded model answers once
a recording exists; `--live` makes one).
The current numbers are in the README and `eval/results/m3.md`. Without a model, the
regex baseline already shows the solver's guarantee: its edits break **0** rules, even
when it turns an adversarial request into edits, because the solver enforces them all.
What a model adds is understanding: exact parses of varied wording, clarifying questions
for vague requests, and refusals the guard's patterns don't cover.

Re-planning one day with the rest of the week pinned takes about 0.3 s at p95, against
about 3 s to re-solve the whole week (target ≤ 2 s, excluding the model call).

## Limits

- The model is whatever `llm_toolkit` selects: OpenAI's `gpt-4o-mini` with a key, or a
  small local model (granite-4.0-h-350M) without one. A small model parses less of the
  varied wording correctly; the guard and the solver keep it safe either way.
- Tags are decided from item names, descriptions and allergen tags (the menu has no tag
  column), and deliberately strictly: any meat word rules out "vegetarian".
- Edits apply to the next 7 days of an existing plan, or to as many of them as are fully
  planned. A day that is not planned is never filled in. Plan the week first.
- The menu has no cuisine, protein or ingredient columns, so "Italian" or "high protein"
  can only be matched through dish words in names and descriptions, or a new tag (see the
  tutorial).
- A calorie shift changes whole days, up to 1,000 kcal, within the profile's 800 to
  6,000 kcal bounds, and each day can have only one shift per edit.

To support a new kind of request, see [Teach the parser a new request](./teach-the-parser.html).
