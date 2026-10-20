"""
Migration: add per-restaurant fees (M4).

Creates the RestaurantFee table if it is missing and gives every restaurant that has no row
yet the synthetic delivery fee the seed data uses ($1.99 to $5.99, see
planner/fees.py: synthetic_delivery_fee_cents). The service fee is left NULL, which means the
default $1.49. Fees already in the table are never changed.

These fees are a synthetic model for the course project, not real prices.

Idempotent: running it again adds nothing.

Run (from app/):
    python migrations/add_restaurant_fees.py
    python migrations/add_restaurant_fees.py path/to/other.db
"""

import os
import sqlite3
import sys

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from planner.fees import ensure_fee_schema, synthetic_delivery_fee_cents  # noqa: E402


def get_db_path():
    return os.path.join(APP_DIR, "CSC510_DB.db")


def migrate(conn) -> int:
    """Add the table and any missing fee rows. Returns how many rows were added."""
    ensure_fee_schema(conn)
    missing = conn.execute(
        '''SELECT r.rtr_id FROM "Restaurant" r
           LEFT JOIN "RestaurantFee" f ON f.rtr_id = r.rtr_id
           WHERE f.rtr_id IS NULL ORDER BY r.rtr_id'''
    ).fetchall()
    conn.executemany(
        'INSERT INTO "RestaurantFee" (rtr_id, delivery_fee_cents, service_fee_cents) VALUES (?, ?, NULL)',
        [(rtr_id, synthetic_delivery_fee_cents(rtr_id)) for (rtr_id,) in missing],
    )
    conn.commit()
    return len(missing)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    db_path = args[0] if args else get_db_path()
    if not os.path.exists(db_path):
        print(f"✗ Database not found: {db_path}")
        return 1
    conn = sqlite3.connect(db_path)
    try:
        added = migrate(conn)
        total = conn.execute('SELECT count(*) FROM "RestaurantFee"').fetchone()[0]
    finally:
        conn.close()
    print(f"✓ RestaurantFee table ready: {added} restaurant(s) given fees, {total} in total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
