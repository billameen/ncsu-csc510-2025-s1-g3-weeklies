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

The tax rate and fees come from the fee model in ``planner/fees.py`` (M4), shared
with the meal planner: each restaurant can have its own delivery and service fee, and
restaurants without their own use the defaults below (the pre-M4 charges).
"""
from money import MoneyError, parse_cents
from planner.fees import DEFAULT_FEES, FeeSchedule

TAX_RATE = DEFAULT_FEES.tax_rate
DELIVERY_FEE_CENTS = DEFAULT_FEES.delivery_fee_cents
SERVICE_FEE_CENTS = DEFAULT_FEES.service_fee_cents

#: The charges every order has, in display order. ``total`` is the sum of the others.
CHARGE_PARTS = ("subtotal", "tax", "delivery_fee", "service_fee", "tip")
CHARGE_KEYS = CHARGE_PARTS + ("total",)


def tax_cents(subtotal_cents: int, schedule: FeeSchedule = DEFAULT_FEES) -> int:
    """Sales tax on a subtotal, rounded half up to the cent."""
    _require_cents(subtotal_cents, "subtotal")
    return schedule.tax_cents(subtotal_cents)


def compute_charges(lines, delivery_type: str, tip_cents: int = 0, *,
                    schedule: FeeSchedule = DEFAULT_FEES, rtr_id: int | None = None) -> dict:
    """Work out an order's charges in cents.

    Args:
        lines: iterable of ``(unit_price_cents, qty)`` for each item line.
        delivery_type: ``"delivery"`` (adds the delivery fee) or ``"pickup"``.
        tip_cents: tip in cents, must be >= 0.
        schedule: the fee model (tax rate and per-restaurant fees); defaults to the
            pre-M4 fees.
        rtr_id: the restaurant the order is from, to look up its fees.
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
    fees = schedule.for_restaurant(rtr_id)
    charges = {
        "subtotal": subtotal,
        "tax": tax_cents(subtotal, schedule),
        "delivery_fee": fees.delivery_fee_cents if delivery_type == "delivery" else 0,
        "service_fee": fees.service_fee_cents,
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
