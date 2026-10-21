import sqlite3

import pytest

import Flask_app


@pytest.mark.parametrize(
    "raw,cents",
    [("12.50", 1250), ("0.29", 29), (" 3 ", 300), ("1.005", 101), ("0.004", 0), ("-5", -500), (7, 700)],
)
def test_parse_amount_cents_rounds_half_up_to_exact_cents(raw, cents):
    assert Flask_app._parse_amount_cents(raw) == cents


@pytest.mark.parametrize("raw", ["", "abc", "nan", "NaN", "inf", "-Infinity", "1e999", None])
def test_parse_amount_cents_raises_on_non_finite_or_non_numeric(raw):
    with pytest.raises(ValueError):
        Flask_app._parse_amount_cents(raw)


def test_dollars_to_cents_rounds_instead_of_truncating():
    # 0.29 * 100 == 28.999999999999996 in binary floating point
    assert Flask_app._dollars_to_cents(0.29) == 29
    assert all(Flask_app._dollars_to_cents(c / 100) == c for c in range(1, 20001))


def _wallet_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE w (id INTEGER PRIMARY KEY, bal INTEGER)")
    conn.execute("INSERT INTO w VALUES (1, 100)")
    conn.commit()
    return conn


def test_execute_transaction_rolls_back_when_expected_rowcount_is_not_met():
    conn = _wallet_db()
    ok = Flask_app._execute_transaction(conn, [
        ("UPDATE w SET bal = bal + 1 WHERE id = 1", ()),
        ("UPDATE w SET bal = bal - ? WHERE id = 1 AND bal >= ?", (500, 500), 1),
    ])
    assert ok is False
    assert conn.execute("SELECT bal FROM w WHERE id = 1").fetchone()[0] == 100


def test_execute_transaction_commits_when_expected_rowcount_is_met():
    conn = _wallet_db()
    ok = Flask_app._execute_transaction(conn, [
        ("UPDATE w SET bal = bal - ? WHERE id = 1 AND bal >= ?", (50, 50), 1),
    ])
    assert ok is True
    assert conn.execute("SELECT bal FROM w WHERE id = 1").fetchone()[0] == 50
