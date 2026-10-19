"""Tests for the double-entry wallet ledger (``ledger.py``, M2)."""
import sqlite3
import threading

import pytest
from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

import ledger
from ledger import (
    AlreadyReversed,
    IdempotencyConflict,
    InsufficientFunds,
    InvalidTransaction,
    LedgerError,
    UnbalancedTransaction,
    check_ledger,
    post_transaction,
    reverse_transaction,
    user_balance,
)


def _connect(path):
    conn = sqlite3.connect(str(path), timeout=30)
    ledger.ensure_schema(conn)
    return conn


@pytest.fixture()
def conn(tmp_path):
    c = _connect(tmp_path / "ledger.db")
    yield c
    c.close()


def topup(conn, usr_id, cents, key):
    return post_transaction(conn, "topup", [(f"user:{usr_id}", cents), ("external:topup", -cents)], key)


def gift(conn, from_id, to_id, cents, key):
    return post_transaction(conn, "gift", [(f"user:{from_id}", -cents), (f"user:{to_id}", cents)], key)


def _count(conn, table):
    return conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]


# --- Schema -------------------------------------------------------------------

def test_ensure_schema_is_idempotent(conn):
    ledger.ensure_schema(conn)
    ledger.ensure_schema(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"LedgerTransaction", "LedgerEntry"} <= names


# --- Posting ------------------------------------------------------------------

def test_top_up_credits_the_user_and_keeps_the_ledger_balanced(conn):
    result = topup(conn, 1, 1234, "t1")

    assert result.created is True
    assert user_balance(conn, 1) == 1234
    assert ledger.balance(conn, "external:topup") == -1234
    assert check_ledger(conn).ok


def test_gift_moves_money_between_users(conn):
    topup(conn, 1, 1000, "t1")
    gift(conn, 1, 2, 300, "g1")

    assert (user_balance(conn, 1), user_balance(conn, 2)) == (700, 300)
    assert check_ledger(conn).ok


def test_spending_down_to_exactly_zero_is_allowed(conn):
    topup(conn, 1, 500, "t1")
    gift(conn, 1, 2, 500, "g1")
    assert user_balance(conn, 1) == 0


def test_overdraft_is_refused_and_writes_nothing(conn):
    topup(conn, 1, 500, "t1")
    before = (_count(conn, "LedgerTransaction"), _count(conn, "LedgerEntry"))

    with pytest.raises(InsufficientFunds) as exc:
        gift(conn, 1, 2, 501, "g1")

    assert exc.value.account == "user:1" and exc.value.balance_cents == -1
    assert (_count(conn, "LedgerTransaction"), _count(conn, "LedgerEntry")) == before
    assert user_balance(conn, 1) == 500


def test_non_user_accounts_may_go_negative(conn):
    # external:topup is where top-up money comes from, so it is always negative.
    topup(conn, 1, 100, "t1")
    assert ledger.balance(conn, "external:topup") == -100


def test_order_split_across_restaurant_fees_and_tax(conn):
    topup(conn, 7, 5000, "t1")
    post_transaction(conn, "order", [
        ("user:7", -2893), ("restaurant:3", 2200), ("tax", 145),
        ("fees:delivery", 399), ("fees:service", 149),
    ], "o1")

    assert user_balance(conn, 7) == 5000 - 2893
    assert ledger.balance(conn, "restaurant:3") == 2200
    assert check_ledger(conn).ok


# --- Validation ---------------------------------------------------------------

@pytest.mark.parametrize("entries", [
    [("user:1", 100), ("external:topup", -99)],
    [("user:1", 100), ("user:2", 100)],
])
def test_unbalanced_entries_are_refused(conn, entries):
    with pytest.raises(UnbalancedTransaction):
        post_transaction(conn, "topup", entries, "k")
    assert _count(conn, "LedgerTransaction") == 0


@pytest.mark.parametrize("entries", [
    [("user:1", 1.0), ("external:topup", -1.0)],      # float
    [("user:1", True), ("external:topup", -1)],       # bool is not money
    [("user:1", 0), ("external:topup", 0)],           # zero amounts
    [("user:1", 0)],                                  # one entry
    [],                                               # nothing
    [("user:0", 5), ("external:topup", -5)],          # bad user id
    [("wallet", 5), ("external:topup", -5)],          # unknown account type
    [("user:1", 5), ("external:topup", -5, "x")],     # malformed entry
    [("user:1", 5), ("user:1", -5)],                  # nets to nothing
])
def test_malformed_entries_are_refused(conn, entries):
    with pytest.raises(InvalidTransaction):
        post_transaction(conn, "topup", entries, "k")
    assert _count(conn, "LedgerTransaction") == 0


@pytest.mark.parametrize("key", ["", "   ", None, 42, "k" * 129])
def test_bad_idempotency_keys_are_refused(conn, key):
    with pytest.raises(InvalidTransaction):
        topup(conn, 1, 100, key)


@pytest.mark.parametrize("kind", ["", "Top Up", "topup;", None])
def test_bad_kinds_are_refused(conn, kind):
    with pytest.raises(InvalidTransaction):
        post_transaction(conn, kind, [("user:1", 1), ("external:topup", -1)], "k")


def test_duplicate_accounts_are_merged(conn):
    topup(conn, 1, 1000, "t1")
    post_transaction(conn, "gift", [("user:1", -300), ("user:2", 100), ("user:2", 200)], "g1")
    rows = conn.execute('SELECT account, amount_cents FROM "LedgerEntry" WHERE txn_id = 2 '
                        'ORDER BY account').fetchall()
    assert rows == [("user:1", -300), ("user:2", 300)]


def test_refuses_to_run_inside_a_callers_open_transaction(conn):
    conn.execute('INSERT INTO "LedgerTransaction"(kind, idempotency_key, created_at) '
                 "VALUES ('x', 'open', 'now')")
    assert conn.in_transaction
    with pytest.raises(LedgerError):
        topup(conn, 1, 100, "t1")
    conn.rollback()


# --- Idempotency --------------------------------------------------------------

def test_repeating_a_request_with_the_same_key_changes_nothing(conn):
    first = topup(conn, 1, 500, "click-1")
    second = topup(conn, 1, 500, "click-1")

    assert second.created is False and second.txn_id == first.txn_id
    assert user_balance(conn, 1) == 500
    assert _count(conn, "LedgerTransaction") == 1


def test_reusing_a_key_for_a_different_transaction_is_an_error(conn):
    topup(conn, 1, 500, "click-1")
    with pytest.raises(IdempotencyConflict):
        topup(conn, 1, 600, "click-1")
    with pytest.raises(IdempotencyConflict):
        post_transaction(conn, "refund", [("user:1", 500), ("external:topup", -500)], "click-1")
    assert user_balance(conn, 1) == 500


# --- The `after` hook ---------------------------------------------------------

def test_after_hook_runs_in_the_same_transaction(conn):
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, txn_id INTEGER)")
    topup(conn, 1, 1000, "t1")

    def save_order(cur, txn_id):
        cur.execute("INSERT INTO orders (txn_id) VALUES (?)", (txn_id,))
        return cur.lastrowid

    result = post_transaction(conn, "order", [("user:1", -400), ("restaurant:1", 400)], "o1",
                              after=save_order)

    assert result.extra == 1
    assert conn.execute("SELECT txn_id FROM orders").fetchall() == [(result.txn_id,)]


def test_overdraft_cancels_the_after_hook_too(conn):
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, txn_id INTEGER)")
    calls = []
    with pytest.raises(InsufficientFunds):
        post_transaction(conn, "order", [("user:1", -400), ("restaurant:1", 400)], "o1",
                         after=lambda cur, txn_id: calls.append(txn_id))
    assert calls == []
    assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0


def test_a_failing_after_hook_rolls_back_the_payment(conn):
    topup(conn, 1, 1000, "t1")

    def boom(cur, txn_id):
        raise RuntimeError("order insert failed")

    with pytest.raises(RuntimeError):
        post_transaction(conn, "order", [("user:1", -400), ("restaurant:1", 400)], "o1", after=boom)
    assert user_balance(conn, 1) == 1000
    assert _count(conn, "LedgerTransaction") == 1


# --- Append-only --------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    'UPDATE "LedgerEntry" SET amount_cents = 999999',
    'DELETE FROM "LedgerEntry"',
    'UPDATE "LedgerTransaction" SET memo = \'edited\'',
    'DELETE FROM "LedgerTransaction"',
])
def test_ledger_rows_can_never_be_edited_or_deleted(conn, sql):
    topup(conn, 1, 500, "t1")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(sql)
    conn.rollback()
    assert user_balance(conn, 1) == 500


def test_database_rejects_float_and_zero_amounts_even_without_this_module(conn):
    conn.execute('INSERT INTO "LedgerTransaction"(kind, idempotency_key, created_at) '
                 "VALUES ('x', 'raw', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO "LedgerEntry"(txn_id, account, amount_cents) '
                     "VALUES (1, 'user:1', 1.5)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO "LedgerEntry"(txn_id, account, amount_cents) '
                     "VALUES (1, 'user:1', 0)")
    conn.rollback()


# --- Refunds ------------------------------------------------------------------

def test_refund_reverses_an_order_exactly(conn):
    topup(conn, 1, 1000, "t1")
    order = post_transaction(conn, "order", [("user:1", -600), ("restaurant:2", 550),
                                             ("fees:service", 50)], "o1")

    refund = reverse_transaction(conn, order.txn_id, "r1")

    assert user_balance(conn, 1) == 1000
    assert ledger.balance(conn, "restaurant:2") == 0
    assert conn.execute('SELECT reverses_txn_id, kind FROM "LedgerTransaction" WHERE txn_id = ?',
                        (refund.txn_id,)).fetchone() == (order.txn_id, "refund")
    assert check_ledger(conn).ok


def test_a_transaction_can_only_be_refunded_once(conn):
    topup(conn, 1, 1000, "t1")
    order = post_transaction(conn, "order", [("user:1", -600), ("restaurant:2", 600)], "o1")
    reverse_transaction(conn, order.txn_id, "r1")

    assert reverse_transaction(conn, order.txn_id, "r1").created is False   # same request again
    with pytest.raises(AlreadyReversed):
        reverse_transaction(conn, order.txn_id, "r2")                       # a second refund
    assert user_balance(conn, 1) == 1000


def test_reversing_a_top_up_that_was_already_spent_is_refused(conn):
    t = topup(conn, 1, 1000, "t1")
    gift(conn, 1, 2, 800, "g1")
    with pytest.raises(InsufficientFunds):
        reverse_transaction(conn, t.txn_id, "r1")
    assert user_balance(conn, 1) == 200


def test_reversing_an_unknown_transaction_is_an_error(conn):
    with pytest.raises(LedgerError):
        reverse_transaction(conn, 404, "r1")


# --- Reading ------------------------------------------------------------------

def test_history_lists_a_users_transactions_newest_first(conn):
    topup(conn, 1, 1000, "t1")
    gift(conn, 1, 2, 250, "g1")
    gift(conn, 2, 1, 50, "g2")

    rows = ledger.history(conn, "user:1")

    assert [(r["kind"], r["amount_cents"]) for r in rows] == [("gift", 50), ("gift", -250),
                                                              ("topup", 1000)]
    assert ledger.history(conn, "user:1", limit=1)[0]["txn_id"] == 3
    assert ledger.history(conn, "user:99") == []


def test_unknown_accounts_have_zero_balance(conn):
    assert user_balance(conn, 12345) == 0


def test_check_ledger_reports_problems_written_behind_its_back(conn):
    topup(conn, 1, 100, "t1")
    conn.execute('INSERT INTO "LedgerTransaction"(kind, idempotency_key, created_at) '
                 "VALUES ('bad', 'bad', 'now')")
    conn.execute('INSERT INTO "LedgerEntry"(txn_id, account, amount_cents) VALUES (2, \'user:3\', -7)')
    conn.commit()

    check = check_ledger(conn)

    assert not check.ok
    assert check.total_cents == -7
    assert check.unbalanced_txn_ids == (2,)
    assert check.negative_user_accounts == ("user:3",)


# --- Concurrency --------------------------------------------------------------

def test_concurrent_spending_from_separate_connections_never_overdraws(tmp_path):
    path = tmp_path / "race.db"
    setup = _connect(path)
    topup(setup, 1, 1000, "t1")
    setup.close()

    barrier = threading.Barrier(10)
    outcomes = []

    def spend(i):
        c = _connect(path)
        try:
            barrier.wait()
            gift(c, 1, 100 + i, 300, f"g{i}")
            outcomes.append("ok")
        except InsufficientFunds:
            outcomes.append("refused")
        finally:
            c.close()

    threads = [threading.Thread(target=spend, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check_conn = _connect(path)
    try:
        assert outcomes.count("ok") == 3 and outcomes.count("refused") == 7
        assert user_balance(check_conn, 1) == 100
        assert check_ledger(check_conn).ok
    finally:
        check_conn.close()


# --- Property-based: random sequences keep every invariant --------------------

USERS = (1, 2, 3)
cents = st.integers(min_value=1, max_value=50_000)


class LedgerMachine(RuleBasedStateMachine):
    """Runs random top-ups, gifts, orders, refunds and replays against the
    ledger and checks after every step that it agrees with a simple model."""

    def __init__(self):
        super().__init__()
        self.conn = sqlite3.connect(":memory:")
        ledger.ensure_schema(self.conn)
        self.model = {u: 0 for u in USERS}
        self.refundable = []        # (txn_id, usr_id, cents) of orders not yet refunded
        self.posted = []            # (key, kind, entries) that succeeded
        self.n = 0

    def _key(self):
        self.n += 1
        return f"k{self.n}"

    def _post(self, kind, entries):
        key = self._key()
        result = post_transaction(self.conn, kind, entries, key)
        self.posted.append((key, kind, entries))
        return result

    @rule(user=st.sampled_from(USERS), amount=cents)
    def top_up(self, user, amount):
        self._post("topup", [(f"user:{user}", amount), ("external:topup", -amount)])
        self.model[user] += amount

    @rule(sender=st.sampled_from(USERS), receiver=st.sampled_from(USERS), amount=cents)
    def send_gift(self, sender, receiver, amount):
        entries = [(f"user:{sender}", -amount), (f"user:{receiver}", amount)]
        if sender == receiver:
            with pytest.raises(InvalidTransaction):
                self._post("gift", entries)
        elif self.model[sender] < amount:
            with pytest.raises(InsufficientFunds):
                self._post("gift", entries)
        else:
            self._post("gift", entries)
            self.model[sender] -= amount
            self.model[receiver] += amount

    @rule(user=st.sampled_from(USERS), food=cents, fee=st.integers(0, 999))
    def place_order(self, user, food, fee):
        total = food + fee
        entries = [(f"user:{user}", -total), ("restaurant:1", food)]
        if fee:
            entries.append(("fees:service", fee))
        if self.model[user] < total:
            with pytest.raises(InsufficientFunds):
                self._post("order", entries)
        else:
            result = self._post("order", entries)
            self.model[user] -= total
            self.refundable.append((result.txn_id, user, total))

    @precondition(lambda self: self.refundable)
    @rule(pick=st.integers(min_value=0))
    def refund_order(self, pick):
        txn_id, user, total = self.refundable.pop(pick % len(self.refundable))
        reverse_transaction(self.conn, txn_id, self._key())
        self.model[user] += total

    @precondition(lambda self: self.posted)
    @rule(pick=st.integers(min_value=0))
    def replay_a_request(self, pick):
        key, kind, entries = self.posted[pick % len(self.posted)]
        assert post_transaction(self.conn, kind, entries, key).created is False

    @invariant()
    def entries_sum_to_zero_and_nothing_is_negative(self):
        check = check_ledger(self.conn)
        assert check.ok, check

    @invariant()
    def balances_match_the_model(self):
        for u in USERS:
            assert user_balance(self.conn, u) == self.model[u]

    def teardown(self):
        self.conn.close()


LedgerMachine.TestCase.settings = settings(max_examples=60, stateful_step_count=40, deadline=None)
TestLedgerProperties = LedgerMachine.TestCase
