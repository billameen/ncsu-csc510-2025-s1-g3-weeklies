# Architecture (Overview)

- **Framework**: Flask  
- **Entrypoint**: Flask_app.py  
- **Database helpers**: sqlQueries.py (use only provided helpers)  
- **Templates / Static**: templates/, static/  
- **Meal planner**: planner/ (OR-Tools CP-SAT). `/generate_plan` calls `planner.solver.plan_week`;
  each rule is a plug-in in planner/rules/ (see [Planner Rules](./planner-rules.html)).
  `PLANNER=llm` switches back to the v1 LLM planner in menu_generation.py.  
- **Plan edits**: planner/edits/ turns a sentence into typed edits (guard, LLM or regex parser,
  Pydantic schema), planner/edits/resolve.py turns them into rule plug-ins, and
  planner/edits/replan.py re-plans only the affected meals. Routes: `/plan/edit` and its
  accept and discard routes. Prompts are versioned in planner/prompts/ (see
  [The LLM Proposes, the Solver Decides](./llm-proposes-solver-decides.html)).  
- **Fees (M4)**: planner/fees.py holds each restaurant's delivery and service fees (a synthetic
  model); the `fee_cost` rule charges them per order, with optional batching and pickup.
  fee_prefs.py stores each user's batching and pickup settings (`/profile/fees`) in the
  `UserFeePrefs` table.  
- **Wallet (M2)**: ledger.py is a double-entry ledger: every top-up, gift, order and refund is
  a transaction whose entries sum to zero, and a balance is the sum of a wallet's entries.
  money.py parses and formats amounts as integer cents. Routes: `/profile/wallet/topup`,
  `/profile/wallet/gift` and `/admin/orders/<id>/refund`.  
- **Evaluation**: eval/ at the repository root (see [How We Evaluate](./evaluation.html)).  

This document intentionally focuses on what’s present today.
