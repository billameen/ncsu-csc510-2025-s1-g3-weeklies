"""
Order receipts as PDFs, drawn with ReportLab: `generate_order_receipt_pdf(db_file, ord_id)`
returns the bytes served by `/orders/<id>/receipt.pdf`, including the order's ledger IDs (M2).
"""
import json
from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib import colors

from sqlQueries import create_connection, close_connection, fetch_one, fetch_all
from charges import item_cents, order_charges_cents
from money import format_cents


def _safe_str(x):
    """
    Safely convert a value to string, avoiding None.
    Args:
        x (Any): The input value to convert.
    Returns:
        str: Empty string if None, otherwise stringified value.
    """
    return "" if x is None else str(x)


def _money(x):
    """
    Format a numeric value as a currency string.
    Args:
        x (float | int | str): The numeric amount to format.
    Returns:
        str: The value formatted as a dollar amount (e.g., "$12.34"), or empty string on failure.
    """
    try:
        return f"${float(x):.2f}"
    except Exception:
        return ""


def _dt_display(iso_str):
    """
    Format an ISO timestamp string into a readable form.
    Args:
        iso_str (str): ISO 8601 datetime string.
    Returns:
        str: A formatted timestamp 'YYYY-MM-DD HH:MM' or the original string if invalid.
    """
    if not iso_str:
        return ""
    try:
        return datetime.fromisoformat(iso_str).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str


def receipt_ledger_lines(conn, details: dict) -> list:
    """
    Ledger references printed on a receipt (M2): the ID of the ledger transaction
    that paid for the order and, if the order was refunded, the refund's ID.
    Orders placed before the ledger existed have none.
    Args:
        conn (sqlite3.Connection): Active database connection.
        details (dict): The order's parsed details JSON.
    Returns:
        list[str]: Zero, one or two lines of text.
    """
    txn_id = (details or {}).get("ledger_txn_id")
    if not txn_id:
        return []
    lines = [f"Ledger transaction #{txn_id}"]
    try:
        row = conn.execute(
            'SELECT txn_id FROM "LedgerTransaction" WHERE reverses_txn_id = ?', (txn_id,)
        ).fetchone()
    except Exception:
        row = None
    if row:
        lines.append(f"Refunded in full (ledger transaction #{row[0]})")
    return lines


def generate_order_receipt_pdf(db_file: str, ord_id: int) -> bytes:
    """
    Generate a PDF receipt for a given order.
    Args:
        db_file (str): Path to the SQLite database file.
        ord_id (int): Order ID for which to generate the receipt.
    Returns:
        bytes: The binary PDF data as a bytes object.
    """
    conn = create_connection(db_file)
    try:
        # Order: ord_id,rtr_id,usr_id,details,status
        orow = fetch_one(conn, 'SELECT ord_id, rtr_id, usr_id, details, status FROM "Order" WHERE ord_id = ?', (ord_id,))
        if not orow:
            raise ValueError("Order not found")

        ord_id, rtr_id, usr_id, details, status = orow

        # User
        urow = fetch_one(conn,
                         'SELECT first_name, last_name, email, phone FROM "User" WHERE usr_id = ?',
                         (usr_id,))
        first_name, last_name, email, phone = (urow or ("", "", "", ""))

        # Restaurant
        rrow = fetch_one(conn,
                         'SELECT name, address, city, state, zip, phone FROM "Restaurant" WHERE rtr_id = ?',
                         (rtr_id,))
        r_name, r_addr, r_city, r_state, r_zip, r_phone = (rrow or ("", "", "", "", "", ""))

        # Parse details JSON (new format)
        j = {}
        try:
            j = json.loads(details or "{}")
        except Exception:
            j = {}

        placed_at = _dt_display(j.get("placed_at") or j.get("time"))
        delivery_type = _safe_str(j.get("delivery_type"))
        notes = _safe_str(j.get("notes"))

        items = j.get("items") or []
        # Charges in integer cents: new orders store "charges_cents", older orders
        # stored float dollars under "charges" (see charges.py). A charge an old
        # order never recorded is left off the receipt, as before.
        cents = order_charges_cents(j)
        stored = j.get("charges_cents") if isinstance(j.get("charges_cents"), dict) else (j.get("charges") or {})

        def _shown(key):
            return format_cents(cents[key]) if key in stored else None

        subtotal = _shown("subtotal")
        tax = _shown("tax")
        delivery_fee = _shown("delivery_fee")
        service_fee = _shown("service_fee")
        tip = _shown("tip")
        total = format_cents(cents["total"]) if stored else ""
        ledger_lines = receipt_ledger_lines(conn, j)

        # --------- Build PDF ----------
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter
        margin = 0.75 * inch
        y = height - margin

        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margin, y, f"Receipt · Order #{ord_id}")
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.grey)
        c.drawString(margin, y - 14, f"Status: {_safe_str(status)}")
        c.drawRightString(width - margin, y - 14, f"Placed: {placed_at}")
        for i, line in enumerate(ledger_lines):
            c.drawString(margin, y - 26 - 12 * i, line)
        c.setFillColor(colors.black)
        y -= 30 + 12 * len(ledger_lines)

        # Parties
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, y, "Billed To")
        c.setFont("Helvetica", 10)
        c.drawString(margin, y - 14, f"{_safe_str(first_name)} {_safe_str(last_name)}")
        c.drawString(margin, y - 28, f"Email: {_safe_str(email)}")
        c.drawString(margin, y - 42, f"Phone: {_safe_str(phone)}")

        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(width - margin, y, "Restaurant")
        c.setFont("Helvetica", 10)
        c.drawRightString(width - margin, y - 14, _safe_str(r_name))
        c.drawRightString(width - margin, y - 28, f"{_safe_str(r_addr)}")
        c.drawRightString(width - margin, y - 42, f"{_safe_str(r_city)}, {_safe_str(r_state)} {_safe_str(r_zip)}")
        c.drawRightString(width - margin, y - 56, f"Phone: {_safe_str(r_phone)}")

        y -= 78

        # Divider
        c.setStrokeColor(colors.lightgrey)
        c.line(margin, y, width - margin, y)
        y -= 16

        # Items table header
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, "Qty")
        c.drawString(margin + 40, y, "Item")
        c.drawRightString(width - margin - 140, y, "Unit")
        c.drawRightString(width - margin, y, "Line")
        y -= 12
        c.setStrokeColor(colors.lightgrey)
        c.line(margin, y, width - margin, y)
        y -= 10
        c.setFont("Helvetica", 10)

        # Items rows
        for it in items:
            qty = _safe_str(it.get("qty"))
            name = _safe_str(it.get("name"))
            unit_cents, line_cents = item_cents(it)
            unit = format_cents(unit_cents)
            line = format_cents(line_cents)

            c.drawString(margin, y, qty)
            c.drawString(margin + 40, y, name[:60])
            c.drawRightString(width - margin - 140, y, unit)
            c.drawRightString(width - margin, y, line)
            y -= 14
            if y < 1.25 * inch:
                c.showPage()
                y = height - margin
                c.setFont("Helvetica", 10)

        # Divider
        y -= 6
        c.setStrokeColor(colors.lightgrey)
        c.line(margin, y, width - margin, y)
        y -= 12

        # Charges
        c.setFont("Helvetica", 10)
        def row(label, value):
            """
            Draw a label-value row for a charge line.
            Args:
                label (str): Description of the charge (e.g., 'Tax', 'Subtotal').
                value (str | None): The formatted amount, or None to skip the row.
            Returns:
                None
            """
            nonlocal y
            if value is None or value == "":
                return
            c.drawRightString(width - margin - 140, y, label)
            c.drawRightString(width - margin, y, value)
            y -= 14

        row("Subtotal", subtotal)
        row("Tax", tax)
        row("Delivery fee", delivery_fee)
        row("Service fee", service_fee)
        row("Tip", tip)

        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(width - margin - 140, y, "Total")
        c.drawRightString(width - margin, y, total)
        y -= 18

        # Footer notes
        c.setFont("Helvetica", 9)
        if delivery_type:
            c.drawString(margin, y, f"Delivery type: {delivery_type}")
            y -= 12
        if notes:
            c.drawString(margin, y, f"Notes: {notes[:120]}")
            y -= 12

        c.setFillColor(colors.grey)
        c.drawString(margin, 0.6 * inch, "Thank you for your order!")
        c.setFillColor(colors.black)

        c.showPage()
        c.save()
        pdf_bytes = buf.getvalue()
        buf.close()
        return pdf_bytes

    finally:
        close_connection(conn)
