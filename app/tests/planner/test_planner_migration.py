"""The add_plan_targets migration adds the planner's two User columns, once."""

import sqlite3

import pytest

from migrations.add_plan_targets import migrate

OLD_USER_TABLE = """
CREATE TABLE "User" (
  usr_id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, generated_menu TEXT,
  is_admin INTEGER DEFAULT 0
);
INSERT INTO "User"(email) VALUES ('old@example.test');
"""


@pytest.fixture()
def old_db(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_USER_TABLE)
    conn.close()
    return path


def _columns(path):
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute('PRAGMA table_info("User")')]
    finally:
        conn.close()


def test_migration_adds_both_columns_at_the_end_and_leaves_existing_users_unset(old_db):
    assert migrate(str(old_db)) == ["daily_calorie_target", "weekly_budget_cents"]

    # Appended last, so code that reads User by position (index() uses row[9]) is unaffected.
    assert _columns(old_db)[-2:] == ["daily_calorie_target", "weekly_budget_cents"]
    conn = sqlite3.connect(old_db)
    row = conn.execute('SELECT daily_calorie_target, weekly_budget_cents FROM "User"').fetchone()
    conn.close()
    assert row == (None, None)


def test_migration_is_idempotent(old_db):
    migrate(str(old_db))
    assert migrate(str(old_db)) == []
    assert _columns(old_db).count("weekly_budget_cents") == 1


def test_migration_refuses_a_missing_database_instead_of_creating_one(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(FileNotFoundError):
        migrate(str(missing))
    assert not missing.exists()
