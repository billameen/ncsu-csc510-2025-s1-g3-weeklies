# Contributing to Weeklies

Thanks for helping. Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first.

## Workflow

- Branch off `development` and open pull requests back into `development`.
- Keep commits small and about one thing, and reference the issue (e.g. "for #5").
- Before opening a PR, run from the repository root:

```bash
pytest                  # tests and coverage (must stay at or above 80%)
black --check .         # formatting
ruff check .            # lint
```

- Setup, the local database and running the app are in [INSTALLATION.md](INSTALLATION.md).
- Schema changes go in three places by hand: a migration in `app/migrations/`,
  `app/db/seed.sql`, and the test schema in `app/tests/conftest.py`.

## Dependencies

Whenever you add, remove or change the version of a package in `app/requirements.txt`, update
[THIRD_PARTY_LIBRARIES.md](THIRD_PARTY_LIBRARIES.md) in the same pull request (how to regenerate
it is at the bottom of that file). Don't add a GPL or AGPL package without asking the team first.

## Extending the planner safely

The weekly planner (`app/planner/`) decides what users eat and spend, so changes to it carry
more risk than most. The tutorial
[Add a planner rule in 15 minutes](app/docs/planner-rules.md) shows how to write a rule;
these are the rules for doing it safely.

**Add rules, do not edit the solver.** A new requirement is a new file in
`app/planner/rules/`. If a rule seems to need a change to `solver.py` or `context.py`, open an
issue first: those changes affect every plan.

**Hard means never broken.** Make a rule hard only if a plan that breaks it is unusable
(allergens, budget). Anything a user would trade off is soft. A hard rule that is too strict
turns valid weeks into "no valid week" for real users.

**Rules only read what they are given.** Use `ctx.request` and `ctx.menu`; never query the
database, the clock, the network or a random number generator inside a rule. Given the same
request, a rule must add the same constraints every time, so the planner's plans stay
repeatable, and tests rely on it.

**Explain only what you can prove.** `explain(ctx)` is shown to the user as the reason their
week is impossible. Return a sentence only when your rule is the cause (for example, the plan
works once it is lifted: `cheapest_without(ctx, self)` is not None) and `None` otherwise.
Include the numbers and what the user could change.

**Weights are in cents.** `prefer_low_cost` charges 1 per cent spent, so a soft rule's
weight says how many cents one unit of its penalty is worth. Document the weight and why.

**Test the rule alone.** One test file per rule, using only `one_item_per_meal` and your rule
on a `menu_factory` menu, covering: the rule holds, the explanation when it cannot, and
silence when another rule is the cause. A broken rule must be refused when it loads, not
halfway through a plan; `planner.registry.register` already checks the basics.

**Re-run the evaluation for anything on by default.** A rule or weight that is on by default
changes every user's week. Run `python -m eval.run --seed 510`, check that M1 still passes H1
to H4 (H3, p95 planning time, must stay at or below 5 s), and commit `eval/results/` in the
same pull request. CI fails the PR if H1 drops by 5 points or more against `main`.

**Plan edits only ever tighten.** A new edit type, condition field or tag in the edit
language (see [Teach the parser a new request](app/docs/teach-the-parser.md)) must add a
restriction or a preference, never remove an allergy, raise the budget or relax a rule.
Change the parser's prompt only by adding a new version in `app/planner/prompts/`, then
re-record the model's answers with `python -m eval.edits --live --readme` and commit the
recording and results. CI fails if any edit in the evaluation breaks a rule, changes a meal
outside the edit, or is missed in a plan the solver called a full match.

**Keep v1 working.** `PLANNER=llm` runs the v1 LLM planner, which the evaluation uses as
baseline B2. Do not remove it or change its behavior.
