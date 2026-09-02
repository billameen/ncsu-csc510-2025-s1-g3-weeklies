# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Weeklies: a Flask meal-planning/food-delivery web app (CSC 510 course project). All application code
lives under `proj2/`; `proj1/` only contains PDF reports from a prior assignment and is not source code.

## Commands

Run all commands from the repo root unless noted. Activate the venv first (`source .venv/bin/activate` or
create one per `INSTALLATION.md`); dependencies are in `proj2/requirements.txt`.

**Run the dev server** (from `proj2/`, since `FLASK_APP=Flask_app` resolves relative to cwd):
```bash
cd proj2 && flask run
```

**Tests** (pytest config is `pytest.ini` at repo root; `pythonpath = proj2` lets tests `import Flask_app`,
`import sqlQueries`, etc. directly):
```bash
pytest                                          # full suite, stops at first failure (--maxfail=1)
pytest proj2/tests/unit/test_menus.py           # single file
pytest proj2/tests/unit/test_menus.py::test_x -v  # single test
pytest -m unit                                  # by marker: smoke, unit, integration, e2e, llm
pytest --maxfail=100                            # see more than one failure per run
```
Coverage (`--cov=proj2 --cov-branch`, `.coveragerc`) writes `coverage.xml` and enforces `fail_under = 80`.
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
pdoc proj2 --no-show-source --template-dir proj2/pdoc_templates -o proj2/site
python ./scripts/build_docs.py
```

**DB migrations** (manual, ad hoc scripts — no migration framework/Alembic):
```bash
cd proj2
python migrations/add_ticket_table.py    # idempotent
python migrations/add_admin_column.py    # idempotent
```

## Architecture

- **`proj2/Flask_app.py`** (~2200 lines) is a monolith: every route (`/login`, `/register`, `/order`,
  `/orders`, `/restaurants`, `/profile*`, `/admin*`, `/support/submit`, `/insights*`,
  `/orders/<id>/receipt.pdf`, `/generate_plan`, `/db`, etc.) plus a set of module-level helpers
  (`_money`, `_cents_to_dollars`/`_dollars_to_cents`, `_execute_transaction`, `palette_for_item_ids`,
  `fetch_menu_items_by_ids`, `build_calendar_cells`) live in this single file. There are no blueprints.
  It also defines its own `OrderStatus(Enum)` at the top — this is **separate from** `models.OrderStatus`
  (see below); don't conflate the two when touching order-status logic.

- **No ORM.** Despite the tech-stack table in `README.md` mentioning Flask-SQLAlchemy, persistence is raw
  `sqlite3` against `proj2/CSC510_DB.db`, accessed only through `proj2/sqlQueries.py`
  (`create_connection`, `close_connection`, `execute_query`, `fetch_one`, `fetch_all`, plus
  ticket-specific helpers `create_ticket`/`get_tickets_by_user`/`get_all_tickets`/`update_ticket_status`/
  `update_ticket_response`). `docs/architecture.md` explicitly says to use only these helpers for DB access.

- **`proj2/models.py`** currently defines only `OrderStatus`, a validation class for order status strings
  and allowed transitions (`Ordered -> Preparing -> Delivering -> Delivered`, plus shortcuts). It is not
  used by `Flask_app.py`'s own `OrderStatus` enum of the same name.

- **`proj2/menu_generation.py`** (`MenuGenerator` + helpers) builds weekly personalized meal plans: filters
  menu items by allergens, filters restaurants by open hours/weekday, and limits scope before generation.
  Invoked from the `/generate_plan` route.

- **`proj2/llm_toolkit.py`** (`LLM` class) is used by menu generation for plan text. It auto-selects a
  provider at init: OpenAI (`gpt-4o-mini`) if `OPENAI_API_KEY` is set (via `.env`/`load_dotenv`), otherwise
  falls back to a local HuggingFace model with CUDA/MPS acceleration.

- **`proj2/pdf_receipt.py`** (`generate_order_receipt_pdf(db_file, ord_id)`) renders order receipts with
  ReportLab. It has its own private `_money`/`_safe_str`/`_dt_display` helpers, independent from the
  similarly-named helpers in `Flask_app.py`.

- **Schema** has no single source of truth: the live DB is `proj2/CSC510_DB.db`, one-off changes are
  applied via `proj2/migrations/*.py` (idempotent, run manually — see `proj2/migrations/README.md`), and
  tests build a fresh temp SQLite DB from an inline `SCHEMA_SQL` string in `proj2/tests/conftest.py`. When
  changing table shape, all three need to be kept in sync by hand.

- **Templates/static**: server-rendered Jinja2 views in `proj2/templates/`, plain JS/CSS in
  `proj2/static/` (`admin.js`, `script.js`, `style.css`) — no frontend build step.

## Tests

`proj2/tests/` is split into `smoke/`, `unit/`, `integration/`, `e2e/`, `llm/`, matching the markers
declared in `pytest.ini`. `conftest.py` provides:
- `app`/`client`: builds a session-scoped temp SQLite DB from `SCHEMA_SQL` and a Flask test client.
- `seed_minimal_data`: seeds one restaurant, two in-stock menu items, one user (idempotent).
- `login_session` / `admin_session`: log in as the seeded user / an admin user via `POST /login`.
- An autouse fixture monkeypatches `generate_order_receipt_pdf` to return dummy PDF bytes in every test,
  so PDF generation is never exercised for real outside of dedicated pdf tests.
