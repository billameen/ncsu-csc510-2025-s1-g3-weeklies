"""The add_plan_targets migration adds the planner's two User columns, once."""

import sqlite3

import pytest

from migrations.add_plan_targets import MigrationOrderError, migrate

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


def test_migration_refuses_to_run_before_the_admin_column_exists(tmp_path):
    """Login reads is_admin as User column 10; our columns must not take that position."""
    path = tmp_path / "pre_admin.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        'CREATE TABLE "User" (usr_id INTEGER PRIMARY KEY, a, b, c, d, e, f, g, h, generated_menu);'
    )
    conn.close()

    with pytest.raises(MigrationOrderError, match="add_admin_column.py first"):
        migrate(str(path))
    assert "daily_calorie_target" not in _columns(path)


def test_after_both_migrations_in_order_login_does_not_grant_admin(client, temp_db_path):
    """With is_admin at index 10, a user who sets a calorie target is still not an admin."""
    from werkzeug.security import generate_password_hash

    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        """INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,
                              is_admin,daily_calorie_target,weekly_budget_cents)
           VALUES ('Not','Admin','not-admin@example.test','1',?,0,0,2000,15000)""",
        (generate_password_hash("pw"),),
    )
    conn.commit()
    conn.close()
    client.post("/login", data={"email": "not-admin@example.test", "password": "pw"})
    with client.session_transaction() as sess:
        assert sess["is_admin"] is False


def test_plan_edit_migration_creates_the_table_once(old_db):
    from migrations.add_plan_edit_table import migrate as migrate_edits

    assert migrate_edits(str(old_db)) is True
    assert migrate_edits(str(old_db)) is False
    conn = sqlite3.connect(old_db)
    cols = [r[1] for r in conn.execute('PRAGMA table_info("PlanEdit")')]
    conn.close()
    assert cols == ["edit_id", "usr_id", "request", "status", "detail", "created_at"]
