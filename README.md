# 🍽️ WEEKLIES — Intelligent Meal Planning and Delivery System
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

---

## 🧠 Project Overview

**Weeklies** is a full-stack Flask web application for planning and ordering a week of meals.
Users register, set dietary preferences and allergies, browse restaurants and menus, and schedule
orders on a calendar, with an LLM-generated weekly meal plan tailored to them.

This repository is our team's continuation of Weeklies for *CSC 510: Software Engineering
(NC State University)*. We are extending the existing application with a new set of milestones
(see [Roadmap](#️-roadmap)), while keeping the codebase tested, documented, and continuously integrated.

> **Built on Weeklies (Fall 2025).** This project starts from the
> [Weeklies codebase](https://github.com/Aum3010/ncsu-csc510-2025-s1-g3-weeklies) by Aum Pandya,
> Pranav Bhagwat, and Tayo Olukotun, which itself extended earlier work by Section 001 Group 9
> (Taylor J. Brown, Kunal Jindal, Ashritha Bugada, Daniel Dong). Thank you to both teams.

---

## 🗺️ Roadmap

<!-- TODO: replace with our milestones once finalized -->
| # | Milestone | Status |
|---|-----------|--------|
| 1 | _TBD_ | ⏳ Planned |
| 2 | _TBD_ | ⏳ Planned |
| 3 | _TBD_ | ⏳ Planned |
| 4 | _TBD_ | ⏳ Planned |

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
| **LLM** | OpenAI API (`gpt-4o-mini`) or local HuggingFace model |
| **PDF** | ReportLab |
| **Tooling** | GitHub Actions, pytest, pytest-cov, ruff, black, pdoc |

---

## 🧱 Repository Layout

```
.
├── app/
│   ├── Flask_app.py          # all routes and helpers
│   ├── sqlQueries.py         # DB access helpers
│   ├── menu_generation.py    # weekly meal-plan generation
│   ├── llm_toolkit.py        # LLM provider wrapper
│   ├── pdf_receipt.py        # receipt PDFs
│   ├── models.py
│   ├── templates/  static/
│   ├── db/seed.sql           # schema + demo data (source of truth for the local DB)
│   ├── scripts/init_db.py    # builds app/CSC510_DB.db from db/seed.sql
│   ├── migrations/           # one-off, idempotent schema changes
│   ├── tests/                # smoke / unit / integration / e2e / llm
│   └── requirements.txt
├── .github/workflows/        # ci.yml (tests), docs.yml (pdoc → GitHub Pages)
├── scripts/build_docs.py
├── INSTALLATION.md
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

<!-- TODO: fill in team members -->
| Member | GitHub Handle | Key Contributions |
|--------|---------------|-------------------|
| _TBD_ | [@billameen](https://github.com/billameen) | _TBD_ |

---

## 🤝 Contributing

Please review our [Code of Conduct](CODE_OF_CONDUCT.md) before submitting pull requests. Branch off
`development` and open PRs back into `development`. See [CONTRIBUTING.md](CONTRIBUTING.md), including
how to extend the meal planner safely.

---

## 📜 License

Distributed under the MIT License. See [LICENSE](./LICENSE) for more information.
