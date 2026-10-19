"""Order charges in integer cents (M2).

Orders used to compute and store their charges as float dollars
(``subtotal * 0.0725``, ``3.99``, ...). Every charge is now an ``int`` number of
cents: computed here from the menu prices (already stored in cents), saved on
the order as ``details["charges_cents"]``, and posted to the wallet ledger.

Orders saved before this change still have float dollars under
``details["charges"]``; ``order_charges_cents`` reads both formats, so old
orders keep displaying correctly.

Tax is ``TAX_RATE`` of the subtotal, rounded half up to the cent, the same
result the old float code gave (e.g. 7.25% of $10.00 = 72.5 cents -> 73 cents).

The rates themselves live in ``pricing.py`` (shared with the meal planner) and
are converted exactly to ``Decimal`` / integer cents here, once, at import.
"""
from decimal import Decimal, ROUND_HALF_UP

import pricing
from money import MoneyError, parse_cents

TAX_RATE = Decimal(str(pricing.TAX_RATE))
DELIVERY_FEE_CENTS = parse_cents(pricing.DELIVERY_FEE)
SERVICE_FEE_CENTS = parse_cents(pricing.SERVICE_FEE)

#: The charges every order has, in display order. ``total`` is the sum of the others.
CHARGE_PARTS = ("subtotal", "tax", "delivery_fee", "service_fee", "tip")
CHARGE_KEYS = CHARGE_PARTS + ("total",)


def tax_cents(subtotal_cents: int) -> int:
    """Sales tax on a subtotal, rounded half up to the cent."""
    _require_cents(subtotal_cents, "subtotal")
    return int((Decimal(subtotal_cents) * TAX_RATE).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def compute_charges(lines, delivery_type: str, tip_cents: int = 0) -> dict:
    """Work out an order's charges in cents.

    Args:
        lines: iterable of ``(unit_price_cents, qty)`` for each item line.
        delivery_type: ``"delivery"`` (adds the delivery fee) or ``"pickup"``.
        tip_cents: tip in cents, must be >= 0.
    Returns:
        dict with ``subtotal``, ``tax``, ``delivery_fee``, ``service_fee``,
        ``tip`` and ``total``, all ``int`` cents.
    Raises:
        ValueError: a non-int amount, a negative price or tip, or a quantity < 1.
    """
    subtotal = 0
    for unit, qty in lines:
        _require_cents(unit, "unit price")
        if type(qty) is not int or qty < 1:
            raise ValueError(f"quantity must be a positive int, got {qty!r}")
        subtotal += unit * qty
    _require_cents(tip_cents, "tip")
    charges = {
        "subtotal": subtotal,
        "tax": tax_cents(subtotal),
        "delivery_fee": DELIVERY_FEE_CENTS if delivery_type == "delivery" else 0,
        "service_fee": SERVICE_FEE_CENTS,
        "tip": tip_cents,
    }
    charges["total"] = sum(charges[k] for k in CHARGE_PARTS)
    return charges


def _require_cents(value, what):
    if type(value) is not int or value < 0:
        raise ValueError(f"{what} must be a non-negative int number of cents, got {value!r}")


def _legacy_cents(value) -> int:
    """Old orders stored dollars as floats; convert one to cents (0 if missing/bad)."""
    if value is None:
        return 0
    try:
        return parse_cents(value)
    except MoneyError:
        return 0


def order_charges_cents(details: dict) -> dict:
    """An order's charges in cents, for both new and old orders.

    New orders store ``details["charges_cents"]`` (ints). Old orders stored
    float dollars under ``details["charges"]``, sometimes with ``grand_total``
    or ``amount`` instead of ``total``; those are converted exactly.
    """
    details = details or {}
    new = details.get("charges_cents")
    if isinstance(new, dict):
        out = {k: int(new.get(k) or 0) for k in CHARGE_PARTS}
        out["total"] = int(new["total"]) if new.get("total") is not None else sum(out.values())
        return out

    old = details.get("charges") or {}
    out = {k: _legacy_cents(old.get(k)) for k in CHARGE_PARTS}
    total = next((old.get(k) for k in ("total", "grand_total", "amount") if old.get(k) is not None),
                 None)
    out["total"] = _legacy_cents(total) if total is not None else sum(out.values())
    return out


def item_cents(item: dict):
    """``(unit_price_cents, line_total_cents)`` of one stored order line, new or old format."""
    item = item or {}
    if "unit_price_cents" in item:
        unit = int(item.get("unit_price_cents") or 0)
        line = int(item.get("line_total_cents") or unit * int(item.get("qty") or 1))
        return unit, line
    unit = _legacy_cents(item.get("unit_price"))
    line = item.get("line_total")
    return unit, (_legacy_cents(line) if line is not None else unit * int(item.get("qty") or 1))
