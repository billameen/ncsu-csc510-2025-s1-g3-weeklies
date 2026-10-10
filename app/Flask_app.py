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
from collections import Counter, defaultdict
from menu_generation import MenuGenerator

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

# ---------------------- Helpers ----------------------

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
    Convert an amount in dollars to cents.
    Args:
        dollars (int | float | None): The value in dollars to convert.
    Returns:
        int: The cent value (0 on failure).
    """
    try:
        # Use _money to ensure 2 decimal places, then multiply by 100
        return int(_money(dollars) * 100)
    except Exception:
        return 0

def _execute_transaction(conn, queries_and_params: list) -> bool:
    """
    Execute multiple queries in a single, atomic transaction.
    Args:
        conn (sqlite3.Connection): Active database connection.
        queries_and_params (list): List of (query: str, params: tuple) pairs.
    Returns:
        bool: True on success, False on failure (with automatic rollback).
    """
    try:
        cur = conn.cursor()
        for query, params in queries_and_params:
            cur.execute(query, params)
        conn.commit()
        return True
    except Exception as e:
        print(f"Transaction failed, rolling back: {e}")
        conn.rollback()
        return False

def parse_generated_menu(gen_str):
    """
    Parse a serialized generated-menu string into a date-indexed structure.
    Args:
        gen_str (str): A string like "[YYYY-MM-DD,ID,(meal)]..." where meal is 1|2|3 (optional).
    Returns:
        dict: Mapping 'YYYY-MM-DD' -> [{'itm_id': int, 'meal': int}, ...].
    """
    if not gen_str:
        return {}

    # date, id, optional meal (1,2,3)
    pairs = re.findall(r'\[\s*(\d{4}-\d{2}-\d{2})\s*,\s*([0-9]+)\s*(?:,\s*([123])\s*)?\]', gen_str)
    out = {}
    for d, mid, meal in pairs:
        try:
            itm_id = int(mid)
            meal_i = int(meal) if meal else 3  # default to Dinner for legacy entries
            out.setdefault(d, []).append({'itm_id': itm_id, 'meal': meal_i})
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


def build_calendar_cells(gen_map, year, month, items_by_id):
    """
    Build month-view calendar cells enriched with menu items per day.
    Args:
        gen_map (dict): Mapping 'YYYY-MM-DD' -> [{'itm_id': int, 'meal': 1|2|3}, ...].
        year (int): The calendar year.
        month (int): The calendar month (1–12).
        items_by_id (dict): Mapping itm_id -> item detail dict from DB.
    Returns:
        list: A flat list of calendar cell dicts with day number and a 'meals' list.
    """
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
                })

            cells.append({"day": d, "meals": meals})

    return cells


def _is_restaurant_reviewed(conn, usr_id: int, rtr_id: int) -> bool:
    """Check if the user has already submitted a review for this specific restaurant."""
    # Checks the existing schema: Review(rev_id, rtr_id, usr_id, title, rating, description)
    sql = 'SELECT 1 FROM "Review" WHERE usr_id = ? AND rtr_id = ?'
    return fetch_one(conn, sql, (usr_id, rtr_id)) is not None

# ---------------------- Routes ----------------------

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
    if not year or not month:
        year, month = today.year, today.month

    # Load current user's generated_menu
    conn = create_connection(db_file)
    try:
        user = fetch_one(conn, 'SELECT * FROM "User" WHERE email = ?', (session.get("Email"),))
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
    cells = build_calendar_cells(gen_map, year, month, items_by_id)

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
        calendar_cells=cells,
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
            session["Wallet"] = user[6]
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

        digits_only = re.sub(r"\D+", "", phone)
        if len(digits_only) < 7:
            return render_template('register.html', error="Please enter a valid phone number")

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
        row = fetch_one(conn, 'SELECT usr_id,first_name,last_name,email,phone,password_HS,wallet,preferences,allergies FROM "User" WHERE email = ?', (email,))
        if not row:
            return redirect(url_for('logout'))

        user = {
            "usr_id":        row[0],
            "first_name":    row[1],
            "last_name":     row[2],
            "email":         row[3],
            "phone":         row[4],
            "password_HS":   row[5],
            "wallet":        (row[6] or 0) / 100.0,
            "preferences":   row[7] or "",
            "allergies":     row[8] or "",
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

        orders = []
        for ord_id, details, status, r_name, rtr_id in order_rows:
            placed = ""
            total = ""
            if details:
                try:
                    j = json.loads(details)
                    placed = _fmt_date(j.get("placed_at") or j.get("time"))
                    charges = j.get("charges") or {}
                    total_val = charges.get("total") or charges.get("grand_total") or charges.get("amount")
                    total = _fmt_total(total_val) if total_val is not None else ""
                except Exception:
                    pass

            # New logic to determine reviewability (Delivered AND Restaurant not yet reviewed)
            is_delivered = (status or "").lower() == OrderStatus.ORDERED.get_lowercase()
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
                "is_reviewed": is_reviewed_final # <-- CORRECTED: Use the final state for display
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
        pw_error=pw_error
    )

# Edit Profile route
@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    """
    Display and process the profile edit form (phone, preferences, allergies).
    Args:
        None
    Returns:
        Response: Renders form (GET) or updates and redirects to profile (POST).
    """
    if session.get('Username') is None:
        return redirect(url_for('login'))

    usr_id = session.get('usr_id')
    if not usr_id:
        return redirect(url_for('logout'))

    conn = create_connection(db_file)
    try:
        row = fetch_one(conn, '''
            SELECT usr_id, first_name, last_name, email, phone, wallet, preferences, allergies
            FROM "User" WHERE usr_id = ?
        ''', (usr_id,))
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
        "wallet": (row[5] or 0) / 100.0,
        "preferences": row[6] or "",
        "allergies": row[7] or "",
    }

    # For now just render an edit form (you can build edit_profile.html)
    if request.method == 'POST':
        # You’ll expand this with update logic later
        # Example: update phone, preferences, allergies
        new_phone = request.form.get('phone') or user['phone']
        new_prefs = request.form.get('preferences') or user['preferences']
        new_allergies = request.form.get('allergies') or user['allergies']

        conn = create_connection(db_file)
        try:
            execute_query(conn, '''
                UPDATE "User"
                SET phone = ?, preferences = ?, allergies = ?
                WHERE usr_id = ?
            ''', (new_phone, new_prefs, new_allergies, usr_id))
        finally:
            close_connection(conn)

        # Refresh session values
        session['Phone'] = new_phone
        session['Preferences'] = new_prefs
        session['Allergies'] = new_allergies

        return redirect(url_for('profile'))

    return render_template("edit_profile.html", user=user)

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

    # Read form fields
    current_password = (request.form.get('current_password') or '').strip()
    new_password     = (request.form.get('new_password') or '').strip()
    confirm_password = (request.form.get('confirm_password') or '').strip()

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
        amount_dollars = _money(request.form.get('amount') or 0)
        amount_cents = _dollars_to_cents(amount_dollars)
    except Exception:
        return redirect(url_for('profile', wallet_error='invalid_amount'))

    if amount_cents <= 0:
        return redirect(url_for('profile', wallet_error='zero_amount'))

    usr_id = session['usr_id']
    
    conn = create_connection(db_file)
    try:
        # Atomically update the user's wallet balance
        success = _execute_transaction(conn, [
            ('UPDATE "User" SET wallet = wallet + ? WHERE usr_id = ?', (amount_cents, usr_id))
        ])

        if success:
            # Refresh session and redirect
            session['Wallet'] = session['Wallet'] + amount_cents
            return redirect(url_for('profile', wallet_updated='topup'))
        else:
            return redirect(url_for('profile', wallet_error='db_failed'))
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
        amount_dollars = _money(request.form.get('amount') or 0)
        amount_cents = _dollars_to_cents(amount_dollars)
    except Exception:
        return redirect(url_for('profile', wallet_error='invalid_amount'))

    sender_id = session['usr_id']

    if amount_cents <= 0:
        return redirect(url_for('profile', wallet_error='zero_amount'))
    if recipient_email == session.get('Email'):
        return redirect(url_for('profile', wallet_error='self_gift'))

    conn = create_connection(db_file)
    try:
        # 1. Get sender's current balance and recipient's ID
        sender = fetch_one(conn, 'SELECT wallet FROM "User" WHERE usr_id = ?', (sender_id,))
        recipient = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (recipient_email,))

        if not sender or not recipient:
            return redirect(url_for('profile', wallet_error='recipient_not_found'))

        sender_balance = sender[0] or 0
        recipient_id = recipient[0]

        if sender_balance < amount_cents:
            return redirect(url_for('profile', wallet_error='insufficient_funds'))

        # 2. Prepare the atomic transaction (two steps: debit and credit)
        queries_and_params = [
            # Debit sender
            ('UPDATE "User" SET wallet = wallet - ? WHERE usr_id = ?', (amount_cents, sender_id)),
            # Credit recipient
            ('UPDATE "User" SET wallet = wallet + ? WHERE usr_id = ?', (amount_cents, recipient_id))
        ]

        # 3. Execute the atomic transaction
        if _execute_transaction(conn, queries_and_params):
            # Refresh sender's session wallet value
            session['Wallet'] = session['Wallet'] - amount_cents
            return redirect(url_for('profile', wallet_updated='gift'))
        else:
            return redirect(url_for('profile', wallet_error='db_failed'))
    finally:
        close_connection(conn)

# Review Submission Route (Restaurant-Level)
@app.route('/review/submit', methods=['POST'])
def submit_review():
    """Handles POST request to submit a restaurant-level review."""
    if session.get('usr_id') is None:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    conn = create_connection(db_file)
    try:
        data = request.get_json()
        usr_id = session['usr_id']
        rtr_id = int(data.get('restaurant_id')) # New: use restaurant_id
        rating = int(data.get('rating'))
        title = (data.get('title') or '').strip()
        description = (data.get('comment') or '').strip()
        ord_id = int(data.get('order_id')) # Optional, for context/UI redirection

        if not (1 <= rating <= 5) or rtr_id <= 0:
            return jsonify({"ok": False, "error": "Invalid rating or restaurant ID"}), 400
        
        # 1. Verify the order was actually delivered to allow review submission
        order_row = fetch_one(conn, 'SELECT status FROM "Order" WHERE ord_id = ? AND usr_id = ? AND rtr_id = ?', (ord_id, usr_id, rtr_id))
        if not order_row or (order_row[0] or '').lower() != OrderStatus.ORDERED.get_lowercase():
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
@app.route('/order', methods=['GET', 'POST'])
def order():
    """
    Place an order via JSON (POST) or handle legacy single-item GET flow.
    Args:
        None
    Returns:
        Response: JSON with {'ok', 'ord_id'} on POST; redirects/HTML for legacy GET.
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
        rtr_id = int(payload.get("restaurant_id") or 0)
        items_in = payload.get("items") or []     # [{itm_id, qty, notes}]
        delivery_type = (payload.get("delivery_type") or "delivery").lower()
        if delivery_type not in ("delivery", "pickup"):
            delivery_type = "delivery"
        tip_dollars = _money(payload.get("tip") or 0)
        eta_minutes = int(payload.get("eta_minutes") or 40)
        iso_date = (payload.get("date") or datetime.now().date().isoformat())
        try:
            meal = int(payload.get("meal") or 3)
        except Exception:
            meal = 3

        if rtr_id <= 0 or not items_in:
            return jsonify({"ok": False, "error": "invalid_input"}), 400

        # Look up all items strictly from DB to get authoritative prices/names
        itm_ids = [int(it.get("itm_id") or 0) for it in items_in if int(it.get("itm_id") or 0) > 0]
        if not itm_ids:
            return jsonify({"ok": False, "error": "no_items"}), 400

        conn = create_connection(db_file)
        try:
            qmarks = ",".join(["?"] * len(itm_ids))
            rows = fetch_all(conn, f'''
                SELECT m.itm_id, m.rtr_id, m.name, m.price, r.name
                FROM "MenuItem" m
                JOIN "Restaurant" r ON r.rtr_id = m.rtr_id
                WHERE m.itm_id IN ({qmarks})
            ''', tuple(itm_ids))
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

        # Build items array for details; compute charges
        detail_items = []
        subtotal = 0.0
        for it in items_in:
            iid = int(it.get("itm_id"))
            qty = int(it.get("qty") or 1)
            if qty <= 0: qty = 1
            meta = dbmap[iid]
            unit_price = _cents_to_dollars(meta["price_cents"])
            line_total = _money(unit_price * qty)
            subtotal = _money(subtotal + line_total)
            detail_items.append({
                "itm_id": iid,
                "name": meta["name"],
                "qty": qty,
                "unit_price": unit_price,
                "line_total": line_total,
                **({"notes": (it.get("notes") or "")} if it.get("notes") else {})
            })

        tax = _money(subtotal * 0.0725)
        delivery_fee = 3.99 if delivery_type == "delivery" else 0.00
        service_fee = 1.49
        total = _money(subtotal + tax + delivery_fee + service_fee + tip_dollars)

        placed_iso = datetime.now().astimezone().isoformat()

        details = {
            "placed_at": placed_iso,
            "restaurant_id": int(rtr_id),
            "items": detail_items,
            "charges": {
                "subtotal": subtotal,
                "tax": tax,
                "delivery_fee": delivery_fee,
                "service_fee": service_fee,
                "tip": tip_dollars,
                "total": total
            },
            "delivery_type": delivery_type,
            "eta_minutes": int(eta_minutes),
            "date": iso_date,
            "meal": meal
        }

        # Handle amount being debited from user's wallet
        total_cents = _dollars_to_cents(total)
        user_wallet_cents = session.get('Wallet', 0)

        # Quick check based on session to prevent unnecessary transaction attempt
        if user_wallet_cents < total_cents:
            return jsonify({"ok": False, "error": "insufficient_funds"}), 402

        # Insert the single order row with status "Ordered" AND debit the wallet atomically
        conn = create_connection(db_file)
        new_ord_id = None
        try:
            # 1. Prepare queries for atomic transaction: Debit wallet AND Insert order
            queries_and_params = [
                # Debit the wallet, using the WHERE clause as an optimistic check against race conditions
                ('UPDATE "User" SET wallet = wallet - ? WHERE usr_id = ? AND wallet >= ?', (total_cents, usr_id, total_cents)),
                # Insert the new order
                ('INSERT INTO "Order" (rtr_id, usr_id, details, status) VALUES (?, ?, ?, ?)', (rtr_id, usr_id, json.dumps(details), OrderStatus.ORDERED.value))
            ]

            if _execute_transaction(conn, queries_and_params):
                # Transaction succeeded. Wallet debited and order inserted.
                # Get the order ID.
                row = fetch_one(conn, 'SELECT ord_id FROM "Order" WHERE usr_id = ? ORDER BY ord_id DESC LIMIT 1', (usr_id,))
                new_ord_id = row[0] if row else None

                # Update session wallet to reflect the debit
                session['Wallet'] = user_wallet_cents - total_cents
                
            else:
                # Transaction failed. Most likely due to the `wallet >= ?` check failing (insufficient funds).
                # Re-fetch wallet balance to confirm the insufficient funds error.
                updated_wallet_row = fetch_one(conn, 'SELECT wallet FROM "User" WHERE usr_id = ?', (usr_id,))
                updated_wallet = updated_wallet_row[0] if updated_wallet_row else 0
                
                if updated_wallet < total_cents:
                    return jsonify({"ok": False, "error": "insufficient_funds"}), 402
                
                # Fallback for unexpected DB error during atomic transaction.
                return jsonify({"ok": False, "error": "db_failed"}), 500

        except Exception as e:
            print(f"Order Placement Error: {e}")
            return jsonify({"ok": False, "error": "server_error"}), 500

        finally:
            close_connection(conn)

        if new_ord_id is None:
             return jsonify({"ok": False, "error": "order_id_missing"}), 500
        
        return jsonify({"ok": True, "ord_id": new_ord_id})

        # Insert the single order row with status "Ordered"
        conn = create_connection(db_file)
        try:
            execute_query(conn, '''
                INSERT INTO "Order" (rtr_id, usr_id, details, status)
                VALUES (?, ?, ?, ?)
            ''', (rtr_id, usr_id, json.dumps(details), OrderStatus.ORDERED.value))
            row = fetch_one(conn, 'SELECT last_insert_rowid()')
            new_ord_id = row[0] if row else None
        finally:
            close_connection(conn)

        return jsonify({"ok": True, "ord_id": new_ord_id})

    # ---- (optional) legacy GET single-item path, kept for compatibility ----
    # If you don't need this anymore, you can remove the whole GET section.
    # Expect query: itm_id, qty, notes, delivery, tip, eta, date, meal
    itm_id = int(request.args.get("itm_id") or 0)
    if itm_id <= 0:
        return redirect(url_for("orders"))

    try:
        qty = max(1, int(request.args.get("qty", "1")))
    except ValueError:
        qty = 1
    delivery_type = (request.args.get("delivery") or "delivery").lower()
    if delivery_type not in ("delivery", "pickup"):
        delivery_type = "delivery"
    try:
        tip_dollars = _money(float(request.args.get("tip", "0")))
    except Exception:
        tip_dollars = 0.0
    try:
        eta_minutes = int(request.args.get("eta", "40"))
    except Exception:
        eta_minutes = 40
    iso_date = (request.args.get("date") or datetime.now().date().isoformat())
    try:
        meal = int(request.args.get("meal", "3"))
    except Exception:
        meal = 3
    notes = (request.args.get("notes") or "").strip()

    # Look up item & restaurant strictly
    conn = create_connection(db_file)
    try:
        mi = fetch_one(conn, '''
            SELECT m.itm_id, m.rtr_id, m.name, m.price, r.name
            FROM "MenuItem" m
            JOIN "Restaurant" r ON r.rtr_id = m.rtr_id
            WHERE m.itm_id = ?
        ''', (itm_id,))
    finally:
        close_connection(conn)
    if not mi:
        return redirect(url_for("orders"))

    item_id, rtr_id, item_name, price_cents, restaurant_name = mi
    unit_price = _cents_to_dollars(price_cents)
    line_total = _money(unit_price * qty)

    tax = _money(line_total * 0.0725)
    delivery_fee = 3.99 if delivery_type == "delivery" else 0.00
    service_fee = 1.49
    total = _money(line_total + tax + delivery_fee + service_fee + tip_dollars)

    details = {
        "placed_at": datetime.now().astimezone().isoformat(),
        "restaurant_id": int(rtr_id),
        "items": [{
            "itm_id": int(item_id),
            "name": item_name,
            "qty": int(qty),
            "unit_price": unit_price,
            "line_total": line_total,
            **({"notes": notes} if notes else {})
        }],
        "charges": {
            "subtotal": line_total,
            "tax": tax,
            "delivery_fee": delivery_fee,
            "service_fee": service_fee,
            "tip": tip_dollars,
            "total": total
        },
        "delivery_type": delivery_type,
        "eta_minutes": int(eta_minutes),
        "date": iso_date,
        "meal": meal
    }

    conn = create_connection(db_file)
    try:
        execute_query(conn, '''
            INSERT INTO "Order" (rtr_id, usr_id, details, status)
            VALUES (?, ?, ?, ?)
        ''', (rtr_id, usr_id, json.dumps(details), OrderStatus.ORDERED.value))
        row = fetch_one(conn, 'SELECT last_insert_rowid()')
        new_ord_id = row[0] if row else None
    finally:
        close_connection(conn)

    return redirect(url_for("profile") + (f"?ordered={new_ord_id}" if new_ord_id else ""))

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
            WHERE instock IS NULL OR instock = 1
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
            WHERE instock IS NULL OR instock = 1
        ''')
        # Fetch all reviews, including the user's name for display
        review_rows = fetch_all(conn, '''
            SELECT 
                r.rtr_id, r.rating, r.title, r.description, u.first_name, u.last_name
            FROM "Review" r
            JOIN "User" u ON r.usr_id = u.usr_id
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
                "user_name": f"{first_name} {last_name}",
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
        if session.get('usr_id') and row[0] != session['usr_id']:
            abort(403)
        # If usr_id not in session (older sessions), compare via email
        if not session.get('usr_id'):
            # Resolve current user's usr_id by email
            urow = fetch_one(conn, 'SELECT usr_id FROM "User" WHERE email = ?', (session.get('Email'),))
            if not urow or urow[0] != row[0]:
                abort(403)

        pdf_bytes = generate_order_receipt_pdf(db_file, ord_id)  # returns bytes
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
        Response: HTML page showing rows/columns for a selected table (requires login).
    """
    if session.get('Username') is None:
        return redirect(url_for('login'))

    allowed_tables = {'User', 'Restaurant', 'MenuItem', 'Order', 'Review'}
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

@app.route('/generate_plan', methods=['POST'])
def generate_plan():
    if session.get("Username") is None:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    # 1. Fetch User Metadata (Preferences & Allergies)
    conn = create_connection(db_file)
    try:
        user = fetch_one(conn, 'SELECT preferences, allergies, generated_menu FROM "User" WHERE email = ?', (session.get("Email"),))
        if not user:
            return jsonify({"ok": False, "error": "User not found"}), 404
        
        prefs, allergies, current_menu = user[0] or "", user[1] or "", user[2] or ""

        # 2. Initialize Generator
        # Using 500 tokens as defined in your system
        gen = MenuGenerator(tokens=500)
        
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
        print(f"Generation Error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
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
            'Delivered': []
        }
        
        for row in order_rows:
            ord_id, rtr_id, usr_id, details_json, status, first_name, last_name, restaurant_name = row
            
            # Parse details to get placed_at and total
            placed_at = None
            total = None
            placed_at_display = ""
            
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
                    
                    # Get total from charges
                    charges = details.get("charges", {})
                    total = charges.get("total") or charges.get("grand_total")
                    
                except Exception as e:
                    print(f"Error parsing order details: {e}")
                    continue
            
            # Default status if missing
            if not status:
                status = 'Ordered'
            
            # Build order object
            order = {
                'ord_id': ord_id,
                'customer_name': f"{first_name} {last_name}",
                'restaurant_name': restaurant_name,
                'total': f"${total:.2f}" if total else "N/A",
                'placed_at': placed_at_display,
                'status': status
            }
            
            # Add to appropriate status group
            if status in orders_by_status:
                orders_by_status[status].append(order)
        
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
        orders_by_status=orders_by_status,
        tickets=tickets,
        current_page=page,
        total_pages=total_pages,
        total_tickets=total_tickets
    )

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
            # Update both status and response
            execute_query(
                conn, 
                'UPDATE Ticket SET status = ?, response = ? WHERE ticket_id = ?', 
                (final_status, response_text, ticket_id)
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
        return redirect(url_for('profile') + f'?ticket_error=message_too_short&ord_id={ord_id}&message={message}')
    
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
                charges = d.get("charges", {})
                subtotal = float(charges.get("subtotal", 0))
                tax = float(charges.get("tax", 0))
                fee = float(charges.get("delivery_fee", 0)) + float(charges.get("service_fee", 0))
                tip = float(charges.get("tip", 0))
                total = float(charges.get("total", 0))
                
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
                    u_price = float(item.get("unit_price", 0))
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
        print(f"Insights Error: {e}")
        return jsonify({"error": str(e)}), 500
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