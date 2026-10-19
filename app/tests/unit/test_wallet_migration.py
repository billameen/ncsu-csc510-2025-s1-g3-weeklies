"""Tests for migrations/add_wallet_ledger.py: moving User.wallet into the ledger (M2)."""
import os
import sqlite3

import pytest

import ledger
from migrations.add_wallet_ledger import main, migrate

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _db(path, wallets):
    conn = sqlite3.connect(str(path))
    conn.execute('CREATE TABLE "User" (usr_id INTEGER PRIMARY KEY, email TEXT, wallet INTEGER)')
    conn.executemany('INSERT INTO "User" (usr_id, email, wallet) VALUES (?, ?, ?)',
                     [(i, f"u{i}@x.test", w) for i, w in enumerate(wallets, start=1)])
    conn.commit()
    return conn


def _txn_count(conn):
    return conn.execute('SELECT count(*) FROM "LedgerTransaction"').fetchone()[0]


def test_every_old_balance_becomes_an_equal_opening_balance(tmp_path):
    conn = _db(tmp_path / "m.db", [1234, 0, 29, 570000])

    report = migrate(conn)

    assert report.ok
    assert (report.users, report.opened, report.empty) == (4, 3, 1)
    assert report.column_total_cents == report.opening_total_cents == 1234 + 29 + 570000
    assert [ledger.user_balance(conn, u) for u in (1, 2, 3, 4)] == [1234, 0, 29, 570000]
    assert ledger.balance(conn, ledger.OPENING_ACCOUNT) == -(1234 + 29 + 570000)


def test_running_it_twice_changes_nothing(tmp_path):
    conn = _db(tmp_path / "m.db", [500, 700])
    migrate(conn)
    before = _txn_count(conn)

    again = migrate(conn)

    assert again.ok and again.opened == 0 and again.already_open == 2
    assert _txn_count(conn) == before


def test_users_the_app_already_opened_are_only_verified(tmp_path):
    conn = _db(tmp_path / "m.db", [500, 700])
    ledger.ensure_schema(conn)
    ledger.open_legacy_wallet(conn, 1)        # the app touched user 1's wallet first
    ledger.post_transaction(conn, "topup", [("user:1", 300), ("external:topup", -300)], "t1")

    report = migrate(conn)

    assert report.ok and report.opened == 1 and report.already_open == 1
    assert ledger.user_balance(conn, 1) == 800   # later activity is kept, opening still matches


def test_a_column_changed_after_migration_is_reported(tmp_path):
    conn = _db(tmp_path / "m.db", [500, 700])
    migrate(conn)
    conn.execute('UPDATE "User" SET wallet = 999 WHERE usr_id = 2')
    conn.commit()

    report = migrate(conn)

    assert not report.ok
    assert report.mismatches == [(2, 999, 700)]


@pytest.mark.parametrize("bad", [-5, 12.5])
def test_invalid_old_values_are_reported_and_others_still_migrate(tmp_path, bad):
    conn = _db(tmp_path / "m.db", [500, bad, 300])

    report = migrate(conn)

    assert not report.ok
    assert [u for u, _ in report.errors] == [2]
    assert ledger.user_balance(conn, 1) == 500 and ledger.user_balance(conn, 3) == 300


def test_check_mode_writes_nothing(tmp_path):
    path = tmp_path / "m.db"
    conn = _db(path, [500])
    ledger.ensure_schema(conn)
    conn.close()

    assert main(["--check", str(path)]) == 1          # nothing opened yet -> mismatch
    conn = sqlite3.connect(str(path))
    assert _txn_count(conn) == 0
    conn.close()

    assert main([str(path)]) == 0
    assert main(["--check", str(path)]) == 0


def test_check_mode_needs_the_tables_and_a_missing_db_is_an_error(tmp_path, capsys):
    path = tmp_path / "m.db"
    _db(path, [500]).close()
    assert main(["--check", str(path)]) == 1
    assert main([str(tmp_path / "missing.db")]) == 1


def test_init_db_builds_the_seed_with_a_balanced_ledger(tmp_path):
    from scripts.init_db import init_db

    path = tmp_path / "seeded.db"
    assert init_db(db_file=str(path)) is True

    conn = sqlite3.connect(str(path))
    try:
        report = migrate(conn, write=False)
        column_total = conn.execute('SELECT SUM(wallet) FROM "User"').fetchone()[0]
    finally:
        conn.close()
    assert report.ok
    assert report.opening_total_cents == column_total
    assert report.users > 0 and report.opened == 0     # init_db already did it
