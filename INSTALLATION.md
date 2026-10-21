# ⚙️ Installation Guide

> Tested on **Python 3.11+** (recommended: 3.12).  
> Follow the steps below to set up, run, and document the project on any OS.

---

## 🧩 Setup

### 🪟 Windows (PowerShell)
```powershell
# 1️⃣ Clone the repository
git clone https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies.git
cd ncsu-csc510-2025-s1-g3-weeklies

# 2️⃣ Create and activate a virtual environment
py -3 -m venv .venv
. .\.venv\Scripts\Activate.ps1
# If activation is blocked:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3️⃣ Install dependencies
python -m pip install --upgrade pip
pip install -r app/requirements.txt

# 4️⃣ Build the local database from app/db/seed.sql
python app/scripts/init_db.py
```

### 🐧MacOS / Linux (Bash/Zsh)
```bash
# 1️⃣ Clone the repository
git clone https://github.com/billameen/ncsu-csc510-2025-s1-g3-weeklies.git
cd ncsu-csc510-2025-s1-g3-weeklies

# 2️⃣ Create & activate a venv
python3 -m venv .venv
source .venv/bin/activate

# 3️⃣ Install packages
python -m pip install --upgrade pip
pip install -r app/requirements.txt

# 4️⃣ Build the local database from app/db/seed.sql
python app/scripts/init_db.py
```

---

### Already have a local database?

`app/CSC510_DB.db` is not rebuilt automatically. After pulling schema changes, either reset it
to the seed data:

```bash
python app/scripts/init_db.py --force             # reset to app/db/seed.sql
```

or keep your data and run the migrations, in this order (each one is idempotent, so running one
that is already applied does nothing):

```bash
cd app
python migrations/add_ticket_table.py
python migrations/add_admin_column.py      # before add_plan_targets.py
python migrations/add_plan_targets.py
python migrations/add_wallet_ledger.py     # moves old wallet balances into the M2 ledger
python migrations/add_plan_edit_table.py
python migrations/add_restaurant_fees.py
cd ..
```

See [app/migrations/README.md](app/migrations/README.md) for what each one changes.

---

## 🚀Usage

### Running the Application
Once dependencies are installed and the virtual environment is activated, you can run the Flask server:

### 🪟Windows (PowerShell)
```powershell
# Start the development server (from app/, where .flaskenv lives)
cd app
flask run
```

### 🐧MacOS / Linux (Bash/Zsh)
```bash
# Start the development server (from app/, where .flaskenv lives)
cd app
flask run
```

### Planning a week

Set a **daily calorie target** and **weekly budget** on *Profile → Edit Profile*, then press
**Auto-Plan Week** on the calendar. The constraint solver plans the next 7 days within both
and never picks an item with one of your allergens; if no week fits, it says why. To use the
v1 LLM planner instead, start the server with `PLANNER=llm` (it needs `OPENAI_API_KEY` or a
local model).

### Changing your week in plain English

Once a week is planned, type a change into **Change your week** on the calendar, such as
"make Thursday vegetarian under $10", "keep each day under $40", "pizza on Friday night" or
"cheaper lunches if possible", and press **Preview**. You
see exactly which meals would change and what the week would cost; nothing is saved until you
press **Accept**. Allergies and the budget can't be loosened this way; change them on your
profile.

The edit box uses the app's LLM (`OPENAI_API_KEY`, or the local model, which loads on the
first edit and can take a while). To run it without any model, start the server with
`EDIT_PARSER=regex`.

The default local model is small and parses many requests wrongly (never unsafely). For
better edits without an API key, set a larger local model for the edit box, for example
`EDIT_LLM_MODEL=ibm-granite/granite-4.0-micro` (3B, about 6.5 GB of GPU memory in half
precision; `ibm-granite/granite-4.0-1b` needs about half that). It is downloaded on first
use.

### Delivery fees, batching and pickup

Every order pays the restaurant's delivery fee and a service fee, and the planner counts them
toward your weekly budget. On *Profile → Delivery & Fees* you can turn on **batching**, so meals
from the same restaurant on the same day, at most 6 hours apart, share one delivery, and pick
**pickup** days and restaurants, where the delivery fee is skipped (pickup needs at least one of
each). Both are off by default. The calendar shows the month's fees and how much batching saved;
the fees are a synthetic model, not real prices.

### Wallet

Top up or gift wallet balance on your profile; *Wallet History* below it lists every top-up,
gift, order and refund. Admins see a ledger check (every transaction balances, no wallet is
negative) at the top of the admin dashboard and can refund an order from its card.

> [!NOTE]
> If you have downloaded the repo locally and you're running into issues with
> `app.` errors when trying to run `Flask_app.py`, simply remove `app.`
> that is in front of any of the imports and try to run the application again.

---

## 🧪Running Tests
Execute unit tests using pytest:
```bash
# For full information run:
pytest
# Add a '-q'(quiet) flag to show concise, easy-to-read output (dots for passes, 'F' for failures):
pytest -q
```

---

## 📚Documentation

### _Documentation is generated using pdoc._
Documentation is automatically generated using pdoc and deployed to GitHub Pages whenever new changes are merged into the `main` branch.

### 🧩 Automated Docs
* CI/CD workflow (`docs.yml`) builds and publishes docs from `app/` to the `gh-pages` branch.

* Live documentation becomes available at the GitHub Pages link after each successful merge.

* Source code is hidden; only public functions, classes, and docstrings are shown.

### 🖥️ Build Docs Locally
You can also generate and preview the documentation manually:
### 🪟Windows (PowerShell)
```powershell
# Temporarily add current directory to Python path
$env:PYTHONPATH="." ;
pdoc app --no-show-source --template-dir app\pdoc_templates -o app\site
python .\scripts\build_docs.py
# View the documentation in your default browser
start app\site\index.html
```

### 🐧MacOS / Linux (Bash/Zsh)
```bash
# Temporarily add current directory to Python path
export PYTHONPATH="."
pdoc app --no-show-source --template-dir app/pdoc_templates -o app/site
python ./scripts/build_docs.py
# View the documentation in your default browser
open app/site/index.html
```

The generated HTML files will be available in the `app/site` directory.
