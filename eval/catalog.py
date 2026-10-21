"""
Load the menu data the evaluation plans against: in-stock items from open restaurants.

Allergen tags are kept exactly as stored (e.g. both "Egg" and "Eggs" appear in the seed data).
Normalizing them is the validator's job, so its tests can prove it handles the raw tags.
"""

import json
import os
from dataclasses import dataclass, field

from planner.fees import DEFAULT_FEES, FeeSchedule, load_fee_schedule
from sqlQueries import create_connection, close_connection, fetch_all

RESTAURANTS_QUERY = """
    SELECT rtr_id, hours FROM Restaurant
    WHERE status = 'Open'
    ORDER BY rtr_id
"""

ITEMS_QUERY = """
    SELECT m.itm_id, m.rtr_id, m.price, m.calories, m.allergens
    FROM MenuItem m JOIN Restaurant r ON r.rtr_id = m.rtr_id
    WHERE m.instock = 1 AND r.status = 'Open'
    ORDER BY m.itm_id
"""


@dataclass(frozen=True)
class Item:
    itm_id: int
    rtr_id: int
    price_cents: int
    calories: int
    allergens: tuple[str, ...]


@dataclass(frozen=True)
class Restaurant:
    rtr_id: int
    # Weekday ("Mon".."Sun") -> flat list of open/close times, e.g. (1100, 1400, 1700, 2100).
    hours: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class Catalog:
    # Keyed by id, in ascending id order, so seeded random choices are reproducible.
    items: dict[int, Item]
    restaurants: dict[int, Restaurant]
    # Tax rate and each restaurant's fees (M4); the defaults are the pre-M4 fees.
    fees: FeeSchedule = field(default=DEFAULT_FEES)


def load_catalog(db_path: str | os.PathLike) -> Catalog:
    """
    Load in-stock menu items from open restaurants.
    Args:
        db_path: Path to a SQLite database built from app/db/seed.sql.
    Returns:
        Catalog: Items and restaurants keyed by id.
    Raises:
        FileNotFoundError: The database file does not exist.
        ValueError: The database has no open restaurants or in-stock items.
    """
    # sqlite3.connect would silently create an empty file, so check first.
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"Database not found at {db_path}. Build it with `python app/scripts/init_db.py`."
        )

    conn = create_connection(db_path)
    try:
        restaurant_rows = fetch_all(conn, RESTAURANTS_QUERY)
        item_rows = fetch_all(conn, ITEMS_QUERY)
        fees = load_fee_schedule(conn)
    finally:
        close_connection(conn)

    # fetch_all returns [] on SQL errors too, so an empty result also covers a missing schema.
    if not restaurant_rows or not item_rows:
        raise ValueError(
            f"No open restaurants or in-stock menu items in {db_path}. "
            "Rebuild it with `python app/scripts/init_db.py --force`."
        )

    restaurants = {
        rtr_id: Restaurant(rtr_id=rtr_id, hours=_parse_hours(hours))
        for rtr_id, hours in restaurant_rows
    }
    items = {
        itm_id: Item(
            itm_id=itm_id,
            rtr_id=rtr_id,
            price_cents=int(price),
            calories=int(calories),
            allergens=_split_allergens(allergens),
        )
        for itm_id, rtr_id, price, calories, allergens in item_rows
    }
    return Catalog(items=items, restaurants=restaurants, fees=fees)


def _split_allergens(raw: str | None) -> tuple[str, ...]:
    """Split a comma-separated tag string, dropping blanks. Tags are not normalized."""
    if not raw:
        return ()
    return tuple(tag.strip() for tag in raw.split(",") if tag.strip())


def _parse_hours(raw: str | None) -> dict[str, tuple[int, ...]]:
    """
    Parse the hours JSON. Missing or unreadable hours, and any weekday whose value is not a
    list of integer times, give no opening times. Whether a day's times make sense (e.g. an
    odd number of them) is left to the validator.
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        day: tuple(times)
        for day, times in parsed.items()
        if isinstance(times, list) and all(type(t) is int for t in times)
    }
