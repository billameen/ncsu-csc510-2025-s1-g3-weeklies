# 🍽️ WEEKLIES — Intelligent Meal Planning and Delivery System
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23547302.svg)](https://doi.org/10.5281/zenodo.23547302)
[![Tests](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/actions/workflows/ci.yml)
[![Docs](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/actions/workflows/docs.yml/badge.svg?branch=main&event=push)](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/actions/workflows/docs.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)]()
[![Flask](https://img.shields.io/badge/Flask-2.x-lightgrey?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/github/license/billameen/ncsu-csc510-2025-s1-g3-weeklies.svg)](LICENSE)
[![GitHub last commit](https://img.shields.io/github/last-commit/billameen/ncsu-csc510-2025-s1-g3-weeklies.svg)](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/commits)
[![GitHub issues](https://img.shields.io/github/issues/billameen/ncsu-csc510-2025-s1-g3-weeklies.svg)](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/issues)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/billameen/ncsu-csc510-2025-s1-g3-weeklies.svg)](https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies/pulls)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-46a2f1?logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)

**[▶ Watch the teaser](https://youtu.be/6kqtTYBGfYY)** · [Full demo (YouTube)](https://youtu.be/PxjkRfjJGXs)

---

## 🧠 Project Overview

**Weeklies** is a full-stack Flask web application for planning and ordering a week of meals.
Users register, set dietary preferences, allergies, a daily calorie target and a weekly budget,
browse restaurants and menus, and schedule orders on a calendar. A constraint solver plans all 21
meals of their week at once so that every day hits the calorie target, the week fits the budget,
and no meal contains their allergens.

This repository is our team's continuation of Weeklies for *CSC 510: Software Engineering
(NC State University)*. We are extending the existing application with a new set of milestones
(see [Roadmap](#️-roadmap)), while keeping the codebase tested, documented, and continuously integrated.

> **Built on Weeklies (Fall 2025).** This project starts from the
> [Weeklies codebase](https://github.com/Aum3010/ncsu-csc510-2025-s1-g3-weeklies) by Aum Pandya,
> Pranav Bhagwat, and Tayo Olukotun, which itself extended earlier work by Section 001 Group 9
> (Taylor J. Brown, Kunal Jindal, Ashritha Bugada, Daniel Dong). Thank you to both teams.

---

## 🎬 Videos

| Teaser | Full demo |
|:---:|:---:|
| [![Watch the Weeklies teaser on YouTube](https://img.youtube.com/vi/6kqtTYBGfYY/hqdefault.jpg)](https://youtu.be/6kqtTYBGfYY) | [![Watch the Weeklies demo on YouTube](https://img.youtube.com/vi/PxjkRfjJGXs/hqdefault.jpg)](https://youtu.be/PxjkRfjJGXs) |
| **[▶ Watch the teaser](https://youtu.be/6kqtTYBGfYY)** | **[▶ Watch the demo](https://youtu.be/PxjkRfjJGXs)** — a 2–5 minute walk-through of the main features |

---

## 🗺️ Roadmap

| # | Milestone | Lead | Status |
|---|-----------|------|--------|
| M0 | [Risk evaluation](#-meal-planner-results): a validator, 100 simulated users and baseline numbers for the v1 LLM planner | Bill Ameen | ✅ Done |
| M1 | [Constraint-solver planner](#-meal-planner-results): OR-Tools CP-SAT replaces the LLM, with daily calorie and budget rules as plug-ins | Shaan Chandra | ✅ Done |
| M2 | [Wallet ledger](#-wallet-ledger-m2): double-entry ledger in integer cents, one charge per payment, admin refunds | Siddhant Joshi | ✅ Done |
| M3 | [Plain-English plan edits](#-plan-edits-m3): the LLM proposes an edit, the solver decides | Shaan Chandra | ✅ Done |
| M4 | [Fee-aware batching](#m4-fee-aware-batching): fees per order, optional batching and pickup | Siddhant Joshi | ✅ Done |

---

## 📊 Meal Planner Results

Since M1 the week is planned by an OR-Tools CP-SAT solver instead of an LLM
([why](app/docs/why-a-solver.md)). Every rule is a plug-in
([add one in 15 minutes](app/docs/planner-rules.md)). M0 evaluation, 100 simulated users,
seed 510 ([full results](eval/results/m0.md), [method](app/docs/evaluation.md)):

| | Target | v1 LLM (B2) | Solver (M1) |
|---|---|---|---|
| H1 Feasible users who get a valid week | ≥ 90% | 0% | **100%** |
| H2 Distinct items per week (median) | ≥ 14 | 19 | **20** |
| H3 Time to plan a week (p95) | ≤ 5 s | 216 s | **2.8 s** |
| H4 Infeasible users told "no valid week" | ≥ 90% | 0% | **100%** |
| Infeasible users told why | 100% | 0% | **100%** |

Reproduce with `python -m eval.run --seed 510` (about 3 minutes, no API key). `PLANNER=llm` switches
`/generate_plan` back to v1.

### M4: fee-aware batching

Every meal used to be its own delivery order, so a 21-meal week paid **$115.08** in fees
($3.99 delivery + $1.49 service, 21 times) before any food. M4 counts fees per *order*
([`planner/rules/fee_cost.py`](app/planner/rules/fee_cost.py)):

- **Batching** (opt-in): meals from the same restaurant on the same day, at most 6 hours apart
  (breakfast + lunch, or lunch + dinner), share one delivery. That 21-meal week drops to 14
  orders: **$115.08 → $76.72**.
- **Pickup** (opt-in per restaurant *and* day): no delivery fee.
- Fees count toward the weekly budget, so batching can make a budget M1 called impossible fit.

> **The fees are a synthetic model**, not real prices: the seed data gives each restaurant a
> made-up delivery fee from $1.99 to $5.99 ([`planner/fees.py`](app/planner/fees.py)).

M0's 100 users, seed 510, against M1 with batching off ([full results](eval/results/m4.md)):

| Target | Goal | M4 batching | M4 batching + pickup¹ |
|---|---|---|---|
| Median weekly fee savings vs M1 | ≥ 25% | **26.8%** ✅ | **32.5%** ✅ |
| Valid-week rate | no drop vs M1 (67%) | **74%** ✅ | **74%** ✅ |
| Variety (median distinct items) | drop ≤ 2 vs M1 (20) | **19** (−1) ✅ | **19** (−1) ✅ |
| Food-safety window violations | 0 | **0** ✅ | **0** ✅ |
| Budgets only possible with batching | report | **7 users** | **7 users** |

Median fees fall from $98.58 to $71.96 a week (21 → 15 orders); the median user pays $106.08 →
$77.70. No user loses a valid week, and the validator, which recomputes every order's fees on
its own, agrees with the planner on all of them.

![Per-user weekly fee savings](eval/results/m4_savings.png)

¹ Pickup opt-ins are synthetic: half the users opt into pickup at 5 restaurants on the weekend
and one weekday. Reproduce with `python -m eval.m4 --seed 510` (about 10 minutes; resumes if
stopped). The M0 table above was measured before M4 gave restaurants their own fees; rerun
`python -m eval.run --seed 510` to refresh it.

---

## 💰 Wallet Ledger (M2)

The v1 wallet was one float column on the user row, updated in place, so a double-clicked "Pay",
two gifts at once or a failed debit could create or lose money. Since M2 every money movement is
a transaction in a double-entry ledger ([`app/ledger.py`](app/ledger.py)):

- **Entries always add up to zero.** Money only moves between accounts (a user's wallet, a
  restaurant, fees, tax, top-ups); it never appears or disappears.
- **Integer cents, never floats.** Order charges are worked out and stored in cents, and a test
  fails if money code uses a float.
- **Append-only.** Database triggers block edits and deletes; refunds post a reversing
  transaction instead.
- **One charge per payment.** A repeated request (a double click, a refreshed form) is recognised
  and charged only once, and a wallet can never go negative, even with concurrent gifts.
- **Visible.** Users see their wallet history on the profile, receipts show the ledger ID, and
  admins get a ledger check and a refund button.

Existing balances move into the ledger with
[`migrations/add_wallet_ledger.py`](app/migrations/add_wallet_ledger.py), which checks that every
balance matches afterwards.

---

## 💬 Plan Edits (M3)

Since M3, users can change their week in plain English on the calendar ("make Thursday vegetarian
under $10", "keep each day under $40", "pizza on Friday night", "cheaper lunches if possible"). The
LLM only turns the sentence into a small edit language (filters, inclusions, daily limits,
preferences and calorie shifts over tags, dishes, restaurants, allergens, prices and calories); the
solver re-plans just the affected meals and still enforces every rule, and nothing is saved until
the user accepts a diff ([how it works](app/docs/llm-proposes-solver-decides.md),
[teach it a new request](app/docs/teach-the-parser.md)). Evaluation on 82 labelled requests
([full results](eval/results/m3.md)):

<!-- m3-results:start -->
60 normal, 10 ambiguous and 12 adversarial requests; LLM answers recorded from `ibm-granite/granite-4.0-micro`.

| Metric | Target | Regex baseline | Guard + regex (no model) | M3 (guard + LLM) |
|---|---|---|---|---|
| Edits parsed exactly right (normal requests) | ≥ 85% | 76.7% FAIL | 76.7% FAIL | 86.7% PASS |
| Adversarial requests refused | ≥ 90% | 0.0% FAIL | 83.3% FAIL | 91.7% PASS |
| Ambiguous requests get a clarifying question | ≥ 70% | 0.0% FAIL | 0.0% FAIL | 60.0% FAIL |
| Rules broken after an edit | ≤ 0 | 0 PASS | 0 PASS | 0 PASS |
| Meals outside the edit that changed | 0 | 0 | 0 | 0 |
| Edits missed in a plan called a match | 0 | 0 | 0 | 0 |

Re-plan time for the 25 one-day edits, excluding the LLM call: p95 **0.52 s** with the rest of the week pinned (target ≤ 2 s), against 4.01 s re-solving the whole week.
<!-- m3-results:end -->

Reproduce with `python -m eval.edits` (no API key: model answers are replayed from a recording).
`python -m eval.edits --live --readme` re-records them with the app's LLM and refreshes this table.
`EDIT_PARSER=regex` runs the app's edit box without a model.

---

## 🧩 What We Started From

Features inherited from Weeklies (Fall 2025):

- 👤 **User registration & authentication**
- 🍱 **Restaurant and menu browsing** with allergen and cuisine tagging
- 🧭 **User preference tagging** and filtering
- 📅 **Calendar-based order scheduling**
- 🤖 **LLM-generated weekly meal plans** (OpenAI, or a local HuggingFace model as fallback)
- 💰 **Wallet system** for paying, topping up, and gifting balance
- ⭐ **Restaurant reviews and ratings**
- 📈 **User insights dashboard** for dining and spending history
- ⚙️ **Admin dashboard** for managing orders and order status
- ✉️ **Support ticket system**
- 🧾 **PDF order receipts**

---

## ⚙️ Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Frontend** | Server-rendered Jinja2 templates, plain HTML/CSS/JavaScript |
| **Backend** | Python 3.11+, Flask |
| **Database** | SQLite via raw `sqlite3` (helpers in `app/sqlQueries.py`) |
| **Meal planner** | OR-Tools CP-SAT constraint solver (`app/planner/`) |
| **LLM** | OpenAI API (`gpt-4o-mini`) or local HuggingFace model (v1 planner, `PLANNER=llm`) |
| **PDF** | ReportLab |
| **Tooling** | GitHub Actions, pytest, pytest-cov, ruff, black, pdoc |

---

## 🧱 Repository Layout

```
.
├── app/
│   ├── Flask_app.py          # all routes and helpers
│   ├── sqlQueries.py         # DB access helpers
│   ├── ledger.py             # M2 double-entry wallet ledger
│   ├── planner/              # CP-SAT weekly planner; rules/ holds one plug-in per rule;
│   │                         # edits/ turns plain-English edits into rules; prompts/ is versioned
│   ├── menu_generation.py    # v1 LLM meal-plan generation (PLANNER=llm)
│   ├── llm_toolkit.py        # LLM provider wrapper
│   ├── pdf_receipt.py        # receipt PDFs
│   ├── models.py
│   ├── templates/  static/
│   ├── db/seed.sql           # schema + demo data (source of truth for the local DB)
│   ├── scripts/init_db.py    # builds app/CSC510_DB.db from db/seed.sql
│   ├── migrations/           # one-off, idempotent schema changes
│   ├── tests/                # smoke / unit / integration / e2e / llm / planner / eval
│   ├── docs/                 # architecture, evaluation, planner rules, why a solver
│   └── requirements.txt
├── eval/                     # M0 evaluation: validator, simulated users, planners, results
├── .github/workflows/        # ci.yml (tests), eval.yml (M0 eval), docs.yml (pdoc → GitHub Pages)
├── scripts/build_docs.py
├── INSTALLATION.md  CONTRIBUTING.md
├── pytest.ini  pyproject.toml  .coveragerc  pdoc.toml
└── README.md
```

---

## 🚀 Installation & Usage

See the **[Installation Guide](./INSTALLATION.md)** for environment setup, building the local
database, running the app, and running tests.

---

## 🧪 Continuous Integration

Every push or pull request to `main` or `development` runs the test suite with coverage
(`.github/workflows/ci.yml`). Pushes to `main` also build the pdoc API documentation and deploy it
to GitHub Pages (`.github/workflows/docs.yml`).

---

## 📚 Documentation

API documentation is generated with **pdoc**. To build it locally, see
[INSTALLATION.md](./INSTALLATION.md#documentation).

---

## 👥 Team

Developed as part of **CSC 510: Software Engineering, NC State University**.

| Member | GitHub Handle | Key Contributions |
|--------|---------------|-------------------|
| Bill Ameen | [@billameen](https://github.com/billameen) | M0 risk evaluation (validator, simulated users, baselines, eval CI); bug-fix sweep on inherited features (#12–#22) and merge regressions (#33); documentation |
| Shaan Chandra | [@rectangle-man](https://github.com/rectangle-man) | M1 constraint-solver planner and rule plug-ins; M3 plain-English plan edits and their evaluation; planner docs and CONTRIBUTING guide |
| Siddhant Joshi | [@sidjoshi29](https://github.com/sidjoshi29) | M2 wallet ledger; M4 fee-aware batching and pickup; license, Code of Conduct and third-party library list; teaser and demo videos |

---

## 🤖 AI Usage

We used **Claude** (Anthropic), in chat and as the Claude Code coding agent, throughout this
project:

- **Writing code**: implementing milestone features, bug fixes and refactors.
- **Writing tests**: drafting and extending pytest tests, including failing tests written before
  a fix.
- **Documentation**: drafting docs, tutorials and this README.
- **Review and debugging**: reviewing changes, finding bugs and explaining errors.

Every AI-generated change was reviewed, tested and committed by a team member, and the team made
all design decisions. Weeklies itself also uses an LLM at runtime, separately from the above: the
v1 planner (`PLANNER=llm`) and the M3 plan-edit parser (see [Plan Edits](#-plan-edits-m3)).

---

## 🤝 Contributing

Please review our [Code of Conduct](CODE_OF_CONDUCT.md) before submitting pull requests. Branch off
`development` and open PRs back into `development`. See [CONTRIBUTING.md](CONTRIBUTING.md), including
how to extend the meal planner safely.

---

## 📜 License

Distributed under the MIT License. See [LICENSE](./LICENSE) for more information. The original
Weeklies copyright is kept, as MIT requires, with our team's line added below it.

Third-party packages and their licenses are listed in
[THIRD_PARTY_LIBRARIES.md](./THIRD_PARTY_LIBRARIES.md). Please follow our
[Code of Conduct](./CODE_OF_CONDUCT.md); reports go to the contact listed there.
