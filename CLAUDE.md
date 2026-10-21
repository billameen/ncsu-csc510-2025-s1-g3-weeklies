# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Weeklies: a Flask meal-planning/food-delivery web app (CSC 510 course project). All application code
lives under `app/` (renamed from last semester's `proj2/`).

## Commands

Run all commands from the repo root unless noted. Activate the venv first (`source .venv/bin/activate` or
create one per `INSTALLATION.md`); dependencies are in `app/requirements.txt`.

**Run the dev server** (from `app/`, since `FLASK_APP=Flask_app` resolves relative to cwd):
```bash
cd app && flask run
```

**Tests** (pytest config is `pytest.ini` at repo root; `pythonpath = app` lets tests `import Flask_app`,
`import sqlQueries`, etc. directly):
```bash
pytest                                          # full suite, stops at first failure (--maxfail=1)
pytest app/tests/unit/test_menus.py           # single file
pytest app/tests/unit/test_menus.py::test_x -v  # single test
pytest -m unit                                  # by marker: smoke, unit, integration, e2e, llm
pytest --maxfail=100                            # see more than one failure per run
```
Coverage (`--cov=app --cov-branch`, `.coveragerc`) writes `coverage.xml` and enforces `fail_under = 80`.
`e2e` tests are Playwright-based and expect a live server at `http://127.0.0.1:5000` (`base_url` fixture in
`conftest.py`) — start `flask run` in another terminal first.

**Lint / format** (configured in `pyproject.toml`, line-length 100, target py311):
```bash
black .          # format
black --check .  # verify formatting (CI runs this)
ruff check .     # lint (CI runs `ruff check . --fix || true`, i.e. non-blocking)
```

**Docs** (pdoc, deployed to GitHub Pages by `.github/workflows/docs.yml` on push to `main`):
```bash
export PYTHONPATH="."
pdoc app --no-show-source --template-dir app/pdoc_templates -o app/site
python ./scripts/build_docs.py
```

**Local DB**: `app/CSC510_DB.db` is gitignored; `app/db/seed.sql` (a `sqlite3 .dump`) is the tracked
source of truth. Build/reset it with `python app/scripts/init_db.py [--force]`; after changing schema or
demo data, refresh the seed with `sqlite3 app/CSC510_DB.db ".dump --newlines" > app/db/seed.sql`
(`--newlines` keeps sqlite3 3.50+ from writing `unistr()`, which CI's older SQLite cannot load).

**DB migrations** (manual, ad hoc, idempotent scripts — no migration framework/Alembic; run in
this order, see `app/migrations/README.md`):
```bash
cd app
python migrations/add_ticket_table.py
python migrations/add_admin_column.py     # must run before add_plan_targets.py
python migrations/add_plan_targets.py
python migrations/add_wallet_ledger.py    # --check verifies without writing
python migrations/add_plan_edit_table.py
python migrations/add_restaurant_fees.py
```

**Evaluation** (from repo root, no API key): `python -m eval.run --seed 510` (M0/M1, ~3 min),
`python -m eval.edits` (M3 plan edits), `python -m eval.m4 --seed 510` (M4 fees, ~10 min).

## Architecture

- **`app/Flask_app.py`** (~2200 lines) is a monolith: every route (`/login`, `/register`, `/order`,
  `/orders`, `/restaurants`, `/profile*`, `/admin*`, `/support/submit`, `/insights*`,
  `/orders/<id>/receipt.pdf`, `/generate_plan`, `/db`, etc.) plus a set of module-level helpers
  (`_money`, `_cents_to_dollars`/`_dollars_to_cents`, `_execute_transaction`, `palette_for_item_ids`,
  `fetch_menu_items_by_ids`, `build_calendar_cells`) live in this single file. There are no blueprints.
  It also defines its own `OrderStatus(Enum)` at the top — this is **separate from** `models.OrderStatus`
  (see below); don't conflate the two when touching order-status logic.

- **No ORM.** Despite the tech-stack table in `README.md` mentioning Flask-SQLAlchemy, persistence is raw
  `sqlite3` against `app/CSC510_DB.db`, accessed only through `app/sqlQueries.py`
  (`create_connection`, `close_connection`, `execute_query`, `fetch_one`, `fetch_all`, plus
  ticket-specific helpers `create_ticket`/`get_tickets_by_user`/`get_all_tickets`/`update_ticket_status`/
  `update_ticket_response`). `docs/architecture.md` explicitly says to use only these helpers for DB access.

- **`app/models.py`** currently defines only `OrderStatus`, a validation class for order status strings
  and allowed transitions (`Ordered -> Preparing -> Delivering -> Delivered`, plus shortcuts). It is not
  used by `Flask_app.py`'s own `OrderStatus` enum of the same name.

- **`app/planner/`** plans the week with an OR-Tools CP-SAT solver: `/generate_plan` calls
  `planner.solver.plan_week`. Every requirement is a `Constraint` plug-in in `planner/rules/`
  (hard or soft, with an `explain()` for infeasible weeks); see `app/docs/planner-rules.md`.
  `planner/edits/` turns plain-English plan edits into rule plug-ins (guard, LLM or regex parser,
  versioned prompts in `planner/prompts/`) and re-plans only affected meals (`/plan/edit`).
  `planner/fees.py` holds per-restaurant fees, charged per order by the `fee_cost` rule.

- **`app/menu_generation.py`** (`MenuGenerator` + helpers) is the v1 LLM planner, used only when
  `PLANNER=llm`; the evaluation keeps it as baseline B2, so don't remove or change it.

- **`app/ledger.py`** is the M2 double-entry wallet ledger: every money movement is a transaction
  whose entries sum to zero; balances are sums of entries; rows are append-only (DB triggers).
  **`app/money.py`** parses/formats integer cents — money is never a float.
  **`app/fee_prefs.py`** stores each user's batching/pickup settings (`UserFeePrefs`).

- **`app/llm_toolkit.py`** (`LLM` class) is used by the v1 planner and the plan-edit parser. It auto-selects a
  provider at init: OpenAI (`gpt-4o-mini`) if `OPENAI_API_KEY` is set (via `.env`/`load_dotenv`), otherwise
  falls back to a local HuggingFace model with CUDA/MPS acceleration.

- **`app/pdf_receipt.py`** (`generate_order_receipt_pdf(db_file, ord_id)`) renders order receipts with
  ReportLab. It has its own private `_money`/`_safe_str`/`_dt_display` helpers, independent from the
  similarly-named helpers in `Flask_app.py`.

- **Schema** has no single source of truth: the live DB is `app/CSC510_DB.db` (built from `app/db/seed.sql`), one-off changes are
  applied via `app/migrations/*.py` (idempotent, run manually — see `app/migrations/README.md`), and
  tests build a fresh temp SQLite DB from an inline `SCHEMA_SQL` string in `app/tests/conftest.py`. When
  changing table shape, all three need to be kept in sync by hand.

- **Templates/static**: server-rendered Jinja2 views in `app/templates/`, plain JS/CSS in
  `app/static/` (`admin.js`, `script.js`, `style.css`) — no frontend build step.

## Tests

`app/tests/` is split into `smoke/`, `unit/`, `integration/`, `e2e/`, `llm/` (matching the markers
declared in `pytest.ini`), plus `planner/` (one file per rule) and `eval/`. `conftest.py` provides:
- `app`/`client`: builds a session-scoped temp SQLite DB from `SCHEMA_SQL` and a Flask test client.
- `seed_minimal_data`: seeds one restaurant, two in-stock menu items, one user (idempotent).
- `login_session` / `admin_session`: log in as the seeded user / an admin user via `POST /login`.
- An autouse fixture monkeypatches `generate_order_receipt_pdf` to return dummy PDF bytes in every test,
  so PDF generation is never exercised for real outside of dedicated pdf tests.
