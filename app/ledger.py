"""Double-entry wallet ledger (M2).

Every movement of money is one ``LedgerTransaction`` with two or more
``LedgerEntry`` rows. Each entry moves an integer number of cents into (+) or
out of (-) an account, and the entries of a transaction always add up to 0,
so money can only move between accounts, never appear or disappear.

Accounts are plain strings:

* ``user:<usr_id>``        a customer's wallet (never allowed to go negative)
* ``restaurant:<rtr_id>``  money owed to a restaurant
* ``fees:<name>``          platform fees, e.g. ``fees:delivery``, ``fees:service``
* ``tax``                  sales tax collected
* ``external:<name>``      money entering or leaving the system, e.g.
                           ``external:topup`` (card top-ups) and
                           ``external:opening`` (balances migrated from the old
                           ``User.wallet`` column)

A wallet balance is the sum of that account's entries. Rows are never edited
or deleted (database triggers enforce this); mistakes and refunds are fixed by
posting a reversing transaction.

All amounts are ``int`` cents. See ``money.py`` for why money is never a float.
"""
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS "LedgerTransaction" (
    txn_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT    NOT NULL,
    idempotency_key  TEXT    NOT NULL UNIQUE,
    created_at       TEXT    NOT NULL,
    memo             TEXT,
    reverses_txn_id  INTEGER REFERENCES "LedgerTransaction"(txn_id)
);

CREATE TABLE IF NOT EXISTS "LedgerEntry" (
    entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id        INTEGER NOT NULL REFERENCES "LedgerTransaction"(txn_id),
    account       TEXT    NOT NULL,
    amount_cents  INTEGER NOT NULL
                  CHECK (typeof(amount_cents) = 'integer' AND amount_cents <> 0)
);

CREATE INDEX IF NOT EXISTS ix_ledger_entry_account ON "LedgerEntry"(account);
CREATE INDEX IF NOT EXISTS ix_ledger_entry_txn ON "LedgerEntry"(txn_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_reverses
    ON "LedgerTransaction"(reverses_txn_id) WHERE reverses_txn_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS ledger_entry_no_update BEFORE UPDATE ON "LedgerEntry"
BEGIN SELECT RAISE(ABORT, 'ledger entries are append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_entry_no_delete BEFORE DELETE ON "LedgerEntry"
BEGIN SELECT RAISE(ABORT, 'ledger entries are append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_txn_no_update BEFORE UPDATE ON "LedgerTransaction"
BEGIN SELECT RAISE(ABORT, 'ledger transactions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_txn_no_delete BEFORE DELETE ON "LedgerTransaction"
BEGIN SELECT RAISE(ABORT, 'ledger transactions are append-only'); END;
"""

_ACCOUNT_RE = re.compile(r"(?:user|restaurant):[1-9][0-9]*|fees:[a-z_]+|tax|external:[a-z_]+")
_KIND_RE = re.compile(r"[a-z_]+")
MAX_KEY_LENGTH = 128


# --- Errors -------------------------------------------------------------------

class LedgerError(Exception):
    """Base class for ledger failures. Nothing is written when one is raised."""


class InvalidTransaction(LedgerError):
    """The entries are malformed: bad account, non-int or zero amount, etc."""


class UnbalancedTransaction(InvalidTransaction):
    """The entries do not add up to zero."""


class InsufficientFunds(LedgerError):
    """Posting would leave a ``user:`` account below zero."""

    def __init__(self, account, balance_cents):
        super().__init__(f"{account} would go to {balance_cents} cents")
        self.account = account
        self.balance_cents = balance_cents


class IdempotencyConflict(LedgerError):
    """The idempotency key was already used for a different transaction."""


class AlreadyReversed(LedgerError):
    """The transaction has already been reversed (refunded)."""


# --- Results ------------------------------------------------------------------

@dataclass(frozen=True)
class PostResult:
    """Outcome of ``post_transaction``.

    ``created`` is False when the idempotency key had already been used, in which
    case nothing was written and ``txn_id`` is the original transaction.
    ``extra`` is whatever the ``after`` callback returned (None on a replay).
    """
    txn_id: int
    created: bool
    extra: object = None


# --- Accounts -----------------------------------------------------------------

def user_account(usr_id) -> str:
    return f"user:{int(usr_id)}"


def restaurant_account(rtr_id) -> str:
    return f"restaurant:{int(rtr_id)}"


# --- Schema -------------------------------------------------------------------

def ensure_schema(conn) -> None:
    """Create the ledger tables, indexes and append-only triggers if missing."""
    conn.executescript(SCHEMA_SQL)


# --- Writing ------------------------------------------------------------------

def _normalise_entries(entries):
    """Validate entries and merge duplicate accounts. Returns a sorted list."""
    totals = {}
    for entry in entries:
        try:
            account, amount = entry
        except (TypeError, ValueError):
            raise InvalidTransaction(f"entry must be (account, cents): {entry!r}") from None
        if not isinstance(account, str) or not _ACCOUNT_RE.fullmatch(account):
            raise InvalidTransaction(f"bad account name: {account!r}")
        if type(amount) is not int:
            raise InvalidTransaction(f"amount must be int cents, got {type(amount).__name__}")
        if amount == 0:
            raise InvalidTransaction(f"zero amount for {account}")
        totals[account] = totals.get(account, 0) + amount
    merged = sorted((a, c) for a, c in totals.items() if c != 0)
    if len(merged) < 2:
        raise InvalidTransaction("a transaction needs at least two non-zero entries")
    if sum(c for _, c in merged) != 0:
        raise UnbalancedTransaction(f"entries sum to {sum(c for _, c in merged)}, not 0")
    return merged


def _stored_entries(cur, txn_id):
    return sorted(cur.execute(
        'SELECT account, SUM(amount_cents) FROM "LedgerEntry" WHERE txn_id = ? GROUP BY account',
        (txn_id,),
    ).fetchall())


def post_transaction(conn, kind, entries, idempotency_key, *, memo=None,
                     reverses_txn_id=None, after=None) -> PostResult:
    """Record one balanced transaction atomically.

    Args:
        conn: sqlite3 connection with no transaction already open.
        kind: short lowercase label, e.g. ``"topup"``, ``"gift"``, ``"order"``.
        entries: iterable of ``(account, cents)``; cents are non-zero ``int``s
            that must sum to 0.
        idempotency_key: unique string per real-world request. Posting again
            with the same key and the same entries changes nothing and returns
            the original ``txn_id`` with ``created=False``.
        memo: optional human-readable note shown in transaction history.
        reverses_txn_id: set when this transaction reverses (refunds) another.
        after: optional ``callback(cursor, txn_id)`` run inside the same database
            transaction after the entries are written (e.g. to insert the order
            this payment is for). If it raises, everything is rolled back.

    Raises:
        InvalidTransaction / UnbalancedTransaction: malformed entries.
        InsufficientFunds: a ``user:`` account would end below zero.
        IdempotencyConflict: the key was used for a different transaction.
        AlreadyReversed: ``reverses_txn_id`` has already been reversed.
    """
    if not isinstance(kind, str) or not _KIND_RE.fullmatch(kind):
        raise InvalidTransaction(f"bad kind: {kind!r}")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() \
            or len(idempotency_key) > MAX_KEY_LENGTH:
        raise InvalidTransaction("idempotency_key must be a non-empty string of at most "
                                 f"{MAX_KEY_LENGTH} characters")
    merged = _normalise_entries(entries)
    if conn.in_transaction:
        raise LedgerError("post_transaction needs a connection with no open transaction")

    cur = conn.cursor()
    # IMMEDIATE takes the database write lock now, so the balance check below
    # cannot be invalidated by another writer before we commit.
    cur.execute("BEGIN IMMEDIATE")
    try:
        existing = cur.execute(
            'SELECT txn_id, kind FROM "LedgerTransaction" WHERE idempotency_key = ?',
            (idempotency_key,),
        ).fetchone()
        if existing:
            txn_id, existing_kind = existing
            if existing_kind != kind or _stored_entries(cur, txn_id) != merged:
                raise IdempotencyConflict(
                    f"key {idempotency_key!r} was already used for transaction {txn_id}")
            conn.rollback()
            return PostResult(txn_id=txn_id, created=False)

        if reverses_txn_id is not None:
            done = cur.execute(
                'SELECT txn_id FROM "LedgerTransaction" WHERE reverses_txn_id = ?',
                (reverses_txn_id,),
            ).fetchone()
            if done:
                raise AlreadyReversed(f"transaction {reverses_txn_id} was already reversed "
                                      f"by {done[0]}")

        cur.execute(
            '''INSERT INTO "LedgerTransaction"
                   (kind, idempotency_key, created_at, memo, reverses_txn_id)
               VALUES (?, ?, ?, ?, ?)''',
            (kind, idempotency_key, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             memo, reverses_txn_id),
        )
        txn_id = cur.lastrowid
        cur.executemany(
            'INSERT INTO "LedgerEntry" (txn_id, account, amount_cents) VALUES (?, ?, ?)',
            [(txn_id, account, cents) for account, cents in merged],
        )

        for account, cents in merged:
            if cents < 0 and account.startswith("user:"):
                bal = _balance(cur, account)
                if bal < 0:
                    raise InsufficientFunds(account, bal)

        extra = after(cur, txn_id) if after is not None else None
        conn.commit()
        return PostResult(txn_id=txn_id, created=True, extra=extra)
    except BaseException:
        conn.rollback()
        raise


def reverse_transaction(conn, txn_id, idempotency_key, *, kind="refund", memo=None,
                        after=None) -> PostResult:
    """Post the exact opposite of ``txn_id`` (a refund). Rows are never edited.

    Raises ``LedgerError`` if ``txn_id`` does not exist, ``AlreadyReversed`` if it
    was already reversed, and ``InsufficientFunds`` if a user has already spent
    money the reversal would take back.
    """
    rows = conn.execute(
        'SELECT account, amount_cents FROM "LedgerEntry" WHERE txn_id = ?', (txn_id,)
    ).fetchall()
    if not rows:
        raise LedgerError(f"no such transaction: {txn_id}")
    return post_transaction(
        conn, kind, [(account, -cents) for account, cents in rows], idempotency_key,
        memo=memo or f"Reversal of transaction {txn_id}", reverses_txn_id=txn_id, after=after,
    )


# --- Reading ------------------------------------------------------------------

def _balance(cur, account) -> int:
    return cur.execute(
        'SELECT COALESCE(SUM(amount_cents), 0) FROM "LedgerEntry" WHERE account = ?',
        (account,),
    ).fetchone()[0]


def balance(conn, account) -> int:
    """Current balance of an account in cents (0 if it has no entries)."""
    return _balance(conn.cursor(), account)


def user_balance(conn, usr_id) -> int:
    """Current wallet balance of a user in cents."""
    return balance(conn, user_account(usr_id))


def history(conn, account, limit=50):
    """Most recent transactions touching ``account``, newest first.

    Returns a list of dicts: ``txn_id``, ``kind``, ``created_at``, ``memo``,
    ``amount_cents`` (this account's net change) and ``reverses_txn_id``.
    """
    rows = conn.execute(
        '''SELECT t.txn_id, t.kind, t.created_at, t.memo, SUM(e.amount_cents), t.reverses_txn_id
           FROM "LedgerEntry" e JOIN "LedgerTransaction" t ON t.txn_id = e.txn_id
           WHERE e.account = ?
           GROUP BY t.txn_id
           ORDER BY t.txn_id DESC
           LIMIT ?''',
        (account, int(limit)),
    ).fetchall()
    keys = ("txn_id", "kind", "created_at", "memo", "amount_cents", "reverses_txn_id")
    return [dict(zip(keys, row)) for row in rows]


@dataclass(frozen=True)
class LedgerCheck:
    """Result of ``check_ledger``: the admin "ledger balanced" indicator."""
    total_cents: int
    unbalanced_txn_ids: tuple
    negative_user_accounts: tuple

    @property
    def ok(self) -> bool:
        return (self.total_cents == 0 and not self.unbalanced_txn_ids
                and not self.negative_user_accounts)


def check_ledger(conn) -> LedgerCheck:
    """Verify the ledger's invariants: every transaction sums to 0, so the whole
    ledger sums to 0, and no user wallet is negative."""
    total = conn.execute('SELECT COALESCE(SUM(amount_cents), 0) FROM "LedgerEntry"').fetchone()[0]
    unbalanced = tuple(r[0] for r in conn.execute(
        'SELECT txn_id FROM "LedgerEntry" GROUP BY txn_id HAVING SUM(amount_cents) <> 0'))
    negative = tuple(r[0] for r in conn.execute(
        '''SELECT account FROM "LedgerEntry" WHERE account LIKE 'user:%'
           GROUP BY account HAVING SUM(amount_cents) < 0'''))
    return LedgerCheck(total, unbalanced, negative)


# --- User wallets and the old User.wallet column ------------------------------

#: Counter-account for balances moved over from the old ``User.wallet`` column.
OPENING_ACCOUNT = "external:opening"


def opening_key(usr_id) -> str:
    """Idempotency key of a user's opening-balance transaction."""
    return f"opening:user:{int(usr_id)}"


def open_legacy_wallet(conn, usr_id):
    """Move a user's pre-ledger ``User.wallet`` balance into the ledger, once.

    Before the ledger, a wallet was a single editable ``User.wallet`` column.
    The first time a user's money is touched, their column value becomes an
    ``opening_balance`` transaction (from ``external:opening``); after that the
    column is never read again. Safe to call any number of times and from
    concurrent requests: the idempotency key makes it happen at most once.
    A zero balance needs no opening entry.

    Returns the ``PostResult`` if an opening transaction was written or already
    existed, or None if there was nothing to open.
    """
    key = opening_key(usr_id)
    if conn.execute('SELECT 1 FROM "LedgerTransaction" WHERE idempotency_key = ?',
                    (key,)).fetchone():
        return PostResult(txn_id=conn.execute(
            'SELECT txn_id FROM "LedgerTransaction" WHERE idempotency_key = ?', (key,)
        ).fetchone()[0], created=False)
    row = conn.execute('SELECT wallet FROM "User" WHERE usr_id = ?', (int(usr_id),)).fetchone()
    cents = row[0] if row else 0
    if not cents:
        return None
    if type(cents) is not int or cents < 0:
        raise LedgerError(f"user {usr_id} has an invalid legacy wallet value: {cents!r}")
    return post_transaction(
        conn, "opening_balance", [(user_account(usr_id), cents), (OPENING_ACCOUNT, -cents)], key,
        memo="Opening balance (moved from the old wallet)",
    )


def wallet_balance(conn, usr_id) -> int:
    """A user's wallet balance in cents, opening their legacy balance first if needed."""
    open_legacy_wallet(conn, usr_id)
    return user_balance(conn, usr_id)
