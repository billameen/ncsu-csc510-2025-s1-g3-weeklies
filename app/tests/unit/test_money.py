"""Tests for ``money.py`` (M2: integer-cent money, bug 1 float truncation).

Property-based tests use Hypothesis; the exhaustive sweep covers every cent
amount from $0.00 to $1,000.00, the range where the old float helper was off
by one cent on 4,586 values.
"""
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st
from werkzeug.security import generate_password_hash

import Flask_app
from money import (
    MAX_CENTS,
    AmountOutOfRange,
    InvalidAmount,
    MoneyError,
    cents_to_str,
    format_cents,
    parse_cents,
)
from sqlQueries import close_connection, create_connection, execute_query, fetch_one
import ledger

cent_amounts = st.integers(min_value=-MAX_CENTS, max_value=MAX_CENTS)


# --- Properties --------------------------------------------------------------

@given(cent_amounts)
def test_parse_inverts_cents_to_str_for_every_cent_amount(cents):
    assert parse_cents(cents_to_str(cents)) == cents


@given(cent_amounts)
def test_parse_inverts_display_format_once_separators_are_removed(cents):
    assert parse_cents(format_cents(cents).replace(",", "")) == cents


@given(cent_amounts)
def test_legacy_float_totals_convert_to_the_intended_cent(cents):
    # Order totals are still computed as floats until the ledger lands; the
    # nearest float to c/100 must still map back to c.
    assert parse_cents(cents / 100) == cents


@given(st.decimals(min_value=Decimal("-10000"), max_value=Decimal("10000"),
                   allow_nan=False, allow_infinity=False, places=3))
def test_three_decimal_amounts_round_half_up(amount):
    scaled = amount * 1000  # exact integer number of tenths of a cent
    whole, tenth = divmod(abs(int(scaled)), 10)
    expected = whole + (1 if tenth >= 5 else 0)
    assert parse_cents(str(amount)) == (-expected if scaled < 0 else expected)


@given(cent_amounts)
def test_parse_always_returns_an_int(cents):
    assert type(parse_cents(cents_to_str(cents))) is int


def test_every_cent_amount_up_to_1000_dollars_is_exact():
    wrong = [c for c in range(100_001) if parse_cents(f"{c // 100}.{c % 100:02d}") != c]
    assert wrong == []


# --- Regression: bug 1 -------------------------------------------------------

def test_29_cents_parses_to_29_not_28():
    assert parse_cents("0.29") == 29
    assert Flask_app._dollars_to_cents("0.29") == 29
    assert Flask_app._dollars_to_cents(0.29) == 29


# --- Edge cases --------------------------------------------------------------

@pytest.mark.parametrize("text,cents", [
    ("0", 0), ("0.00", 0), ("12", 1200), ("12.3", 1230), ("12.34", 1234),
    ("  7.10 ", 710), ("$5.25", 525), ("-$5.25", -525), ("-1.50", -150),
    ("1.005", 101), ("1.004", 100), ("0.005", 1), ("2.675", 268),
])
def test_parse_known_values(text, cents):
    assert parse_cents(text) == cents


@pytest.mark.parametrize("bad", [
    None, "", "   ", "abc", "1.2.3", "12abc", "$", "--5", "+-5", "NaN", "nan",
    "Infinity", "-inf", True, False, float("nan"), float("inf"),
    "1e5", "1E+2", "1_000", "\u0661\u0662", "9" * 33, "9" * 5_000_000, "0x10", "1 000",
])
def test_non_numeric_input_is_rejected(bad):
    with pytest.raises(InvalidAmount):
        parse_cents(bad)


@pytest.mark.parametrize("huge", ["1000000.01", "-1000000.01", "9" * 30, 10**12,
                                  Decimal("1e999999"), Decimal("-9e999999")])
def test_huge_amounts_are_rejected(huge):
    with pytest.raises(AmountOutOfRange):
        parse_cents(huge)


def test_limit_itself_is_accepted():
    assert parse_cents("1000000.00") == MAX_CENTS


def test_money_errors_are_value_errors():
    assert issubclass(InvalidAmount, MoneyError) and issubclass(MoneyError, ValueError)


def test_dollars_to_cents_keeps_its_zero_on_failure_contract():
    assert Flask_app._dollars_to_cents("abc") == 0
    assert Flask_app._dollars_to_cents(None) == 0


@pytest.mark.parametrize("cents,shown", [
    (0, "$0.00"), (5, "$0.05"), (123456, "$1,234.56"), (-100, "-$1.00"),
])
def test_format_cents(cents, shown):
    assert format_cents(cents) == shown


def test_money_module_never_uses_float():
    import inspect
    import money
    assert "float(" not in inspect.getsource(money)


# --- Route-level regressions -------------------------------------------------

PASSWORD = "secret123"


def _make_user(db, email, wallet_cents):
    conn = create_connection(db)
    try:
        execute_query(
            conn,
            '''INSERT INTO "User"(first_name,last_name,email,phone,password_HS,wallet,preferences,allergies)
               VALUES ("Money","Tester",?,"9195550600",?,?,"","")''',
            (email, generate_password_hash(PASSWORD), wallet_cents),
        )
        return fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))[0]
    finally:
        close_connection(conn)


def _wallet(db, usr_id):
    conn = create_connection(db)
    try:
        return ledger.wallet_balance(conn, usr_id)
    finally:
        close_connection(conn)


def test_a_29_cent_gift_moves_exactly_29_cents(client, temp_db_path):
    sender = _make_user(temp_db_path, "money-sender@example.test", 1000)
    recipient = _make_user(temp_db_path, "money-recipient@example.test", 0)
    client.post("/login", data={"email": "money-sender@example.test", "password": PASSWORD})

    resp = client.post("/profile/wallet/gift", data={
        "recipient_email": "money-recipient@example.test", "amount": "0.29"})

    assert resp.headers["Location"] == "/profile?wallet_updated=gift"
    assert _wallet(temp_db_path, sender) == 971
    assert _wallet(temp_db_path, recipient) == 29


@pytest.mark.parametrize("amount,error", [
    ("abc", "invalid_amount"), ("", "invalid_amount"), ("1e300", "invalid_amount"),
    ("9" * 100_000, "invalid_amount"), ("5000000", "invalid_amount"),
    ("0", "zero_amount"), ("-5", "zero_amount"),
])
def test_top_up_rejects_bad_amounts_without_touching_the_wallet(client, temp_db_path, amount, error):
    email = f"money-topup-{abs(hash(amount))}@example.test"
    usr = _make_user(temp_db_path, email, 300)
    client.post("/login", data={"email": email, "password": PASSWORD})

    resp = client.post("/profile/wallet/topup", data={"amount": amount})

    assert resp.headers["Location"] == f"/profile?wallet_error={error}"
    assert _wallet(temp_db_path, usr) == 300
