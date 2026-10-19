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
2. **Parser (model).** The model fills in a fixed JSON format with `action` set to `edit`,
   `clarify` or `refuse`, plus typed edits. The only edit types are the ones that exist as
   solver plug-ins: `require_tag`, `max_price`, `exclude_item`, `exclude_restaurant` and
   `calorie_shift`, each with the days and meals it applies to. Pydantic checks the reply.
   An invalid reply gets one retry, then the request is reported as not understood.
   The model's own words are shown only when it asks a clarifying question.
3. **Resolve (code).** "Thursday" becomes a date in the plan window, "dinners" a meal
   number, and dish or restaurant names become menu ids. A name that matches nothing turns
   into a question ("I couldn't find "Lasagna" on the menu. Which dish did you mean?").
4. **Re-plan (solver).** Every meal outside the edit is pinned. The edit's rules are added
   to the plan's usual rules (allergens, opening hours, stock, daily calories, weekly
   budget, variety), and the solver re-plans the rest, changing as few meals as it can.
   If the edit can't be met, the user gets the reason and the closest plan, with how many
   of the edited meals match.
5. **Accept or Discard.** The diff shows each changed meal, its price change, and the
   week's cost and calories before and after. Accept saves it (refused if the plan changed
   since the preview). Discard leaves the plan untouched.

## Why this is safe even when the model is wrong

The parser can only *add* restrictions, and the solver enforces every rule whatever the
parser produces. A wrong parse can give the user a week they didn't ask for, which they
see in the diff and can discard. It cannot give them a week that breaks a rule.

The evaluation checks this directly. It applies **every** edit any parser produces, even
for ambiguous and adversarial requests, to a real week and runs the M0 validator on the
result. CI fails if a single rule is broken or a meal outside the edit changes.

## Results

Run `python -m eval.edits` (no key or model needed: it replays recorded model answers).
The current numbers are in the README and `eval/results/m3.md`. Without a model, the
regex baseline already shows the solver's guarantee: its edits break **0** rules, even
when it turns an adversarial request into edits, because the solver enforces them all.
What a model adds is understanding: exact parses of varied wording, clarifying questions
for vague requests, and refusals the guard's patterns don't cover.

Re-planning one day with the rest of the week pinned takes about 0.3 s at p95, against
about 2.6 s to re-solve the whole week (target ≤ 2 s, excluding the model call).

## Limits

- The model is whatever `llm_toolkit` selects: OpenAI's `gpt-4o-mini` with a key, or a
  small local model (granite-4.0-h-350M) without one. A small model parses less of the
  varied wording correctly; the guard and the solver keep it safe either way.
- Tags are decided from item names, descriptions and allergen tags (the menu has no tag
  column), and deliberately strictly: any meat word rules out "vegetarian".
- Edits apply to the next 7 days of an existing plan. Plan the week first.
- A calorie shift changes whole days, up to 1,000 kcal, within the profile's 800 to
  6,000 kcal bounds.

To support a new kind of request, see [Teach the parser a new request](./teach-the-parser.html).
