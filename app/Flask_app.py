import os
import re
import sys
import argparse
import math
import json
import calendar
from enum import Enum
from io import BytesIO
from flask import jsonify
from sqlite3 import IntegrityError
import sqlite3
from datetime import timedelta, date, datetime
from pdf_receipt import generate_order_receipt_pdf
from werkzeug.security import check_password_hash, generate_password_hash
from flask import Flask, render_template, url_for, redirect, request, session, send_file, abort

# Use ONLY these helpers for DB access
from sqlQueries import create_connection, close_connection, fetch_one, fetch_all, execute_query
from money import MoneyError, parse_cents, cents_to_str, format_cents
import uuid
import ledger
from charges import compute_charges, order_charges_cents, item_cents
from collections import Counter, defaultdict
from menu_generation import MenuGenerator, ALLERGEN_TAGS, invalid_allergies
from planner.targets import (
    TargetError,
    format_budget,
    parse_daily_calorie_target,
    parse_weekly_budget,
)
from planner.menu import WEEKDAYS, load_menu
from planner.fees import DEFAULT_FEES, load_fee_schedule
from fee_prefs import FeePrefs, load_fee_prefs, save_fee_prefs
from planner.request import InvalidPlanRequest, PlanRequest
from planner.solver import plan_week

# Which planner /generate_plan uses: "solver" (CP-SAT, the default) or "llm" (v1, kept as the
# M0 baseline). Read on every request, so it can be switched without a restart.
PLANNER_ENV = "PLANNER"
PLANNERS = ("solver", "llm")

# ----------MANAGE ORDER STATUS--------------
class OrderStatus(Enum):
    ORDERED =  'Ordered'
    PREPARING = 'Preparing'
    DELIVERED = 'Delivered'

    def get_lowercase(self):
        return self.value.lower()
    
    def get_uppercase(self):
        return self.value.upper()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'

db_file = os.path.join(os.path.dirname(__file__), 'CSC510_DB.db')

# The selectable allergens, shared by the register and edit-profile forms
app.jinja_env.globals['ALLERGEN_OPTIONS'] = list(ALLERGEN_TAGS)

# ---------------------- Helpers ----------------------

def _first_present(d: dict, *keys):
    """
    Return the value of the first key in d whose value is not None.
    Unlike chaining with `or`, falsy values such as 0 / 0.0 count as present.
    Args:
        d (dict): The mapping to search.
        *keys: Keys to try, in order.
    Returns:
        The first non-None value, or None if no key has one.
    """
    return next((d[k] for k in keys if d.get(k) is not None), None)

def _money(x: float) -> float:
    """
    Safely round a numeric value to two decimal places.
    Args:
        x (float): The numeric amount to round.
    Returns:
        float: The amount rounded to two decimals, or 0.0 on failure.
    """
    try:
        return round(float(x) + 1e-9, 2)
    except Exception:
        return 0.0

def _cents_to_dollars(cents) -> float:
    """
    Convert an amount in cents to dollars with two-decimal precision.
    Args:
        cents (int | float | None): The value in cents to convert.
    Returns:
        float: The dollar value rounded to two decimals (0.0 on failure).
    """
    try:
        return _money((cents or 0) / 100.0)
    except Exception:
        return 0.0
    
def _dollars_to_cents(dollars) -> int:
    """
    Convert an amount in dollars to cents, rounding half up (see ``money.py``).
    Args:
        dollars (int | float | str | None): The value in dollars to convert.
    Returns:
        int: The cent value (0 on failure).
    """
    try:
        return parse_cents(dollars)
    except MoneyError:
        return 0


def _parse_amount_cents(raw) -> int:
    """
    Strictly parse a user-entered dollar amount into cents (see ``money.parse_cents``).
    Args:
        raw (str | int | None): The amount as entered, e.g. "12.50".
    Returns:
        int: The amount in cents, rounded half-up to the nearest cent (may be zero or negative).
    Raises:
        ValueError: If the input is not a plain finite number (``money.MoneyError`` is a ValueError).
    """
    return parse_cents(raw)


def require_rows(query: str, params: tuple) -> tuple:
    """
    Mark a statement for ``_execute_transaction`` as one that must change exactly one row.
    A guarded debit such as ``UPDATE ... WHERE wallet >= ?`` that matches no rows is not
    a SQL error, so without this the rest of the transaction would still commit.
    Args:
        query (str): SQL statement.
        params (tuple): Parameters for the statement.
    Returns:
        tuple: ``(query, params, 1)`` for use in ``_execute_transaction``.
    """
    return (query, params, 1)


def _execute_transaction(conn, queries_and_params: list, result: dict = None) -> bool:
    """
    Execute multiple queries in a single, atomic transaction.
    Args:
        conn (sqlite3.Connection): Active database connection.
        queries_and_params (list): List of (query: str, params: tuple) pairs, or
            (query, params, expected_rowcount) triples (``require_rows`` makes one).
            If a statement affects a different number of rows than expected (e.g. a
            guarded debit matched nothing), the whole transaction is rolled back.
        result (dict, optional): If given, ``result["lastrowid"]`` is set to the
            ID of the last row inserted by this transaction.
    Returns:
        bool: True on success, False on failure (with automatic rollback).
    """
    try:
        cur = conn.cursor()
        lastrowid = None
        for entry in queries_and_params:
            query, params = entry[0], entry[1]
            cur.execute(query, params)
            if len(entry) > 2 and cur.rowcount != entry[2]:
                print(f"Transaction aborted, expected {entry[2]} row(s), got {cur.rowcount}: {query}")
                conn.rollback()
                return False
            if query.lstrip().upper().startswith("INSERT"):
                lastrowid = cur.lastrowid
        conn.commit()
        if result is not None:
            result["lastrowid"] = lastrowid
        return True
    except Exception as e:
        print(f"Transaction failed, rolling back: {e}")
        conn.rollback()
        return False

# --- Wallet ledger helpers (M2) ------------------------------------------------
# Wallet balances live in the double-entry ledger (ledger.py), not in the old
# User.wallet column. session['Wallet'] is only a display copy and is refreshed
# from the ledger after every money operation; it is never used to decide
# whether a user can pay.

_LEDGER_READY = set()


def _ledger_ready(conn):
    """Create the ledger tables in the current database if needed (once per file)."""
    if db_file not in _LEDGER_READY:
        ledger.ensure_schema(conn)
        _LEDGER_READY.add(db_file)


def _wallet_cents(conn, usr_id) -> int:
    """A user's wallet balance in cents, read from the ledger."""
    _ledger_ready(conn)
    return ledger.wallet_balance(conn, usr_id)


def _refresh_session_wallet(conn, usr_id) -> int:
    """Copy the user's ledger balance into session['Wallet'] for display."""
    session['Wallet'] = _wallet_cents(conn, usr_id)
    return session['Wallet']


def _new_request_key(kind: str) -> str:
    """A unique idempotency key for one money request."""
    return f"{kind}:{uuid.uuid4().hex}"


_CLIENT_KEY_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


def _request_key(kind: str, usr_id, client_key) -> str:
    """
    Idempotency key for a money request (M2). Every money form and the order
    pages send a one-time key; sending the same request again with the same key
    (a double-clicked "Pay", a refreshed form) is recognised by the ledger and
    charges only once. The key is scoped to the user, so one user can never
    collide with or replay another user's key. Requests without a valid key
    get a fresh one (no double-click protection, but they still work).
    """
    if isinstance(client_key, str) and _CLIENT_KEY_RE.fullmatch(client_key):
        return f"{kind}:{int(usr_id)}:{client_key}"
    return _new_request_key(kind)


def _refunded_txn_ids(conn) -> set:
    """IDs of ledger transactions that have been reversed (refunded)."""
    return {r[0] for r in conn.execute(
        'SELECT reverses_txn_id FROM "LedgerTransaction" WHERE reverses_txn_id IS NOT NULL')}


_TXN_LABELS = {
    "topup": "Wallet top-up",
    "gift": "Gift",
    "order": "Order",
    "refund": "Refund",
    "opening_balance": "Opening balance",
}


def _wallet_history(conn, usr_id, limit=25) -> list:
    """
    A user's most recent wallet transactions for the profile page, newest first.
    Returns:
        list[dict]: txn_id, date, description, amount (signed display string),
        amount_cents and credit (True when money came in).
    """
    _ledger_ready(conn)
    rows = []
    for h in ledger.history(conn, ledger.user_account(usr_id), limit=limit):
        try:
            when = datetime.fromisoformat(h["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            when = h["created_at"] or ""
        cents = h["amount_cents"]
        rows.append({
            "txn_id": h["txn_id"],
            "date": when,
            "description": h["memo"] or _TXN_LABELS.get(h["kind"], h["kind"]),
            "amount": ("+" if cents > 0 else "-") + format_cents(abs(cents)),
            "amount_cents": cents,
            "credit": cents > 0,
        })
    return rows


def _order_id_for_txn(conn, usr_id, txn_id):
    """Find the order a ledger transaction paid for (used when a request is replayed)."""
    for ord_id, details in fetch_all(
        conn, 'SELECT ord_id, details FROM "Order" WHERE usr_id = ? ORDER BY ord_id DESC LIMIT 200',
        (usr_id,),
    ):
        try:
            if json.loads(details or "{}").get("ledger_txn_id") == txn_id:
                return ord_id
        except (TypeError, ValueError):
            continue
    return None


def _charge_and_save_order(usr_id, rtr_id, restaurant_name, details, client_key=None):
    """
    Pay for an order from the user's wallet and save it, all or nothing.
    The payment is one ledger transaction split into restaurant (food + tip),
    tax and fee accounts; the order row is inserted inside that same database
    transaction, so an order is never saved without being paid for.
    Args:
        usr_id (int): Buyer.
        rtr_id (int): Restaurant.
        restaurant_name (str): Used in the transaction-history memo.
        details (dict): Order details including "charges_cents" (int cents, see
            charges.py). The ledger transaction ID is added to it as "ledger_txn_id".
        client_key (str, optional): The page's one-time idempotency key. Sending
            the same order again with the same key returns the original order
            instead of charging twice.
    Returns:
        tuple: (ord_id, None) on success, or (None, error) where error is
        "insufficient_funds", "duplicate_request" (key reused for a different
        order) or "db_failed".
    """
    charges = details["charges_cents"]
    subtotal = charges["subtotal"]
    tax = charges["tax"]
    delivery_fee = charges["delivery_fee"]
    service_fee = charges["service_fee"]
    tip = charges["tip"]
    total = charges["total"]

    entries = [
        (ledger.user_account(usr_id), -total),
        (ledger.restaurant_account(rtr_id), subtotal + tip),
        ("tax", tax),
        ("fees:delivery", delivery_fee),
        ("fees:service", service_fee),
    ]
    entries = [(account, cents) for account, cents in entries if cents]

    def save_order(cur, txn_id):
        details["ledger_txn_id"] = txn_id
        cur.execute(
            'INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, ?, ?)',
            (rtr_id, usr_id, json.dumps(details), OrderStatus.ORDERED.value),
        )
        return cur.lastrowid

    conn = create_connection(db_file)
    try:
        _ledger_ready(conn)
        ledger.open_legacy_wallet(conn, usr_id)
        try:
            result = ledger.post_transaction(
                conn, "order", entries, _request_key("order", usr_id, client_key),
                memo=f"Order at {restaurant_name}", after=save_order,
            )
        except ledger.InsufficientFunds:
            return None, "insufficient_funds"
        except ledger.IdempotencyConflict:
            return None, "duplicate_request"
        except ledger.LedgerError as e:
            print(f"Order payment failed: {e}")
            return None, "db_failed"
        finally:
            _refresh_session_wallet(conn, usr_id)
        if not result.created:   # same request again: return the order it already paid for
            return _order_id_for_txn(conn, usr_id, result.txn_id), None
        return result.extra, None
    finally:
        close_connection(conn)


def parse_generated_menu(gen_str):
    """
    Parse a serialized generated-menu string into a date-indexed structure.
    Args:
        gen_str (str): A string like "[YYYY-MM-DD,ID,(meal),(order)]..." where meal is 1|2|3
            (optional) and order (M4, optional) tags meals planned as one order: "o<n>" for a
            batched delivery, "p<n>" for a pickup.
    Returns:
        dict: Mapping 'YYYY-MM-DD' -> [{'itm_id': int, 'meal': int}, ...]. Tagged meals also
        carry 'order': the tag.
    """
    if not gen_str:
        return {}

    # date, id, optional meal (1,2,3), optional order tag (M4)
    pairs = re.findall(
        r'\[\s*(\d{4}-\d{2}-\d{2})\s*,\s*([0-9]+)\s*(?:,\s*([123])\s*(?:,\s*([op][0-9]+)\s*)?)?\]', gen_str)
    out = {}
    for d, mid, meal, tag in pairs:
        try:
            itm_id = int(mid)
            meal_i = int(meal) if meal else 3  # default to Dinner for legacy entries
            entry = {'itm_id': itm_id, 'meal': meal_i}
            if tag:
                entry['order'] = tag
            out.setdefault(d, []).append(entry)
        except ValueError:
            continue
    return out

def palette_for_item_ids(item_ids):
    """
    Generate a deterministic, pleasant color palette for item IDs.
    Args:
        item_ids (Iterable[int]): The menu item IDs to colorize.
    Returns:
        dict: Mapping itm_id -> hex color string (e.g., '#a1b2c3').
    """
    import colorsys
    def hsl_to_hex(h, s, l):
        r, g, b = colorsys.hls_to_rgb(h/360.0, l/100.0, s/100.0)
        return '#%02x%02x%02x' % (int(r*255), int(g*255), int(b*255))
    palette = {}
    for iid in item_ids:
        seed = (iid * 9301 + 49297) % 233280
        hue = seed % 360
        palette[iid] = hsl_to_hex(hue, 65, 52)
    return palette

def fetch_menu_items_by_ids(ids):
    """
    Load menu items (and their restaurant metadata) for given item IDs.
    Args:
        ids (Iterable[int]): The item IDs to fetch.
    Returns:
        dict: Mapping itm_id -> dict with fields like name, price, calories, allergens,
            and restaurant info (name, address, hours, phone).
    """
    if not ids:
        return {}
    conn = create_connection(db_file)
    try:
        qmarks = ",".join(["?"] * len(ids))
        sql = f"""
          SELECT m.itm_id, m.rtr_id, m.name, m.description, m.price, m.calories,
                 m.allergens, r.name AS restaurant_name, r.address, r.city, r.state, r.zip,
                 r.hours, r.phone
          FROM MenuItem m
          JOIN Restaurant r ON r.rtr_id = m.rtr_id
          WHERE m.itm_id IN ({qmarks})
        """
        rows = fetch_all(conn, sql, tuple(ids))
    finally:
        close_connection(conn)

    def _addr(a, c, s, z) -> str:
        parts_raw = [a, c, s, z]
        parts = []
        for p in parts_raw:
            if p is None:
                continue
            sp = str(p).strip()
            if sp:
                parts.append(sp)
        return ", ".join(parts)

    def _fmt_hours(h_str) -> str:
        """Parses the JSON hours string into a readable format server-side."""
        if not h_str: return ""
        try:
            # Load JSON
            h_obj = json.loads(h_str)
            day_map = {"M": "Mon", "T": "Tue", "W": "Wed", "Th": "Thu", "F": "Fri", "Sa": "Sat", "Su": "Sun"}
            order = ["M", "T", "W", "Th", "F", "Sa", "Su"]
            
            lines = []
            for k in order:
                times = h_obj.get(k)
                if times and len(times) >= 2:
                    # Convert 1700 -> 5:00 PM
                    ranges = []
                    for i in range(0, len(times), 2):
                        if i+1 < len(times):
                            start, end = times[i], times[i+1]
                            
                            def to_time(v):
                                h = v // 100
                                m = v % 100
                                ampm = "AM"
                                if h >= 12: ampm = "PM"
                                if h > 12: h -= 12
                                if h == 0: h = 12
                                return f"{h}:{m:02d} {ampm}"
                            
                            ranges.append(f"{to_time(start)}–{to_time(end)}")
                    
                    if ranges:
                        lines.append(f"{day_map.get(k, k)}: {', '.join(ranges)}")
            return " · ".join(lines)
        except Exception:
            # Fallback if not JSON
            return str(h_str)

    out = {}
    for r in rows:
        out[r[0]] = {
            "itm_id": r[0],
            "rtr_id": r[1],
            "name": r[2],
            "description": r[3],
            "price": r[4],
            "calories": r[5],
            "allergens": r[6],
            "restaurant_name": r[7],
            "restaurant_address": _addr(r[8], r[9], r[10], r[11]),
            "restaurant_hours": _fmt_hours(r[12]), # <--- NOW FORMATTED IN PYTHON
            "restaurant_phone": r[13] or "",
        }
    return out


def build_calendar_cells(gen_map, year, month, items_by_id, today=None, fees=DEFAULT_FEES):
    """
    Build month-view calendar cells enriched with menu items per day.
    Args:
        gen_map (dict): Mapping 'YYYY-MM-DD' -> [{'itm_id': int, 'meal': 1|2|3}, ...].
        year (int): The calendar year.
        month (int): The calendar month (1–12).
        items_by_id (dict): Mapping itm_id -> item detail dict from DB.
        today (date | None): The current date (defaults to date.today()); days before it are past.
        fees (FeeSchedule): Tax and each restaurant's fees (M4).
    Returns:
        list: A flat list of calendar cell dicts with day number and a 'meals' list. Days of
            the month also carry 'is_past', 'kcal' (calories planned that day), 'cost_cents'
            (what the day's meals cost, tax and fees included, as the planner counts it),
            'orders' (the meals grouped into orders: meals the planner batched share one,
            each order with its fees), 'fees_cents' and 'fee_savings_cents' (against
            ordering every meal separately for delivery).
    """
    today = today or date.today()
    def meal_sort_key(e):
        # Breakfast(1) first, then Lunch(2), then Dinner(3)
        return e.get('meal', 3)

    palette = palette_for_item_ids(items_by_id.keys())
    cal = calendar.Calendar(firstweekday=6)  # Sunday start
    cells = []

    for week in cal.monthdayscalendar(year, month):
        for d in week:
            if d == 0:
                cells.append({"day": 0})
                continue

            iso = f"{year:04d}-{month:02d}-{d:02d}"
            entries = sorted(gen_map.get(iso, []), key=meal_sort_key)

            meals = []
            for e in entries:
                itm = items_by_id.get(e['itm_id'])
                if not itm:
                    continue
                meals.append({
                    "meal": e.get('meal', 3),
                    "item": itm,
                    "color": palette.get(itm['itm_id'], "#7aa2f7"),
                    "order_tag": e.get('order'),
                })
            orders = calendar_day_orders(meals, fees)
            food = sum(o["food_cents"] for o in orders)

            cells.append({
                "day": d,
                # Past days are still shown (as history) but can no longer be ordered
                "is_past": date(year, month, d) < today,
                "meals": meals,
                "kcal": sum(m["item"].get("calories") or 0 for m in meals),
                "cost_cents": food + sum(o["fee_cents"] for o in orders),
                "orders": orders,
                "fees_cents": sum(o["fee_cents"] for o in orders),
                "fee_savings_cents": sum(o["separate_fee_cents"] - o["fee_cents"] for o in orders),
            })

    return cells


def calendar_day_orders(meals, fees=DEFAULT_FEES):
    """
    Group one day's calendar meals into orders (M4). Meals sharing an order tag from the
    planner, all from one restaurant, are one order; every other meal is its own order. A
    "p" tag means pickup (no delivery fee).
    Args:
        meals (list): The day's meal dicts from build_calendar_cells ('meal', 'item', 'order_tag').
        fees (FeeSchedule): Tax and each restaurant's fees.
    Returns:
        list[dict]: Orders in meal order, each with 'meals', 'rtr_id', 'restaurant_name',
        'pickup', 'batched', 'food_cents' (prices + tax), 'fee_cents', 'separate_fee_cents'
        (fees if each meal were its own delivery order) and 'subtotal_cents'.
    """
    groups = {}
    for m in meals:
        tag = m.get("order_tag")
        key = ("tag", tag) if tag else ("meal", id(m))
        groups.setdefault(key, []).append(m)
    orders = []
    for (kind, tag), group in groups.items():
        rtr_ids = {int(m["item"].get("rtr_id") or 0) for m in group}
        if len(rtr_ids) > 1:  # a tag across restaurants is not a valid order: price separately
            orders.extend(calendar_day_orders([{**m, "order_tag": None} for m in group], fees))
            continue
        rtr_id = rtr_ids.pop()
        pickup = kind == "tag" and str(tag).startswith("p")
        prices = [int(m["item"].get("price") or 0) for m in group]
        for m in group:  # for the calendar badges and per-meal order buttons
            m["batched"] = len(group) > 1
            m["pickup"] = pickup
        orders.append({
            "meals": group,
            "rtr_id": rtr_id,
            "restaurant_name": group[0]["item"].get("restaurant_name") or "",
            "pickup": pickup,
            "batched": len(group) > 1,
            "subtotal_cents": sum(prices),
            "food_cents": sum(p + fees.tax_cents(p) for p in prices),
            "fee_cents": fees.order_fee_cents(rtr_id, pickup=pickup),
            "separate_fee_cents": len(group) * fees.order_fee_cents(rtr_id),
            "delivery_fee_cents": 0 if pickup else fees.for_restaurant(rtr_id).delivery_fee_cents,
            "restaurant_delivery_fee_cents": fees.for_restaurant(rtr_id).delivery_fee_cents,
            "service_fee_cents": fees.for_restaurant(rtr_id).service_fee_cents,
        })
    return sorted(orders, key=lambda o: min(m["meal"] for m in o["meals"]))


def _is_restaurant_reviewed(conn, usr_id: int, rtr_id: int) -> bool:
    """Check if the user has already submitted a review for this specific restaurant."""
    # Checks the existing schema: Review(rev_id, rtr_id, usr_id, title, rating, description)
    sql = 'SELECT 1 FROM "Review" WHERE usr_id = ? AND rtr_id = ?'
    return fetch_one(conn, sql, (usr_id, rtr_id)) is not None

# ---------------------- Routes ----------------------

# Calendar years the home view will render. Kept well inside date's 1..9999 range so the
# prev/next month navigation can never step outside it.
CALENDAR_MIN_YEAR, CALENDAR_MAX_YEAR = 2000, 2100

# Home route (supports /<year>/<month> for nav)
@app.route('/', defaults={'year': None, 'month': None})
@app.route('/<int:year>/<int:month>')
def index(year, month):
    """
    Render the calendar home view for the current or specified month.
    Args:
        year (int | None): Optional year path parameter.
        month (int | None): Optional month path parameter (1–12).
    Returns:
        Response: HTML page showing the monthly plan and today's meals (requires login).
    """
    if session.get("Username") is None:
        return redirect(url_for("login"))

    today = date.today()
    # Only the bare "/" route omits year/month. Explicit values are validated rather than
    # truthiness-checked, so /2026/0 and /2026/13 are both rejected the same way.
    if year is None or month is None:
        year, month = today.year, today.month
    elif not (1 <= month <= 12 and CALENDAR_MIN_YEAR <= year <= CALENDAR_MAX_YEAR):
        abort(404)

    # Load current user's generated_menu
    conn = create_connection(db_file)
    try:
        user = fetch_one(conn, 'SELECT * FROM "User" WHERE email = ?', (session.get("Email"),))
        fee_schedule = load_fee_schedule(conn)
    finally:
        close_connection(conn)

    if not user:
        return redirect(url_for("logout"))

    gen_str = user[9] if len(user) > 9 else ""
    gen_map = parse_generated_menu(gen_str)

    # All item ids referenced (for the whole plan)
    all_item_ids = sorted({e['itm_id'] for entries in gen_map.values() for e in entries})
    items_by_id = fetch_menu_items_by_ids(all_item_ids)

    # Build cells for the month
    cells = build_calendar_cells(gen_map, year, month, items_by_id, today=today, fees=fee_schedule)
    month_cost_cents = sum(c.get("cost_cents", 0) for c in cells)
    month_fees_cents = sum(c.get("fees_cents", 0) for c in cells)
    month_fee_savings_cents = sum(c.get("fee_savings_cents", 0) for c in cells)
    planned_days = [c for c in cells if c.get("meals")]
    month_avg_kcal = round(sum(c["kcal"] for c in planned_days) / len(planned_days)) if planned_days else 0

    # Build "today_menu" (Breakfast, Lunch, Dinner if present)
    today_iso = f"{today.year:04d}-{today.month:02d}-{today.day:02d}"
    today_entries = sorted(gen_map.get(today_iso, []), key=lambda e: e.get('meal', 3))
    today_menu = []
    for e in today_entries:
        item = items_by_id.get(e['itm_id'])
        if item:
            # expose 'meal' and the full item dict to the template
            today_menu.append(type("TodayEntry", (), {"meal": e['meal'], "item": item}))

    # prev/next month nav (unchanged)
    cur = date(year, month, 15)
    prev_m = (cur.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_m = (cur.replace(day=28) + timedelta(days=10)).replace(day=1)

    return render_template(
        "index.html",
        username=session["Username"],
        month_name=calendar.month_name[month],
        month=month,
        year=year,
        prev_month=prev_m.month,
        prev_year=prev_m.year,
        next_month=next_m.month,
        next_year=next_m.year,
        # Hide nav links that would lead outside the renderable range (and so 404)
        has_prev=prev_m.year >= CALENDAR_MIN_YEAR,
        has_next=next_m.year <= CALENDAR_MAX_YEAR,
        calendar_cells=cells,
        month_cost_cents=month_cost_cents,
        month_fees_cents=month_fees_cents,
        month_fee_savings_cents=month_fee_savings_cents,
        tax_rate=str(fee_schedule.tax_rate),
        month_avg_kcal=month_avg_kcal,
        today_year=today.year,
        today_month=today.month,
        today_day=today.day,
        today_menu=today_menu,
    )

# Login route
@app.route('/login', methods=['GET','POST'])
def login():
    """
    Display the login form (GET) and authenticate user credentials (POST).
    Args:
        None
    Returns:
        Response: Renders login page, or redirects to home on successful login.
    """
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        conn = create_connection(db_file)
        try:
            user = fetch_one(conn, 'SELECT * FROM "User" WHERE email = ?', (email,))
        finally:
            close_connection(conn)

        if user and check_password_hash(user[5], password):
            session["usr_id"] = user[0] 
            session["Fname"] = user[1]
            session["Lname"] = user[2]
            session["Username"] = user[1] + " " + user[2]
            session["Email"] = email
            session["Phone"] = user[4]
            conn = create_connection(db_file)
            try:
                session["Wallet"] = _wallet_cents(conn, user[0])
            finally:
                close_connection(conn)
            session["Preferences"] = user[7] if len(user) > 7 else ""
            session["Allergies"] = user[8] if len(user) > 8 else ""
            session["GeneratedMenu"] = user[9] if len(user) > 9 else ""
            session["is_admin"] = bool(user[10]) if len(user) > 10 else False
            session.permanent = True
            app.permanent_session_lifetime = timedelta(minutes=30)
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

# Logout route (single, no duplicates)
@app.route('/logout')
def logout():
    """
    Clear the user session and redirect to the login page.
    Args:
        None
    Returns:
        Response: Redirect to the login route.
    """
    for k in ["Username","Fname","Lname","Email","Phone","Wallet","Preferences","Allergies","GeneratedMenu","is_admin","usr_id"]:
        session.pop(k, None)
    return redirect(url_for("login"))

PHONE_ERROR = "Please enter a valid phone number"

def _normalize_phone(raw):
    """
    Normalize a user-entered phone number to its digits, as stored in "User".phone.
    Shared by /register and /profile/edit so both accept and store phones the same way.
    Args:
        raw (str | None): The phone number as entered, e.g. "(919) 555-0123".
    Returns:
        str | None: The digits (e.g. "9195550123") if there are at least 7, else None.
    """
    digits = re.sub(r"\D+", "", raw or "")
    return digits if len(digits) >= 7 else None

# Registration route
@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Display the registration form (GET) and create a new user (POST).
    Args:
        None
    Returns:
        Response: Renders registration page or redirects to login on success.
    """
    if request.method == 'POST':
        fname = (request.form.get('fname') or '').strip()
        lname = (request.form.get('lname') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        phone = (request.form.get('phone') or '').strip()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        allergies = (request.form.get('allergies') or '').strip()
        preferences = (request.form.get('preferences') or '').strip()

        # Basic validations
        if not fname or not lname:
            return render_template('register.html', error="First and last name are required")
        if not email or not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            return render_template('register.html', error="Please enter a valid email address")
        if password != confirm_password:
            return render_template('register.html', error="Passwords do not match")
        if len(password) < 6:
            return render_template('register.html', error="Password must be at least 6 characters")

        digits_only = _normalize_phone(phone)
        if digits_only is None:
            return render_template('register.html', error=PHONE_ERROR)
        # Allergies drive meal-plan filtering, so only accept allergens the filter understands
        unknown = invalid_allergies(allergies)
        if unknown:
            return render_template('register.html', error=f"Unknown allergy: {', '.join(unknown)}")

        conn = create_connection(db_file)
        try:
            exists = fetch_one(conn, 'SELECT 1 FROM "User" WHERE email = ?', (email,))
            if exists:
                return render_template('register.html', error="Email already registered")

            password_hashed = generate_password_hash(password)

            # Insert WITHOUT generated_menu (your LLM will populate it later)
            execute_query(
                conn,
                """
                INSERT INTO "User"
                    (first_name, last_name, email, phone, password_HS, wallet, preferences, allergies)
                VALUES
                    (?,          ?,         ?,     ?,     ?,           ?,      ?,            ?)
                """,
                (fname, lname, email, digits_only, password_hashed, 0, preferences, allergies)
            )
        except IntegrityError:
            return render_template('register.html', error="Email already registered")
        finally:
            close_connection(conn)

        return redirect(url_for('login'))

    return render_template('register.html')

# Profile route
@app.route('/profile')
def profile():
    """
    Show the logged-in user's profile, including recent orders.
    Args:
        None
    Returns:
        Response: HTML profile page (requires login).
    """
    # Must be logged in
    if session.get('Username') is None:
        return redirect(url_for('login'))

    # Load the full user row by session email
    email = session.get('Email')
    if not email:
        return redirect(url_for('logout'))

    import json
    from datetime import datetime

    def _fmt_date(iso_str: str) -> str:
        if not iso_str:
            return ""
        try:
            # Handles "2025-10-18T18:22:00-04:00" style strings
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return iso_str  # if it’s not ISO, show raw

    def _fmt_total(val) -> str:
        try:
            return f"${float(val):.2f}"
        except Exception:
            return ""

    conn = create_connection(db_file)
    try:
        row = fetch_one(conn, 'SELECT usr_id,first_name,last_name,email,phone,password_HS,wallet,preferences,allergies,daily_calorie_target,weekly_budget_cents FROM "User" WHERE email = ?', (email,))
        if not row:
            return redirect(url_for('logout'))

        user = {
            "usr_id":        row[0],
            "first_name":    row[1],
            "last_name":     row[2],
            "email":         row[3],
            "phone":         row[4],
            "password_HS":   row[5],
            "wallet":        cents_to_str(_wallet_cents(conn, row[0])),
            "preferences":   row[7] or "",
            "allergies":     row[8] or "",
            "daily_calorie_target": row[9],
            "weekly_budget": format_budget(row[10]),
        }

        session['usr_id'] = user["usr_id"]

        # Pull orders for this user; details is JSON we will parse
        order_rows = fetch_all(
            conn,
            '''
            SELECT o.ord_id, o.details, o.status, r.name, r.rtr_id
            FROM "Order" o
            JOIN "Restaurant" r ON o.rtr_id = r.rtr_id
            WHERE o.usr_id = ?
            ORDER BY o.ord_id DESC
            ''',
            (user["usr_id"],)
        )

        # Fetch all existing restaurant reviews for this user in one go
        reviewed_restaurant_rows = fetch_all(conn, 'SELECT DISTINCT rtr_id FROM "Review" WHERE usr_id = ?', (user["usr_id"],))
        reviewed_rtr_ids = {r[0] for r in reviewed_restaurant_rows}

        _ledger_ready(conn)
        refunded_txns = _refunded_txn_ids(conn)
        wallet_history = _wallet_history(conn, user["usr_id"])

        orders = []
        for ord_id, details, status, r_name, rtr_id in order_rows:
            placed = ""
            total = ""
            ledger_txn_id = None
            if details:
                try:
                    j = json.loads(details)
                    ledger_txn_id = j.get("ledger_txn_id")
                    placed = _fmt_date(j.get("placed_at") or j.get("time"))
                    if j.get("charges_cents") or j.get("charges"):
                        total = format_cents(order_charges_cents(j)["total"])
                except Exception:
                    pass

            # New logic to determine reviewability (Delivered AND Restaurant not yet reviewed)
            is_delivered = (status or "").lower() == OrderStatus.DELIVERED.get_lowercase()
            is_reviewed = rtr_id in reviewed_rtr_ids
            is_reviewable = is_delivered and not is_reviewed

            # If reviewable, add the restaurant to the set so subsequent orders from it are marked as 'Reviewed'
            if is_reviewable:
                 reviewed_rtr_ids.add(rtr_id)
            # Re-check the reviewed status after the potential update. This handles orders from the same restaurant correctly.
            is_reviewed_final = rtr_id in reviewed_rtr_ids and not is_reviewable

            orders.append({
                "id": ord_id,
                "date": placed,
                "status": status or "",
                "restaurant": r_name,
                "rtr_id": rtr_id,
                "total": total,
                "is_reviewable": is_reviewable,
                "is_reviewed": is_reviewed_final, # <-- CORRECTED: Use the final state for display
                "refunded": ledger_txn_id in refunded_txns,
            })

        # Fetch user's support tickets with order details
        # Join with Order table to get order information
        # Sort by created_at descending (newest first)
        ticket_rows = fetch_all(
            conn,
            '''
            SELECT t.ticket_id, t.ord_id, t.message, t.response, t.status, 
                   t.created_at, t.updated_at, o.details
            FROM Ticket t
            JOIN "Order" o ON t.ord_id = o.ord_id
            WHERE t.usr_id = ?
            ORDER BY t.created_at DESC
            ''',
            (user["usr_id"],)
        )

        # Build tickets list
        tickets = []
        for ticket_row in ticket_rows:
            ticket_id, ord_id, message, response, status, created_at, updated_at, order_details = ticket_row
            
            # Format the created_at timestamp
            formatted_created = _fmt_date(created_at) if created_at else ""
            
            tickets.append({
                "ticket_id": ticket_id,
                "ord_id": ord_id,
                "message": message,
                "response": response,
                "status": status,
                "created_at": formatted_created,
                "updated_at": updated_at
            })
    finally:
        close_connection(conn)

    pw_updated = request.args.get('pw_updated')
    pw_error   = request.args.get('pw_error')

    return render_template(
        "profile.html",
        user=user,
        orders=orders,
        tickets=tickets,
        pw_updated=pw_updated,
        pw_error=pw_error,
        topup_key=uuid.uuid4().hex,
        gift_key=uuid.uuid4().hex,
        wallet_history=wallet_history,
    )

# Delivery & fee settings (M4)
@app.route('/profile/fees', methods=['GET', 'POST'])
def fee_settings():
    """
    Show and save the user's fee settings for planning: batching (meals from one restaurant
    at most 6 h apart share a delivery) and pickup (no delivery fee) at chosen restaurants on
    chosen days. Used by /generate_plan.
    Returns:
        Response: The settings page; after a successful save, a redirect back to it.
    """
    usr_id = session.get("usr_id")
    if not usr_id:
        return redirect(url_for("login"))
    conn = create_connection(db_file)
    try:
        fee_schedule = load_fee_schedule(conn)
        rows = fetch_all(conn, 'SELECT rtr_id, name, status FROM "Restaurant" ORDER BY name')
        restaurants = [
            {"rtr_id": r, "name": n or f"Restaurant {r}",
             "open": (st or "").strip().lower() == "open",
             "delivery_fee_cents": fee_schedule.for_restaurant(r).delivery_fee_cents,
             "service_fee_cents": fee_schedule.for_restaurant(r).service_fee_cents}
            for r, n, st in rows
        ]
        error = None
        if request.method == "POST":
            known = {r["rtr_id"] for r in restaurants}
            try:
                chosen = [int(x) for x in request.form.getlist("pickup_restaurants")]
                if not set(chosen) <= known:
                    raise ValueError("unknown restaurant")
                prefs = FeePrefs(
                    batching=request.form.get("batching") == "on",
                    pickup_restaurants=tuple(chosen),
                    pickup_days=tuple(request.form.getlist("pickup_days")),
                )
            except ValueError:
                error = "Those settings are not valid. Pick restaurants and days from the lists."
                prefs = load_fee_prefs(conn, usr_id)
            else:
                save_fee_prefs(conn, usr_id, prefs)
                return redirect(url_for("fee_settings", saved=1))
        else:
            prefs = load_fee_prefs(conn, usr_id)
    finally:
        close_connection(conn)
    return render_template(
        "fee_settings.html",
        prefs=prefs,
        restaurants=restaurants,
        weekdays=WEEKDAYS,
        saved=request.args.get("saved"),
        error=error,
        default_order_fee_cents=fee_schedule.order_fee_cents(),
    ), (400 if error else 200)


# Edit Profile route
@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    """
    Display and process the profile edit form (phone, preferences, allergies, and the
    planner's daily calorie target and weekly budget).
    Args:
        None
    Returns:
        Response: Renders form (GET) or updates and redirects to profile (POST). A calorie
        target or budget that fails validation re-renders the form with the error and
        status 400, and nothing is saved.
    """
    if session.get('Username') is None:
        return redirect(url_for('login'))

    usr_id = session.get('usr_id')
    if not usr_id:
        return redirect(url_for('logout'))

    conn = create_connection(db_file)
    try:
        row = fetch_one(conn, '''
            SELECT usr_id, first_name, last_name, email, phone, wallet, preferences, allergies,
                   daily_calorie_target, weekly_budget_cents
            FROM "User" WHERE usr_id = ?
        ''', (usr_id,))
        wallet_cents = _wallet_cents(conn, row[0]) if row else 0
    finally:
        close_connection(conn)

    if not row:
        return redirect(url_for('logout'))

    user = {
        "usr_id": row[0],
        "first_name": row[1],
        "last_name": row[2],
        "email": row[3],
        "phone": row[4],
        "wallet": cents_to_str(wallet_cents),
        "preferences": row[6] or "",
        "allergies": row[7] or "",
        "daily_calorie_target": row[8],
        "weekly_budget_cents": row[9],
    }
    # What the target inputs show: the stored values, or on a failed submit what was typed.
    targets = {
        "daily_calorie_target": "" if row[8] is None else str(row[8]),
        "weekly_budget": format_budget(row[9]),
    }

    # For now just render an edit form (you can build edit_profile.html)
    if request.method == 'POST':
        # You’ll expand this with update logic later
        # Example: update phone, preferences, allergies
        # Phone is required at registration, so an empty value keeps the stored one. Preferences
        # and allergies can be cleared: only fall back when the field is absent, not when it is "".
        raw_phone = (request.form.get('phone') or '').strip()
        new_prefs = (request.form.get('preferences', user['preferences']) or '').strip()
        new_allergies = (request.form.get('allergies', user['allergies']) or '').strip()

        # Validate and store phones exactly as /register does (digits only)
        error = None
        if raw_phone:
            new_phone = _normalize_phone(raw_phone)
            if new_phone is None:
                error = PHONE_ERROR
        else:
            new_phone = user['phone']

        # Allergies drive meal-plan filtering, so only accept allergens the filter understands
        unknown = invalid_allergies(new_allergies)
        if unknown and error is None:
            error = f"Unknown allergy: {', '.join(unknown)}"

        # Planner targets: a field left out of the form keeps its value; a blank one clears it.
        new_kcal = user['daily_calorie_target']
        new_budget_cents = user['weekly_budget_cents']
        errors = {}
        if 'daily_calorie_target' in request.form:
            targets['daily_calorie_target'] = request.form['daily_calorie_target']
            try:
                new_kcal = parse_daily_calorie_target(request.form['daily_calorie_target'])
            except TargetError as e:
                errors['daily_calorie_target'] = str(e)
        if 'weekly_budget' in request.form:
            targets['weekly_budget'] = request.form['weekly_budget']
            try:
                new_budget_cents = parse_weekly_budget(request.form['weekly_budget'])
            except TargetError as e:
                errors['weekly_budget'] = str(e)
        if error or errors:
            return render_template(
                "edit_profile.html", user=user, targets=targets, errors=errors, error=error
            ), 400

        conn = create_connection(db_file)
        try:
            execute_query(conn, '''
                UPDATE "User"
                SET phone = ?, preferences = ?, allergies = ?,
                    daily_calorie_target = ?, weekly_budget_cents = ?
                WHERE usr_id = ?
            ''', (new_phone, new_prefs, new_allergies, new_kcal, new_budget_cents, usr_id))
        finally:
            close_connection(conn)

        # Refresh session values
        session['Phone'] = new_phone
        session['Preferences'] = new_prefs
        session['Allergies'] = new_allergies

        return redirect(url_for('profile'))

    return render_template("edit_profile.html", user=user, targets=targets, errors={})

@app.route('/profile/change-password', methods=['POST'])
def change_password():
    """
    Change the current user's password after validating the current password.
    Args:
        None
    Returns:
        Response: Redirect back to profile with success or error flags.
    """
    # Must be logged in
    if session.get('Username') is None:
        return redirect(url_for('login'))

    usr_id = session.get('usr_id')
    if not usr_id:
        # Fallback: resolve via email
        email = session.get('Email')
        if not email:
            return redirect(url_for('logout'))
        conn = create_connection(db_file)
        try:
            row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))
            if not row:
                return redirect(url_for('logout'))
            usr_id = row[0]
            session['usr_id'] = usr_id
        finally:
            close_connection(conn)

    # Read form fields. Passwords are not stripped, matching /register and /login: spaces are
    # part of the password, and stripping them here would hash a different value than was typed.
    current_password = request.form.get('current_password') or ''
    new_password     = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    # Basic validations (mirror your frontend behavior)
    if not current_password:
        return redirect(url_for('profile', pw_error='missing_current'))
    if len(new_password) < 6:
        return redirect(url_for('profile', pw_error='too_short'))
    if new_password != confirm_password:
        return redirect(url_for('profile', pw_error='mismatch'))
    if new_password == current_password:
        return redirect(url_for('profile', pw_error='same_as_current'))

    # Verify current hash & update to new hash
    conn = create_connection(db_file)
    try:
        row = fetch_one(conn, 'SELECT password_HS FROM "User" WHERE usr_id = ?', (usr_id,))
        if not row:
            return redirect(url_for('logout'))

        stored_hash = row[0]
        if not check_password_hash(stored_hash, current_password):
            # wrong current password
            return redirect(url_for('profile', pw_error='incorrect_current'))

        # All good → update
        new_hash = generate_password_hash(new_password)
        execute_query(conn, 'UPDATE "User" SET password_HS = ? WHERE usr_id = ?', (new_hash, usr_id))

    finally:
        close_connection(conn)

    # Success
    return redirect(url_for('profile', pw_updated=1))

# Wallet Management Routes
@app.route('/profile/wallet/topup', methods=['POST'])
def wallet_topup():
    """
    Simulate adding funds to the user's wallet.
    """
    if session.get('usr_id') is None:
        return redirect(url_for('login'))

    try:
        amount_cents = parse_cents(request.form.get('amount'))
    except MoneyError:
        return redirect(url_for('profile', wallet_error='invalid_amount'))

    if amount_cents <= 0:
        return redirect(url_for('profile', wallet_error='zero_amount'))

    usr_id = session['usr_id']

    conn = create_connection(db_file)
    try:
        _ledger_ready(conn)
        ledger.open_legacy_wallet(conn, usr_id)
        try:
            ledger.post_transaction(
                conn, "topup",
                [(ledger.user_account(usr_id), amount_cents), ("external:topup", -amount_cents)],
                _request_key("topup", usr_id, request.form.get("idempotency_key")),
                memo="Wallet top-up",
            )
        except ledger.IdempotencyConflict:
            return redirect(url_for('profile', wallet_error='duplicate_request'))
        except ledger.LedgerError as e:
            print(f"Top-up failed: {e}")
            return redirect(url_for('profile', wallet_error='db_failed'))
        finally:
            _refresh_session_wallet(conn, usr_id)
        return redirect(url_for('profile', wallet_updated='topup'))
    finally:
        close_connection(conn)


@app.route('/profile/wallet/gift', methods=['POST'])
def wallet_gift():
    """
    Transfer funds from the logged-in user to another user by email.
    """
    if session.get('usr_id') is None:
        return redirect(url_for('login'))

    recipient_email = (request.form.get('recipient_email') or '').strip().lower()
    try:
        amount_cents = parse_cents(request.form.get('amount'))
    except MoneyError:
        return redirect(url_for('profile', wallet_error='invalid_amount'))

    sender_id = session['usr_id']

    if amount_cents <= 0:
        return redirect(url_for('profile', wallet_error='zero_amount'))
    if recipient_email == session.get('Email'):
        return redirect(url_for('profile', wallet_error='self_gift'))

    conn = create_connection(db_file)
    try:
        _ledger_ready(conn)
        recipient = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (recipient_email,))
        if not recipient:
            return redirect(url_for('profile', wallet_error='recipient_not_found'))
        recipient_id = recipient[0]
        if recipient_id == sender_id:
            return redirect(url_for('profile', wallet_error='self_gift'))

        ledger.open_legacy_wallet(conn, sender_id)
        ledger.open_legacy_wallet(conn, recipient_id)
        # The ledger checks the sender's balance while holding the database write
        # lock, so two gifts at once cannot both spend the same money (M2 bug 4).
        try:
            ledger.post_transaction(
                conn, "gift",
                [(ledger.user_account(sender_id), -amount_cents),
                 (ledger.user_account(recipient_id), amount_cents)],
                _request_key("gift", sender_id, request.form.get("idempotency_key")),
                memo=f"Gift from {session.get('Email')} to {recipient_email}",
            )
            outcome = {'wallet_updated': 'gift'}
        except ledger.InsufficientFunds:
            outcome = {'wallet_error': 'insufficient_funds'}
        except ledger.IdempotencyConflict:
            outcome = {'wallet_error': 'duplicate_request'}
        except ledger.LedgerError as e:
            print(f"Gift failed: {e}")
            outcome = {'wallet_error': 'db_failed'}

        _refresh_session_wallet(conn, sender_id)
        return redirect(url_for('profile', **outcome))
    finally:
        close_connection(conn)

# Review Submission Route (Restaurant-Level)
@app.route('/review/submit', methods=['POST'])
def submit_review():
    """Handles POST request to submit a restaurant-level review."""
    if session.get('usr_id') is None:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    # Validate the payload before touching the DB: missing/non-numeric fields are a 400, not a 500
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Invalid rating or restaurant ID"}), 400
    try:
        rtr_id = int(data.get('restaurant_id'))
        rating = int(data.get('rating'))
        ord_id = int(data.get('order_id')) # Required: the order must be delivered to allow a review
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid rating or restaurant ID"}), 400
    title = str(data.get('title') or '').strip()
    description = str(data.get('comment') or '').strip()

    if not (1 <= rating <= 5) or rtr_id <= 0 or ord_id <= 0:
        return jsonify({"ok": False, "error": "Invalid rating or restaurant ID"}), 400

    usr_id = session['usr_id']
    conn = create_connection(db_file)
    try:
        # 1. Verify the order was actually delivered to allow review submission
        order_row = fetch_one(conn, 'SELECT status FROM "Order" WHERE ord_id = ? AND usr_id = ? AND rtr_id = ?', (ord_id, usr_id, rtr_id))
        if not order_row or (order_row[0] or '').lower() != OrderStatus.DELIVERED.get_lowercase():
             return jsonify({"ok": False, "error": "Order not delivered or unauthorized"}), 403

        # 2. Check for existing review (prevent duplicate reviews for the same restaurant by the same user)
        if _is_restaurant_reviewed(conn, usr_id, rtr_id):
            return jsonify({"ok": False, "error": "Restaurant already reviewed"}), 409

        # 3. Insert the review into the existing Review table structure
        execute_query(
            conn,
            '''
            INSERT INTO "Review" (rtr_id, usr_id, title, rating, description)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (rtr_id, usr_id, title, rating, description)
        )

        return jsonify({"ok": True, "rtr_id": rtr_id}), 201
    except Exception as e:
        print(f"Review Submission Error: {e}")
        return jsonify({"ok": False, "error": "Server error during submission"}), 500
    finally:
        close_connection(conn)

# Order route (Calendar "Order" button target)
@app.route('/order', methods=['POST'])
def order():
    """
    Place an order via JSON POST, debiting the user's wallet atomically.
    Args:
        None
    Returns:
        Response: JSON with {'ok', 'ord_id'} on success, or {'ok': False, 'error'} on failure.
    """
    # Must be logged in
    if session.get("Username") is None:
        return redirect(url_for("login"))

    # Resolve usr_id strictly
    usr_id = session.get("usr_id")
    if not usr_id:
        conn = create_connection(db_file)
        try:
            row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (session.get('Email'),))
            if not row:
                return redirect(url_for("logout"))
            usr_id = row[0]
            session["usr_id"] = usr_id
        finally:
            close_connection(conn)

    # ---- POST JSON: place a single order containing ALL items in the restaurant group ----
    if request.method == 'POST' and request.is_json:
        payload = request.get_json(silent=True) or {}
        try:
            rtr_id = int(payload.get("restaurant_id") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_input"}), 400
        items_in = payload.get("items") or []     # [{itm_id, qty, notes}]
        delivery_type = (payload.get("delivery_type") or "delivery").lower()
        if delivery_type not in ("delivery", "pickup"):
            delivery_type = "delivery"
        try:
            tip_cents = parse_cents(payload.get("tip") or 0)
        except MoneyError:
            return jsonify({"ok": False, "error": "invalid_tip"}), 400
        # Reject negative tips (would credit the wallet); NaN/inf are rejected by parse_cents
        if tip_cents < 0:
            return jsonify({"ok": False, "error": "invalid_tip"}), 400
        eta_minutes = int(payload.get("eta_minutes") or 40)
        iso_date = (payload.get("date") or datetime.now().date().isoformat())
        try:
            meal = int(payload.get("meal") or 3)
        except Exception:
            meal = 3
        # M4: a batched order (meals the planner put in one delivery) lists every meal it covers.
        batch_meals = payload.get("meals")
        if batch_meals is not None:
            if (not isinstance(batch_meals, list) or not batch_meals
                    or any(type(x) is not int or x not in (1, 2, 3) for x in batch_meals)
                    or len(set(batch_meals)) != len(batch_meals)):
                return jsonify({"ok": False, "error": "invalid_meals"}), 400
            batch_meals = sorted(batch_meals)
            meal = batch_meals[0]

        if rtr_id <= 0 or not items_in:
            return jsonify({"ok": False, "error": "invalid_input"}), 400

        # The calendar sends the plan entry's date; never accept a malformed or past-dated order
        try:
            order_date = date.fromisoformat(str(iso_date))
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_date"}), 400
        if order_date < date.today():
            return jsonify({"ok": False, "error": "invalid_date"}), 400
        iso_date = order_date.isoformat()

        # Look up all items strictly from DB to get authoritative prices/names.
        # Any malformed or non-positive id rejects the whole request rather than being dropped.
        try:
            itm_ids = [int(it.get("itm_id")) for it in items_in]
        except (AttributeError, TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_item"}), 400
        if any(i <= 0 for i in itm_ids):
            return jsonify({"ok": False, "error": "invalid_item"}), 400

        conn = create_connection(db_file)
        try:
            qmarks = ",".join(["?"] * len(itm_ids))
            rows = fetch_all(conn, f'''
                SELECT m.itm_id, m.rtr_id, m.name, m.price, r.name
                FROM "MenuItem" m
                JOIN "Restaurant" r ON r.rtr_id = m.rtr_id
                WHERE m.itm_id IN ({qmarks})
            ''', tuple(itm_ids))
            fee_schedule = load_fee_schedule(conn)   # this restaurant's own fees (M4)
        finally:
            close_connection(conn)

        # Validate that all items belong to the same restaurant
        if not rows:
            return jsonify({"ok": False, "error": "items_not_found"}), 404

        # Map itm_id -> {price, name, rtr_id, rtr_name}
        dbmap = {row[0]: {"rtr_id": row[1], "name": row[2], "price_cents": row[3] or 0, "restaurant_name": row[4]} for row in rows}
        for it in itm_ids:
            if it not in dbmap:
                return jsonify({"ok": False, "error": f"item_{it}_not_found"}), 404
            if int(dbmap[it]["rtr_id"]) != rtr_id:
                return jsonify({"ok": False, "error": "mixed_restaurants"}), 400

        # Build items array for details; compute charges in integer cents (charges.py)
        detail_items = []
        lines = []
        for it, iid in zip(items_in, itm_ids):
            try:
                qty = int(it.get("qty") or 1)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "invalid_input"}), 400
            if qty <= 0: qty = 1
            meta = dbmap[iid]
            unit_cents = int(meta["price_cents"] or 0)
            lines.append((unit_cents, qty))
            detail_items.append({
                "itm_id": iid,
                "name": meta["name"],
                "qty": qty,
                "unit_price_cents": unit_cents,
                "line_total_cents": unit_cents * qty,
                **({"notes": (it.get("notes") or "")} if it.get("notes") else {})
            })

        placed_iso = datetime.now().astimezone().isoformat()

        details = {
            "placed_at": placed_iso,
            "restaurant_id": int(rtr_id),
            "items": detail_items,
            "charges_cents": compute_charges(lines, delivery_type, tip_cents,
                                             schedule=fee_schedule, rtr_id=rtr_id),
            "delivery_type": delivery_type,
            "eta_minutes": int(eta_minutes),
            "date": iso_date,
            "meal": meal,
            **({"meals": batch_meals} if batch_meals else {}),
        }

        # Pay from the wallet and save the order in one all-or-nothing ledger
        # transaction. The balance is checked by the ledger, never against
        # session['Wallet'] (M2 bugs 2 and 3).
        restaurant_name = dbmap[itm_ids[0]]["restaurant_name"]
        new_ord_id, error = _charge_and_save_order(
            usr_id, rtr_id, restaurant_name, details, client_key=payload.get("idempotency_key"))
        if error == "insufficient_funds":
            return jsonify({"ok": False, "error": "insufficient_funds"}), 402
        if error == "duplicate_request":
            return jsonify({"ok": False, "error": "duplicate_request"}), 409
        if error:
            return jsonify({"ok": False, "error": error}), 500
        return jsonify({"ok": True, "ord_id": new_ord_id})

    return jsonify({"ok": False, "error": "invalid_input"}), 400

# Orders route
@app.route('/orders')
def orders():
    """
    List restaurants and in-stock menu items for browsing.
    Args:
        None
    Returns:
        Response: HTML page showing restaurants and items (requires login).
    """
    if session.get('Username') is None:
        return redirect(url_for('login'))

    conn = create_connection(db_file)
    try:
        # Pull address fields too
        restaurants = fetch_all(conn, 'SELECT rtr_id, name, address, city, state, zip FROM "Restaurant"')
        menu_items = fetch_all(conn, '''
            SELECT itm_id, rtr_id, name, price, calories, allergens, description
            FROM "MenuItem"
            WHERE instock = 1
        ''')
    finally:
        close_connection(conn)

    def _addr(a, c, s, z) -> str:
        """
        Safely join address parts that might be None/ints.
        Args:
            a (Any): Street address.
            c (Any): City.
            s (Any): State/region.
            z (Any): Zip/postal code.
        Returns:
            str: A single formatted address string.
        """
        parts_raw = [a, c, s, z]
        parts = []
        for p in parts_raw:
            if p is None:
                continue
            # Coerce to string and strip
            sp = str(p).strip()
            if sp:
                parts.append(sp)
        return ", ".join(parts)

    rest_list = [{
        "rtr_id": r[0],
        "name": r[1],
        "address": r[2] or "",
        "city": r[3] or "",
        "state": r[4] or "",
        "zip": r[5] if r[5] is not None else "",
        "address_full": _addr(r[2], r[3], r[4], r[5]),
    } for r in restaurants]

    item_list = [{
        "itm_id":      m[0],
        "rtr_id":      m[1],
        "name":        m[2],
        "price_cents": m[3] or 0,
        "calories":    m[4] or 0,
        "allergens":   m[5] or "",
        "description": m[6] or "",
    } for m in menu_items]

    return render_template("orders.html", restaurants=rest_list, items=item_list)

# Restaurants browse route
@app.route('/restaurants')
def restaurants():
    """
    Browse restaurants with details and currently in-stock items.
    Args:
        None
    Returns:
        Response: HTML page listing restaurants and their items (requires login).
    """
    if session.get('Username') is None:
        return redirect(url_for('login'))

    conn = create_connection(db_file)
    try:
        restaurants = fetch_all(conn, 'SELECT rtr_id, name, description, phone, email, address, city, state, zip, hours, status FROM "Restaurant"')
        menu_items = fetch_all(conn, '''
            SELECT itm_id, rtr_id, name, price, calories, allergens, description
            FROM "MenuItem"
            WHERE instock = 1
        ''')
        # Fetch all reviews, including the user's name for display
        review_rows = fetch_all(conn, '''
            SELECT 
                r.rtr_id, r.rating, r.title, r.description, u.first_name, u.last_name
            FROM "Review" r
            LEFT JOIN "User" u ON r.usr_id = u.usr_id
            ORDER BY r.rev_id DESC
        ''')

        reviews_by_rtr = defaultdict(lambda: {'total_rating': 0, 'count': 0, 'list': []})
        for rtr_id, rating, title, description, first_name, last_name in review_rows:
            reviews_by_rtr[rtr_id]['total_rating'] += rating
            reviews_by_rtr[rtr_id]['count'] += 1
            reviews_by_rtr[rtr_id]['list'].append({
                "rating": rating,
                "title": title,
                "description": description,
                # LEFT JOIN keeps reviews whose author was deleted, so they still count toward the rating
                "user_name": f"{first_name} {last_name}" if first_name is not None else "Former customer",
            })
    finally:
        close_connection(conn)

    def _addr(a, c, s, z) -> str:
        parts_raw = [a, c, s, z]
        parts = []
        for p in parts_raw:
            if p is None:
                continue
            sp = str(p).strip()
            if sp:
                parts.append(sp)
        return ", ".join(parts)

    rest_list = [{
        "rtr_id": r[0],
        "name": r[1],
        "description": r[2] or "",
        "phone": r[3] or "",
        "email": r[4] or "",
        "address": r[5] or "",
        "city": r[6] or "",
        "state": r[7] or "",
        "zip": r[8] if r[8] is not None else "",
        "hours": r[9] or "",
        "status": r[10] or "",
        "address_full": _addr(r[5], r[6], r[7], r[8]),
        # ADDED: Include the calculated review data in the list passed to the template
        "reviews": reviews_by_rtr.get(r[0], {'total_rating': 0, 'count': 0, 'list': []})
    } for r in restaurants]

    item_list = [{
        "itm_id":      m[0],
        "rtr_id":      m[1],
        "name":        m[2],
        "price_cents": m[3] or 0,
        "calories":    m[4] or 0,
        "allergens":   m[5] or "",
        "description": m[6] or "",
    } for m in menu_items]

    return render_template("restaurants.html", restaurants=rest_list, items=item_list)

# Order receipt PDF route
@app.route('/orders/<int:ord_id>/receipt.pdf')
def order_receipt(ord_id: int):
    """
    Stream a PDF receipt for an order owned by the logged-in user.
    Args:
        ord_id (int): The order identifier in the path.
    Returns:
        Response: PDF file download or an error status (404/403) if inaccessible.
    """
    # Must be logged in
    if session.get('Username') is None:
        return redirect(url_for('login'))

    # Ensure the order belongs to the logged-in user
    conn = create_connection(db_file)
    try:
        row = fetch_one(conn, 'SELECT usr_id FROM "Order" WHERE ord_id = ?', (ord_id,))
        if not row:
            abort(404)
        # Admins can pull any customer's receipt (they already see every order on the dashboard)
        if not session.get('is_admin'):
            if session.get('usr_id') and row[0] != session['usr_id']:
                abort(403)
            # If usr_id not in session (older sessions), compare via email
            if not session.get('usr_id'):
                # Resolve current user's usr_id by email
                urow = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (session.get('Email'),))
                if not urow or urow[0] != row[0]:
                    abort(403)

        # Only the generator is wrapped: the abort(404/403) calls above raise HTTPExceptions,
        # which must not be swallowed and turned into a 500
        try:
            pdf_bytes = generate_order_receipt_pdf(db_file, ord_id)  # returns bytes
        except Exception as e:
            print(f"Receipt Generation Error (ord_id={ord_id}): {e!r}")
            return render_template("error.html",
                                   error="Receipt Unavailable",
                                   message="We couldn't generate this receipt. Please try again later."), 500
    finally:
        close_connection(conn)

    return send_file(
        BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'order_{ord_id}_receipt.pdf'
    )

# Database viewer route (uses helpers only)
@app.route('/db')
def db_view():
    """
    Display a simple, paginated database table viewer.
    Args:
        None
    Returns:
        Response: HTML page showing rows/columns for a selected table (requires admin).
    """
    if session.get('Username') is None:
        return redirect(url_for('login'))

    if not session.get('is_admin'):
        return render_template("error.html",
                             error="Access Denied",
                             message="You do not have permission to view the database."), 403

    allowed_tables = {'User', 'Restaurant', 'MenuItem', 'Order', 'Review', 'Ticket'}
    hidden_columns = {'password_HS'}
    table = request.args.get('t', 'User')
    if table not in allowed_tables:
        table = 'User'

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    page = max(page, 1)
    per_page = 10

    conn = create_connection(db_file)
    try:
        total_row = fetch_one(conn, f'SELECT COUNT(*) FROM "{table}"')
        total = (total_row[0] if total_row else 0) or 0

        pages = max(math.ceil(total / per_page), 1)
        page = min(page, pages)
        offset = (page - 1) * per_page

        col_rows = fetch_all(conn, f'PRAGMA table_info("{table}")')
        columns = [r[1] for r in col_rows] if col_rows else []

        rows = fetch_all(conn, f'SELECT * FROM "{table}" LIMIT ? OFFSET ?', (per_page, offset))
    finally:
        close_connection(conn)

    # Never expose credential columns, even to admins
    keep = [i for i, c in enumerate(columns) if c not in hidden_columns]
    columns = [columns[i] for i in keep]
    rows = [tuple(row[i] for i in keep) for row in (rows or [])]

    start = 0 if total == 0 else offset + 1
    end = min(offset + per_page, total)

    return render_template(
        'db_view.html',
        table=table,
        allowed=sorted(allowed_tables),
        columns=columns,
        rows=rows,
        page=page,
        pages=pages,
        total=total,
        start=start,
        end=end,
    )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Flask App for Meal Planner")
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to run the Flask app on')
    parser.add_argument('--port', type=int, default=5000, help='Port to run the Flask app on')
    return parser.parse_args()

def replace_menu_days(gen_str, days, entries):
    """
    Replace whole days of a serialized generated menu.
    Args:
        gen_str (str): The current User.generated_menu, "[YYYY-MM-DD,ID,meal],...".
        days (Iterable[date]): Days whose existing entries are dropped.
        entries (Iterable[str]): New entries to append, in the same format.
    Returns:
        str: The menu with every entry on those days replaced by the new entries. Entries on
        other days are kept exactly as they were.
    """
    drop = {d.isoformat() for d in days}
    kept = [
        e for e in re.findall(r'\[[^\]]*\]', gen_str or "")
        if e[1:].strip()[:10] not in drop
    ]
    return ",".join(kept + list(entries))


@app.route('/generate_plan', methods=['POST'])
def generate_plan():
    """
    Plan the next 7 days (starting tomorrow) for the logged-in user and save them to their
    calendar. Uses the planner named by the PLANNER environment variable: "solver" (default)
    or "llm" (v1).
    Returns:
        Response: JSON. With the solver: 200 {"ok": true, "optimal", "total_cost_cents",
        "kcal_per_day"} on success; 400 if the profile is missing its targets; 422 with
        "error" (the explanation) and "reasons" when no week fits. 401 if not logged in.
    """
    if session.get("Username") is None:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    planner = os.environ.get(PLANNER_ENV, "solver").strip().lower()
    if planner == "solver":
        return _generate_plan_solver()
    if planner == "llm":
        return _generate_plan_llm()
    return jsonify({
        "ok": False,
        "error": f"Unknown {PLANNER_ENV}={planner!r}; use one of {', '.join(PLANNERS)}.",
    }), 500


def _generate_plan_solver():
    """/generate_plan with the CP-SAT solver: the whole week at once, within the user's targets."""
    conn = create_connection(db_file)
    try:
        user = fetch_one(conn, '''
            SELECT preferences, allergies, generated_menu, daily_calorie_target, weekly_budget_cents, usr_id
            FROM "User" WHERE email = ?
        ''', (session.get("Email"),))
        if not user:
            return jsonify({"ok": False, "error": "User not found"}), 404
        prefs, allergies, current_menu, kcal_target, budget_cents, plan_usr_id = user
        fee_prefs = load_fee_prefs(conn, plan_usr_id)   # M4: batching and pickup settings

        try:
            plan_request = PlanRequest.from_profile(
                daily_calorie_target=kcal_target,
                weekly_budget_cents=budget_cents,
                allergies=allergies,
                preferences=prefs,
                start=date.today() + timedelta(days=1),
                options=fee_prefs.plan_options(),
            )
        except InvalidPlanRequest as e:
            return jsonify({"ok": False, "error": str(e), "fix_url": url_for("edit_profile")}), 400

        try:
            result = plan_week(plan_request, load_menu(db_file))
        except Exception as e:  # a planner bug or bad data: answer in JSON, the page expects it
            app.logger.exception("Planner failed")
            return jsonify({
                "ok": False,
                "error": f"The planner could not plan your week because of an internal error ({type(e).__name__}). Please report it.",
            }), 500
        if not result.ok:
            return jsonify({
                "ok": False,
                "status": result.status.value,
                "error": result.explanation,
                "reasons": list(result.reasons),
            }), 422

        # The week is planned as a whole (budget, calories), so it replaces those 7 days.
        new_menu_str = replace_menu_days(current_menu, plan_request.dates(), result.menu_entries())
        execute_query(conn, 'UPDATE "User" SET generated_menu = ? WHERE email = ?', (new_menu_str, session.get("Email")))
        session["GeneratedMenu"] = new_menu_str
        return jsonify({
            "ok": True,
            "planner": "solver",
            "optimal": result.optimal,
            "total_cost_cents": result.total_cost_cents,
            # M4: "Fees: $X, saved $Y vs ordering separately"
            "fees_cents": result.fees_cents,
            "fee_savings_cents": result.fee_savings_cents,
            "orders": len(result.orders),
            "batched_orders": sum(o.batched for o in result.orders),
            "kcal_per_day": {d.isoformat(): kcal for d, kcal in result.kcal_by_day().items()},
        })
    finally:
        close_connection(conn)


def _generate_plan_llm():
    """/generate_plan with the v1 LLM planner (PLANNER=llm), unchanged from v1."""
    # 1. Fetch User Metadata (Preferences & Allergies)
    conn = create_connection(db_file)
    try:
        user = fetch_one(conn, 'SELECT preferences, allergies, generated_menu FROM "User" WHERE email = ?', (session.get("Email"),))
        if not user:
            return jsonify({"ok": False, "error": "User not found"}), 404
        
        prefs, allergies, current_menu = user[0] or "", user[1] or "", user[2] or ""

        # 2. Initialize Generator
        # Using 500 tokens as defined in your system
        # strict_allergens: translate allergies into menu tags and exclude items with unknown allergens
        gen = MenuGenerator(tokens=500, strict_allergens=True)
        
        # 3. Define Timeframe (Next 7 days starting tomorrow)
        start_date = (date.today() + timedelta(days=1)).isoformat()
        
        # 4. Generate Menu
        # We pass the stored 'prefs' directly. The MenuGenerator will filter items 
        # and prompt the LLM based on these existing tags.
        new_menu_str = gen.update_menu(
            menu=current_menu, 
            preferences=prefs, 
            allergens=allergies, 
            date=start_date, 
            meal_numbers=[1, 2, 3], # Breakfast, Lunch, Dinner
            number_of_days=7
        )

        # 5. Save & Update Session
        execute_query(conn, 'UPDATE "User" SET generated_menu = ? WHERE email = ?', (new_menu_str, session.get("Email")))
        session["GeneratedMenu"] = new_menu_str
        
        return jsonify({"ok": True})

    except Exception as e:
        # Log the details server-side; don't expose internal error text to the client
        print(f"Generation Error: {e!r}")
        return jsonify({"ok": False, "error": "Meal plan generation failed. Please try again."}), 500
    finally:
        close_connection(conn)

@app.route('/admin/update_status', methods=['POST'])
def admin_update_status():
    """
    Update the status of an order through the admin dashboard.
    
    This endpoint validates the order exists, checks that the new status is valid,
    and ensures the status transition follows the defined workflow rules.
    
    Args:
        None (expects JSON body with ord_id and new_status)
        
    Returns:
        Response: JSON with success/error and appropriate HTTP status codes
        
    Request Body:
        {
            "ord_id": int,
            "new_status": str
        }
        
    Response Body (Success):
        {
            "ok": true,
            "ord_id": int,
            "new_status": str
        }
        
    Response Body (Error):
        {
            "ok": false,
            "error": str
        }
    """
    # Check if user is logged in and is an admin
    if not session.get("Username"):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    if not session.get("is_admin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    
    from models import OrderStatus
    
    # Parse and validate request JSON
    if not request.is_json:
        return jsonify({"ok": False, "error": "Request must be JSON"}), 400
    
    payload = request.get_json(silent=True) or {}
    
    # Extract parameters
    try:
        ord_id = int(payload.get("ord_id") or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid order ID"}), 400
    
    new_status = payload.get("new_status")
    
    if ord_id <= 0:
        return jsonify({"ok": False, "error": "Invalid order ID"}), 400
    
    if not new_status:
        return jsonify({"ok": False, "error": "Missing new_status parameter"}), 400
    
    # Validate new status is in allowed set
    if not OrderStatus.is_valid_status(new_status):
        return jsonify({"ok": False, "error": f"Invalid status: {new_status}"}), 400
    
    # Fetch order and validate it exists
    conn = create_connection(db_file)
    try:
        order_row = fetch_one(conn, 'SELECT ord_id, status FROM "Order" WHERE ord_id = ?', (ord_id,))
        
        if not order_row:
            return jsonify({"ok": False, "error": "Order not found"}), 404
        
        current_status = order_row[1] or "Ordered"
        
        # Validate status transition
        if not OrderStatus.is_valid_transition(current_status, new_status):
            return jsonify({
                "ok": False, 
                "error": f"Invalid transition from {current_status} to {new_status}"
            }), 400
        
        # Update order status
        execute_query(conn, 'UPDATE "Order" SET status = ? WHERE ord_id = ?', (new_status, ord_id))
        
        return jsonify({
            "ok": True,
            "ord_id": ord_id,
            "new_status": new_status
        }), 200
        
    except Exception as e:
        print(f"Error updating order status: {e}")
        return jsonify({"ok": False, "error": "Internal server error"}), 500
    finally:
        close_connection(conn)

@app.route('/admin/orders/<int:ord_id>/refund', methods=['POST'])
def admin_refund_order(ord_id):
    """
    Refund an order in full by reversing its ledger transaction (admin only).

    Nothing is edited or deleted: a new "refund" transaction posts the exact
    opposite of the order's entries, so the customer gets back everything they
    paid and the restaurant, tax and fee accounts give it back. Each order can
    be refunded once; repeating the request returns the same refund.

    Returns:
        JSON {"ok": true, "ord_id", "refund_txn_id", "refunded_cents", "already_refunded"}
        or {"ok": false, "error"} with 401, 403, 404 (no such order) or
        409 ("not_refundable": placed before the ledger existed).
    """
    if not session.get("Username"):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not session.get("is_admin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    conn = create_connection(db_file)
    try:
        _ledger_ready(conn)
        row = fetch_one(conn, 'SELECT usr_id, details FROM "Order" WHERE ord_id = ?', (ord_id,))
        if not row:
            return jsonify({"ok": False, "error": "order_not_found"}), 404
        usr_id, details_json = row
        try:
            txn_id = json.loads(details_json or "{}").get("ledger_txn_id")
        except (TypeError, ValueError):
            txn_id = None
        if not txn_id:
            return jsonify({"ok": False, "error": "not_refundable"}), 409

        try:
            result = ledger.reverse_transaction(
                conn, txn_id, f"refund:order:{ord_id}", memo=f"Refund for order #{ord_id}")
        except ledger.AlreadyReversed:
            return jsonify({"ok": False, "error": "already_refunded"}), 409
        except ledger.LedgerError as e:
            print(f"Refund failed: {e}")
            return jsonify({"ok": False, "error": "refund_failed"}), 500

        refunded = fetch_one(
            conn, 'SELECT amount_cents FROM "LedgerEntry" WHERE txn_id = ? AND account = ?',
            (result.txn_id, ledger.user_account(usr_id)),
        )
        return jsonify({
            "ok": True,
            "ord_id": ord_id,
            "refund_txn_id": result.txn_id,
            "refunded_cents": refunded[0] if refunded else 0,
            "already_refunded": not result.created,
        })
    finally:
        close_connection(conn)


@app.route('/admin')
def admin_dashboard():
    """
    Render the admin dashboard with order management and support tickets.
    
    This route displays:
    - A Kanban board with orders grouped by status (Ordered, Preparing, Delivering, Delivered)
    - Support tickets sorted by status priority (Open first) and creation date
    
    Orders are filtered to the last 7 days by default for performance.
    Tickets are paginated with 20 tickets per page.
    
    Args:
        None (accepts 'page' query parameter for ticket pagination)
        
    Returns:
        Response: HTML admin dashboard page
    """
    # Check if user is logged in and is an admin
    if not session.get("Username"):
        return redirect(url_for("login"))
    
    if not session.get("is_admin"):
        return render_template("error.html", 
                             error="Access Denied", 
                             message="You do not have permission to access the admin dashboard."), 403
    
    from datetime import datetime, timedelta
    
    # Get page number from query parameter, default to 1
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1
    
    # Pagination settings
    tickets_per_page = 20
    offset = (page - 1) * tickets_per_page
    
    conn = create_connection(db_file)
    try:
        # Calculate date 7 days ago for filtering
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        
        # Fetch all orders from last 7 days with user and restaurant information
        # Parse the details JSON to get placed_at timestamp for filtering
        order_rows = fetch_all(conn, '''
            SELECT 
                o.ord_id,
                o.rtr_id,
                o.usr_id,
                o.details,
                o.status,
                u.first_name,
                u.last_name,
                r.name as restaurant_name
            FROM "Order" o
            JOIN "User" u ON o.usr_id = u.usr_id
            JOIN "Restaurant" r ON o.rtr_id = r.rtr_id
            ORDER BY o.ord_id DESC
        ''')
        
        # Process orders and filter by date
        orders_by_status = {
            'Ordered': [],
            'Preparing': [],
            'Delivering': [],
            'Delivered': [],
            'Other': []  # any status the board has no column for, e.g. 'Cancelled'
        }
        
        _ledger_ready(conn)
        refunded_txns = _refunded_txn_ids(conn)
        ledger_check = ledger.check_ledger(conn)
        # Case-insensitive lookup so e.g. 'delivered' lands in 'Delivered'
        known_statuses = {s.lower(): s for s in orders_by_status if s != 'Other'}

        for row in order_rows:
            ord_id, rtr_id, usr_id, details_json, status, first_name, last_name, restaurant_name = row
            
            # Parse details to get placed_at and total
            placed_at = None
            total = None
            placed_at_display = ""
            ledger_txn_id = None
            
            if details_json:
                try:
                    details = json.loads(details_json)
                    placed_at = details.get("placed_at") or details.get("time")
                    
                    # Filter by date (last 7 days)
                    if placed_at:
                        order_dt = datetime.fromisoformat(placed_at)
                        if order_dt.isoformat() < seven_days_ago:
                            continue  # Skip orders older than 7 days
                        
                        # Format for display
                        placed_at_display = order_dt.strftime("%Y-%m-%d %H:%M")
                    
                    # Get total from charges (new orders: int cents; old orders: float dollars)
                    if details.get("charges_cents") or details.get("charges"):
                        total = order_charges_cents(details)["total"]
                    ledger_txn_id = details.get("ledger_txn_id")
                    
                except Exception as e:
                    print(f"Error parsing order details: {e}")
                    continue
            
            # Default status if missing
            if not status:
                status = 'Ordered'
            # Normalize casing/whitespace onto a known column; unknown statuses keep their text
            status = known_statuses.get(str(status).strip().lower(), status)

            # Build order object
            order = {
                'ord_id': ord_id,
                'customer_name': f"{first_name} {last_name}",
                'restaurant_name': restaurant_name,
                'total': format_cents(total) if total is not None else "N/A",
                'placed_at': placed_at_display,
                'status': status,
                'refunded': ledger_txn_id in refunded_txns,
                'refundable': bool(ledger_txn_id) and ledger_txn_id not in refunded_txns,
            }
            
            # Add to appropriate status group; never drop an order the board doesn't recognize
            if status in known_statuses.values():
                orders_by_status[status].append(order)
            else:
                print(f"Admin dashboard: order {ord_id} has unrecognized status {status!r}; showing under Other")
                orders_by_status['Other'].append(order)
        
        # Sort orders within each status group by ord_id descending (already sorted from query)
        # But let's ensure it's explicit
        for status in orders_by_status:
            orders_by_status[status].sort(key=lambda x: x['ord_id'], reverse=True)
        
        # Get total count of tickets for pagination
        total_tickets_row = fetch_one(conn, 'SELECT COUNT(*) FROM Ticket')
        total_tickets = total_tickets_row[0] if total_tickets_row else 0
        
        # Calculate total pages
        total_pages = (total_tickets + tickets_per_page - 1) // tickets_per_page
        if total_pages < 1:
            total_pages = 1
        
        # Ensure current page doesn't exceed total pages
        if page > total_pages:
            page = total_pages
        
        # Fetch paginated support tickets with user and order information
        ticket_rows = fetch_all(conn, '''
            SELECT 
                t.ticket_id,
                t.usr_id,
                t.ord_id,
                t.message,
                t.response,
                t.status,
                t.created_at,
                t.updated_at,
                u.first_name,
                u.last_name
            FROM Ticket t
            JOIN "User" u ON t.usr_id = u.usr_id
            ORDER BY 
                CASE 
                    WHEN t.status = 'Open' THEN 0
                    WHEN t.status = 'In Progress' THEN 1
                    WHEN t.status = 'Resolved' THEN 2
                    WHEN t.status = 'Closed' THEN 3
                    ELSE 4
                END,
                t.created_at DESC
            LIMIT ? OFFSET ?
        ''', (tickets_per_page, offset))
        
        # Process tickets
        tickets = []
        for row in ticket_rows:
            ticket_id, usr_id, ord_id, message, response, status, created_at, updated_at, first_name, last_name = row
            
            # Format created_at for display
            created_at_display = ""
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    created_at_display = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    created_at_display = str(created_at)
            
            ticket = {
                'ticket_id': ticket_id,
                'customer_name': f"{first_name} {last_name}",
                'ord_id': ord_id,
                'message': message,
                'response': response,
                'status': status,
                'created_at': created_at_display
            }
            
            tickets.append(ticket)
        
    finally:
        close_connection(conn)
    
    return render_template(
        'admin.html',
        ledger_check=ledger_check,
        ledger_total=format_cents(ledger_check.total_cents),
        orders_by_status=orders_by_status,
        tickets=tickets,
        current_page=page,
        total_pages=total_pages,
        total_tickets=total_tickets
    )

# Blank line between appended staff replies in Ticket.response
TICKET_RESPONSE_SEPARATOR = "\n\n"

@app.route('/admin/update_ticket_status', methods=['POST'])
def admin_update_ticket_status():
    """
    Update the status of a support ticket and optionally add a response.
    
    This endpoint validates the ticket exists, checks that the new status is valid,
    and automatically updates the status to "In Progress" when a response is added
    to an "Open" ticket.
    
    Args:
        None (expects JSON body with ticket_id, new_status, and optional response)
        
    Returns:
        Response: JSON with success/error and appropriate HTTP status codes
        
    Request Body:
        {
            "ticket_id": int,
            "new_status": str,
            "response": str (optional)
        }
        
    Response Body (Success):
        {
            "ok": true,
            "ticket_id": int,
            "new_status": str
        }
        
    Response Body (Error):
        {
            "ok": false,
            "error": str
        }
    """
    # Check if user is logged in and is an admin
    if not session.get("Username"):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    if not session.get("is_admin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    
    # Parse and validate request JSON
    if not request.is_json:
        return jsonify({"ok": False, "error": "Request must be JSON"}), 400
    
    payload = request.get_json(silent=True) or {}
    
    # Extract parameters
    try:
        ticket_id = int(payload.get("ticket_id") or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid ticket ID"}), 400
    
    new_status = payload.get("new_status")
    response_text = payload.get("response")
    
    if ticket_id <= 0:
        return jsonify({"ok": False, "error": "Invalid ticket ID"}), 400
    
    if not new_status:
        return jsonify({"ok": False, "error": "Missing new_status parameter"}), 400
    
    # Validate new status is in allowed set
    VALID_TICKET_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
    if new_status not in VALID_TICKET_STATUSES:
        return jsonify({"ok": False, "error": f"Invalid status: {new_status}"}), 400
    
    # Fetch ticket and validate it exists
    conn = create_connection(db_file)
    try:
        ticket_row = fetch_one(conn, 'SELECT ticket_id, status FROM Ticket WHERE ticket_id = ?', (ticket_id,))
        
        if not ticket_row:
            return jsonify({"ok": False, "error": "Ticket not found"}), 404
        
        current_status = ticket_row[1] or "Open"
        
        # Determine final status based on response logic
        # If response is provided and current status is "Open", automatically set to "In Progress"
        if response_text and current_status == "Open":
            final_status = "In Progress"
        else:
            final_status = new_status
        
        # Update ticket status and response
        if response_text:
            # Append the reply as a timestamped entry instead of overwriting earlier replies.
            # Done in one statement so two staff replying at once can't lose either reply.
            entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {str(response_text).strip()}"
            execute_query(
                conn,
                '''UPDATE Ticket
                   SET status = ?,
                       response = CASE WHEN response IS NULL OR response = '' THEN ?
                                       ELSE response || ? END
                   WHERE ticket_id = ?''',
                (final_status, entry, TICKET_RESPONSE_SEPARATOR + entry, ticket_id)
            )
        else:
            # Update only status
            execute_query(
                conn, 
                'UPDATE Ticket SET status = ? WHERE ticket_id = ?', 
                (final_status, ticket_id)
            )
        
        # Note: updated_at timestamp is automatically updated by the database trigger
        
        return jsonify({
            "ok": True,
            "ticket_id": ticket_id,
            "new_status": final_status
        }), 200
        
    except Exception as e:
        print(f"Error updating ticket status: {e}")
        return jsonify({"ok": False, "error": "Internal server error"}), 500
    finally:
        close_connection(conn)

@app.route('/support/submit', methods=['POST'])
def support_submit():
    """
    Submit a new support ticket for an order issue.
    
    This endpoint allows authenticated users to report issues with their orders.
    It validates that the user is logged in, the order exists and belongs to them,
    and the message meets minimum length requirements.
    
    Args:
        None (expects form data with ord_id and message)
        
    Returns:
        Response: Redirect to profile page with success/error message
        
    Form Data:
        ord_id (int): The order ID to report an issue for
        message (str): The issue description (minimum 10 characters)
    """
    # Verify user is authenticated
    if session.get('Username') is None:
        return redirect(url_for('login'))
    
    # Get user ID from session
    usr_id = session.get('usr_id')
    if not usr_id:
        # Fallback: resolve via email
        email = session.get('Email')
        if not email:
            return redirect(url_for('logout'))
        
        conn = create_connection(db_file)
        try:
            row = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (email,))
            if not row:
                return redirect(url_for('logout'))
            usr_id = row[0]
            session['usr_id'] = usr_id
        finally:
            close_connection(conn)
    
    # Parse form data
    try:
        ord_id = int(request.form.get('ord_id') or 0)
    except (ValueError, TypeError):
        # Preserve form data and show error
        return redirect(url_for('profile') + '?ticket_error=invalid_order')
    
    message = (request.form.get('message') or '').strip()
    
    # Validate order ID
    if ord_id <= 0:
        return redirect(url_for('profile') + '?ticket_error=invalid_order')
    
    # Validate message length (minimum 10 characters)
    if len(message) < 10:
        # url_for URL-encodes each value, so '&', '#', '=' or '%' in the message can't corrupt the query string
        return redirect(url_for('profile', ticket_error='message_too_short', ord_id=ord_id, message=message))
    
    # Validate order exists and belongs to current user
    conn = create_connection(db_file)
    try:
        order_row = fetch_one(conn, 'SELECT ord_id, usr_id FROM "Order" WHERE ord_id = ?', (ord_id,))
        
        if not order_row:
            return redirect(url_for('profile') + '?ticket_error=order_not_found')
        
        order_usr_id = order_row[1]
        if order_usr_id != usr_id:
            return redirect(url_for('profile') + '?ticket_error=unauthorized')
        
        # Create new Ticket record with status "Open"
        # created_at and updated_at are set automatically by database defaults
        execute_query(
            conn,
            '''
            INSERT INTO Ticket (usr_id, ord_id, message, status)
            VALUES (?, ?, ?, 'Open')
            ''',
            (usr_id, ord_id, message)
        )
        
        # Get the newly created ticket ID
        ticket_row = fetch_one(conn, 'SELECT last_insert_rowid()')
        new_ticket_id = ticket_row[0] if ticket_row else None
        
        # Redirect to profile with success message
        return redirect(url_for('profile') + f'?ticket_success=1&ticket_id={new_ticket_id}')
        
    except sqlite3.Error as e:
        print(f"Database error creating ticket: {e}")
        return redirect(url_for('profile') + '?ticket_error=database_error')
        
    except Exception as e:
        print(f"Error creating ticket: {e}")
        return redirect(url_for('profile') + '?ticket_error=server_error')
        
    finally:
        close_connection(conn)

@app.route('/insights')
def insights():
    """
    Render the new Data Intelligence Dashboard.
    """
    if session.get("Username") is None:
        return redirect(url_for("login"))
    return render_template("insights.html")

@app.route('/api/insights_data')
def insights_data():
    """
    Aggregates ALL user data for visualization.
    Returns complex JSON with multiple datasets.
    """
    if session.get("Username") is None:
        return jsonify({"error": "Unauthorized"}), 401

    conn = create_connection(db_file)
    try:
        # 1. Fetch User & Generated Menu
        user_row = fetch_one(conn, 'SELECT usr_id, generated_menu FROM "User" WHERE email = ?', (session.get("Email"),))
        if not user_row:
            return jsonify({"error": "User not found"}), 404
        usr_id, gen_menu_str = user_row

        # 2. Fetch All Orders
        order_rows = fetch_all(conn, '''
            SELECT o.ord_id, o.details, o.status, r.name
            FROM "Order" o
            JOIN "Restaurant" r ON o.rtr_id = r.rtr_id
            WHERE o.usr_id = ?
            ORDER BY o.ord_id ASC
        ''', (usr_id,))

        # --- DATA PROCESSING ---
        
        # A. Order History Parsing
        orders_data = []
        item_frequencies = Counter()
        restaurant_spend = defaultdict(float)
        restaurant_freq = Counter()
        hourly_activity = defaultdict(int)
        weekday_activity = defaultdict(int)
        
        total_spend = 0.0
        total_calories = 0
        total_items = 0
        
        spending_breakdown = {"food": 0.0, "tax": 0.0, "fees": 0.0, "tip": 0.0}
        delivery_vs_pickup = {"delivery": 0, "pickup": 0}
        
        # For "Value Analysis" (Scatter plot)
        value_scatter = [] # {x: calories, y: price, label: name}

        for oid, details_json, status, r_name in order_rows:
            if not details_json: continue
            try:
                d = json.loads(details_json)
                
                # timestamps
                placed_at = d.get("placed_at") or d.get("time")
                if placed_at:
                    dt = datetime.fromisoformat(placed_at)
                    hourly_activity[dt.hour] += 1
                    weekday_activity[dt.strftime("%A")] += 1
                
                # financials
                cc = order_charges_cents(d)   # int cents for new and old orders
                subtotal = cc["subtotal"] / 100
                tax = cc["tax"] / 100
                fee = (cc["delivery_fee"] + cc["service_fee"]) / 100
                tip = cc["tip"] / 100
                total = cc["total"] / 100
                
                total_spend += total
                spending_breakdown["food"] += subtotal
                spending_breakdown["tax"] += tax
                spending_breakdown["fees"] += fee
                spending_breakdown["tip"] += tip
                
                restaurant_spend[r_name] += total
                restaurant_freq[r_name] += 1
                
                dtype = d.get("delivery_type", "delivery")
                delivery_vs_pickup[dtype] += 1

                # Items (we need to fetch calorie data if not in JSON, but let's assume JSON has it or we skip)
                # Actually, Order details JSON usually stores name/price. Calories might be missing.
                # We will just count frequencies here.
                for item in d.get("items", []):
                    item_frequencies[item.get("name")] += item.get("qty", 1)
                    
                    # For scatter plot, we try to estimate unit price
                    u_price = item_cents(item)[0] / 100
                    # Note: We assume calories aren't always in order JSON. 
                    # If you want calories, we'd need to query MenuItem table.
                    # Let's do a bulk query for Item Metadata later.

            except Exception as e:
                continue

        # B. Planned vs Actual (Generated Menu)
        gen_map = parse_generated_menu(gen_menu_str)
        # We need to fetch metadata for all items in Generated Plan AND Orders to do calorie math
        
        # 3. Fetch Metadata for Deep Analysis
        # Get all item IDs from generated menu
        gen_item_ids = set()
        for day_list in gen_map.values():
            for e in day_list:
                gen_item_ids.add(e['itm_id'])
        
        # We also want to find "Healthy Alternatives". 
        # Let's fetch ALL menu items for the restaurants the user visited.
        visited_rtr_ids = fetch_all(conn, 'SELECT DISTINCT rtr_id FROM "Order" WHERE usr_id = ?', (usr_id,))
        visited_ids = [r[0] for r in visited_rtr_ids]
        
        alternatives_data = {} # rtr_id -> [items sorted by calories]
        if visited_ids:
            q = ",".join(["?"]*len(visited_ids))
            all_rtr_items = fetch_all(conn, f'SELECT rtr_id, name, price, calories FROM MenuItem WHERE rtr_id IN ({q})', tuple(visited_ids))
            for rid, name, price, cal in all_rtr_items:
                if rid not in alternatives_data: alternatives_data[rid] = []
                alternatives_data[rid].append({"name": name, "price": price, "calories": cal})
        
        # 4. Construct Datasets
        
        # Chart 1: Top 5 Restaurants (Freq)
        top_rest = restaurant_freq.most_common(5)
        
        # Chart 2: Meal Time Distribution (Pie)
        # Using hour buckets: Breakfast (5-11), Lunch (11-15), Dinner (15-23), Late Night (23-5)
        meal_times = {"Breakfast": 0, "Lunch": 0, "Dinner": 0, "Late Night": 0}
        for h, count in hourly_activity.items():
            if 5 <= h < 11: meal_times["Breakfast"] += count
            elif 11 <= h < 16: meal_times["Lunch"] += count
            elif 16 <= h < 23: meal_times["Dinner"] += count
            else: meal_times["Late Night"] += count

        # Chart 3: Spending Breakdown (Food vs Fees)
        
        # Insight Generation
        insights_text = []
        if spending_breakdown["tip"] > (spending_breakdown["food"] * 0.25):
            insights_text.append("Generous Tipper! You average over 25% in tips.")
        
        if delivery_vs_pickup["delivery"] > delivery_vs_pickup["pickup"] * 2:
            insights_text.append("Delivery Heavy: You could save ~15% by switching to pickup more often.")

        fav_rest = top_rest[0][0] if top_rest else "None"
        insights_text.append(f"Loyalist: Your favorite spot is {fav_rest}.")

        return jsonify({
            "charts": {
                "top_restaurants": {
                    "labels": [r[0] for r in top_rest],
                    "data": [r[1] for r in top_rest]
                },
                "meal_times": {
                    "labels": list(meal_times.keys()),
                    "data": list(meal_times.values())
                },
                "spending_breakdown": {
                    "labels": ["Food Cost", "Tax", "Service/Delivery Fees", "Tips"],
                    "data": [
                        spending_breakdown["food"], 
                        spending_breakdown["tax"], 
                        spending_breakdown["fees"], 
                        spending_breakdown["tip"]
                    ]
                },
                "activity_by_day": {
                    "labels": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                    "data": [weekday_activity.get(d, 0) for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]]
                },
                "delivery_mode": {
                    "labels": ["Delivery", "Pickup"],
                    "data": [delivery_vs_pickup["delivery"], delivery_vs_pickup["pickup"]]
                },
                "top_items": {
                    "labels": [i[0] for i in item_frequencies.most_common(5)],
                    "data": [i[1] for i in item_frequencies.most_common(5)]
                }
            },
            "insights": insights_text,
            "stats": {
                "total_orders": len(order_rows),
                "total_spend": total_spend,
                "avg_order": (total_spend / len(order_rows)) if order_rows else 0
            }
        })

    except Exception as e:
        # Log the details server-side; don't expose internal error text to the client
        print(f"Insights Error: {e!r}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        close_connection(conn)

if __name__ == '__main__':
    """
    DB column names:

    MenuItem: itm_id,rtr_id,name,description,price,calories,instock,restock,allergens
    Order: ord_id,rtr_id,usr_id,details,status
    Restaurant: rtr_id,name,description,phone,email,password_HS,address,city,state,zip,hours,status
    Review: rev_id,rtr_id,usr_id,title,rating,description
    User: usr_id,first_name,last_name,email,phone,password_HS,wallet,preferences,allergies,generated_menu
    """
    args = parse_args()
    app.run(host=args.host, port=args.port, debug=True)