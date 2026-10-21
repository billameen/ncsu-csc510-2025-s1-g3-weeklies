"""
A user's fee settings for planning (M4): batching and where they agree to pick up.

Stored in their own table, UserFeePrefs, so the User table's column order (which login reads
by position) does not change. A user without a row has the defaults: batching off and no
pickup, which plans exactly like M1.

    prefs = load_fee_prefs(conn, usr_id)
    PlanRequest(..., options=prefs.plan_options())
"""
import json
import sqlite3
from dataclasses import dataclass

from planner.menu import WEEKDAYS
from planner.rules.fee_cost import FeeCostConstraint

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS "UserFeePrefs" (
    usr_id             INTEGER PRIMARY KEY REFERENCES "User"(usr_id),
    batching           INTEGER NOT NULL DEFAULT 0 CHECK (batching IN (0, 1)),
    pickup_restaurants TEXT    NOT NULL DEFAULT '[]',
    pickup_days        TEXT    NOT NULL DEFAULT '[]'
);
"""


@dataclass(frozen=True)
class FeePrefs:
    """batching: share deliveries; pickup at these restaurants on these days (both needed)."""

    batching: bool = False
    pickup_restaurants: tuple = ()
    pickup_days: tuple = ()

    def __post_init__(self):
        # Validated by the planner rule itself, so the settings page and the planner agree.
        FeeCostConstraint(self.batching, self.pickup_restaurants, self.pickup_days)
        object.__setattr__(self, "pickup_restaurants", tuple(sorted(set(self.pickup_restaurants))))
        object.__setattr__(self, "pickup_days",
                           tuple(sorted(set(self.pickup_days), key=WEEKDAYS.index)))

    def plan_options(self) -> dict:
        """PlanRequest options for these settings."""
        return {"fee_cost": {"batching": self.batching,
                             "pickup_restaurants": list(self.pickup_restaurants),
                             "pickup_days": list(self.pickup_days)}}


def ensure_fee_prefs_schema(conn) -> None:
    conn.executescript(SCHEMA_SQL)


def load_fee_prefs(conn, usr_id) -> FeePrefs:
    """The user's settings, or the defaults if they never saved any (or the table is missing)."""
    try:
        row = conn.execute(
            'SELECT batching, pickup_restaurants, pickup_days FROM "UserFeePrefs" WHERE usr_id = ?',
            (usr_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return FeePrefs()
    if not row:
        return FeePrefs()
    batching, restaurants, days = row
    try:
        return FeePrefs(bool(batching), tuple(json.loads(restaurants or "[]")),
                        tuple(json.loads(days or "[]")))
    except (ValueError, TypeError):
        return FeePrefs()   # unreadable settings: plan like M1 rather than fail


def save_fee_prefs(conn, usr_id, prefs: FeePrefs) -> None:
    ensure_fee_prefs_schema(conn)
    conn.execute(
        '''INSERT INTO "UserFeePrefs" (usr_id, batching, pickup_restaurants, pickup_days)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(usr_id) DO UPDATE SET batching = excluded.batching,
               pickup_restaurants = excluded.pickup_restaurants, pickup_days = excluded.pickup_days''',
        (usr_id, int(prefs.batching), json.dumps(list(prefs.pickup_restaurants)),
         json.dumps(list(prefs.pickup_days))),
    )
    conn.commit()
