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
