import importlib.util
import sqlite3
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
SEED_SQL = APP / "db" / "seed.sql"


def load_init_db():
    spec = importlib.util.spec_from_file_location("init_db", APP / "scripts" / "init_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_sql_loads_on_sqlite_older_than_3_50():
    """
    unistr() only exists since SQLite 3.50, and CI's Python ships an older SQLite. The sqlite3
    command writes unistr() into .dump output for text with line breaks unless given --newlines.
    """
    assert "unistr(" not in SEED_SQL.read_text(encoding="utf-8"), (
        "app/db/seed.sql uses unistr(), which older SQLite cannot load. Regenerate it with: "
        'sqlite3 app/CSC510_DB.db ".dump --newlines" > app/db/seed.sql'
    )


def test_init_db_keeps_line_breaks_in_text_exactly(tmp_path):
    # The seed's restaurant hours are JSON written with Windows line breaks (\r\n). Reading the
    # file in text mode would quietly turn them into \n.
    db = tmp_path / "seed.db"

    assert load_init_db().init_db(db_file=str(db), seed_file=str(SEED_SQL))

    hours = sqlite3.connect(db).execute("SELECT hours FROM Restaurant WHERE rtr_id = 1").fetchone()
    assert "\r\n" in hours[0]
