"""
The menu the planner chooses from: every menu item and restaurant in the database.

Nothing is filtered here. Whether an item is in stock or its restaurant is open is decided
by the planner's rules (see `planner.rules`), so each rule can be tested, and can explain
itself, on its own.
"""

import json
import os
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pricing import DELIVERY_FEE, SERVICE_FEE, TAX_RATE
from sqlQueries import close_connection, create_connection, fetch_all

from planner.allergens import parse_allergens

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Meal number (as stored in User.generated_menu) -> name and order time (HHMM). Same times as
# v1's menu_generation and the M0 validator.
MEAL_NAMES = {1: "breakfast", 2: "lunch", 3: "dinner"}
MEAL_TIMES = {1: 1000, 2: 1400, 3: 2000}

# Exact decimal copies of the dollar constants; int(4.35 * 100) is 434 in floating point.
_TAX_RATE = Decimal(str(TAX_RATE))
_FEES_CENTS = int(Decimal(str(DELIVERY_FEE)) * 100 + Decimal(str(SERVICE_FEE)) * 100)


@dataclass(frozen=True)
class MenuItem:
    """One row of MenuItem. Prices are in cents."""

    itm_id: int
    rtr_id: int
    name: str
    description: str
    price_cents: int
    calories: int
    allergens: tuple[str, ...]  # as stored, e.g. ("Egg", "Dairy"); see planner.allergens
    in_stock: bool

    @property
    def cost_cents(self) -> int:
        """What ordering this item on its own costs, tax and fees included."""
        return meal_cost_cents(self.price_cents)


@dataclass(frozen=True)
class Restaurant:
    """One row of Restaurant."""

    rtr_id: int
    name: str
    status_open: bool  # Restaurant.status is "Open"
    # Weekday ("Mon".."Sun") -> flat open/close times, e.g. (1100, 1400, 1700, 2100).
    hours: dict[str, tuple[int, ...]]

    def is_open_at(self, weekday: str, hhmm: int) -> bool:
        """
        True if the restaurant takes orders at hhmm on weekday: its status is Open and the
        time falls inside one of that day's (open, close) pairs, both ends included. A day
        with no times or an odd number of them (unreadable) counts as closed.
        """
        times = self.hours.get(weekday, ())
        if not self.status_open or len(times) % 2:
            return False
        return any(times[i] <= hhmm <= times[i + 1] for i in range(0, len(times), 2))


@dataclass(frozen=True)
class Menu:
    """Everything the planner can choose from, keyed by id in ascending id order."""

    items: dict[int, MenuItem]
    restaurants: dict[int, Restaurant]


def meal_cost_cents(price_cents: int) -> int:
    """
    Cost of one meal ordered on its own for delivery: the item price, plus tax rounded half
    up to the cent, plus the delivery and service fees. This is how checkout and the M0
    validator charge a meal, and it is what the weekly budget is compared against.
    """
    tax = (price_cents * _TAX_RATE).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return price_cents + int(tax) + _FEES_CENTS


def load_menu(db_path: str | os.PathLike) -> Menu:
    """
    Read every menu item and restaurant from the database.
    Args:
        db_path: Path to the app's SQLite database.
    Returns:
        Menu: All items (in stock or not) and all restaurants (open or not).
    Raises:
        FileNotFoundError: The database file does not exist.
    """
    # sqlite3.connect would silently create an empty database instead.
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")
    conn = create_connection(db_path)
    try:
        restaurant_rows = fetch_all(
            conn, 'SELECT rtr_id, name, status, hours FROM "Restaurant" ORDER BY rtr_id'
        )
        item_rows = fetch_all(
            conn,
            """SELECT itm_id, rtr_id, name, description, price, calories, allergens, instock
               FROM "MenuItem" ORDER BY itm_id""",
        )
    finally:
        close_connection(conn)

    restaurants = {
        rtr_id: Restaurant(
            rtr_id=rtr_id,
            name=name or "",
            status_open=(status or "").strip().lower() == "open",
            hours=parse_hours(hours),
        )
        for rtr_id, name, status, hours in restaurant_rows
    }
    items = {
        itm_id: MenuItem(
            itm_id=itm_id,
            rtr_id=rtr_id,
            name=name or "",
            description=description or "",
            price_cents=int(price or 0),
            calories=int(calories or 0),
            allergens=parse_allergens(allergens),
            in_stock=instock == 1,
        )
        for itm_id, rtr_id, name, description, price, calories, allergens, instock in item_rows
    }
    return Menu(items=items, restaurants=restaurants)


def parse_hours(raw: str | None) -> dict[str, tuple[int, ...]]:
    """
    Parse Restaurant.hours JSON, e.g. '{"Mon": [1100, 2200], "Tue": []}'. Missing or
    unreadable hours, and any weekday whose value is not a list of integer times, give no
    opening times, so the restaurant counts as closed then (the safe choice for planning).
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
