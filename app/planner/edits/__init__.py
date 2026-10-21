"""
Plain-English plan edits: "make Thursday vegetarian under $10".

The LLM proposes, the solver decides. A sentence goes through:

1. `guard`: refuses anything that would loosen a rule (allergies, budget) or that tries to
   instruct the assistant, before any model sees it.
2. A parser (`llm_parser`, or the `regex_parser` baseline) turns it into typed edits in the
   format defined in `schema`, or asks a clarifying question.
3. `resolve` maps day and meal phrases to the plan's dates and names to menu ids, and turns
   each edit into an M1 rule plug-in.
4. `replan` re-solves only the affected meals with every other meal pinned, and returns a
   diff for the user to accept or discard. The solver still enforces every rule.
"""
