"""
The fee model (M4): sales tax plus each order's delivery and service fees.

**These fees are a synthetic model** chosen for the course project, not real prices. The
defaults are the numbers checkout used before M4 (7.25% tax, $3.99 delivery, $1.49 service),
so an order is charged exactly as before unless its restaurant has its own fees.

Fees are charged per *order*, not per meal: an order from one restaurant pays one delivery
fee and one service fee however many items it holds, and a pickup order pays no delivery fee.
That is what lets the planner save money by putting meals into fewer orders (see
``planner.rules.fee_cost``).

Each restaurant may override the defaults in the ``RestaurantFee`` table. A restaurant
without a row, or with NULL in a column, uses the default for that fee.

All amounts are ``int`` cents and the tax rate is a ``Decimal``; nothing here is a float.

    from planner.fees import DEFAULT_FEES, load_fee_schedule

    fees = load_fee_schedule(conn)          # defaults + the database's overrides
    fees.order_fee_cents(rtr_id=3)          # delivery + service for one order
    fees.tax_cents(1000)                    # 73
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

DEFAULT_TAX_RATE = Decimal("0.0725")
DEFAULT_DELIVERY_FEE_CENTS = 399
DEFAULT_SERVICE_FEE_CENTS = 149

#: Delivery fees the seed data and migration give restaurants: $1.99 to $5.99.
SYNTHETIC_DELIVERY_FEES_CENTS = (199, 249, 299, 349, 399, 449, 499, 549, 599)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS "RestaurantFee" (
    rtr_id             INTEGER PRIMARY KEY REFERENCES "Restaurant"(rtr_id),
    delivery_fee_cents INTEGER CHECK (delivery_fee_cents IS NULL OR
                                      (typeof(delivery_fee_cents) = 'integer' AND delivery_fee_cents >= 0)),
    service_fee_cents  INTEGER CHECK (service_fee_cents IS NULL OR
                                      (typeof(service_fee_cents) = 'integer' AND service_fee_cents >= 0))
);
"""


class FeeConfigError(ValueError):
    """A fee or tax rate in the configuration is invalid (negative, not whole cents, ...)."""


def _check_cents(value, what) -> int:
    if type(value) is not int or value < 0:
        raise FeeConfigError(f"{what} must be a whole number of cents >= 0, got {value!r}")
    return value


@dataclass(frozen=True)
class RestaurantFees:
    """The fees one restaurant charges per order, in cents."""

    delivery_fee_cents: int
    service_fee_cents: int

    def __post_init__(self):
        _check_cents(self.delivery_fee_cents, "delivery_fee_cents")
        _check_cents(self.service_fee_cents, "service_fee_cents")

    def order_fee_cents(self, *, pickup: bool = False) -> int:
        """Fees for one order: service fee, plus the delivery fee unless it is picked up."""
        return self.service_fee_cents + (0 if pickup else self.delivery_fee_cents)


@dataclass(frozen=True)
class FeeSchedule:
    """
    Tax rate, default fees, and per-restaurant overrides.
    Attributes:
        tax_rate: Sales tax as a fraction, e.g. Decimal("0.0725").
        delivery_fee_cents: Default delivery fee per order.
        service_fee_cents: Default service fee per order.
        overrides: rtr_id -> RestaurantFees for restaurants with their own fees.
    Raises:
        FeeConfigError: A fee is negative or not whole cents, or the tax rate is not a
            Decimal from 0 up to (not including) 1.
    """

    tax_rate: Decimal = DEFAULT_TAX_RATE
    delivery_fee_cents: int = DEFAULT_DELIVERY_FEE_CENTS
    service_fee_cents: int = DEFAULT_SERVICE_FEE_CENTS
    overrides: Mapping[int, RestaurantFees] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.tax_rate, Decimal) or not self.tax_rate.is_finite() \
                or not Decimal(0) <= self.tax_rate < Decimal(1):
            raise FeeConfigError(f"tax_rate must be a Decimal from 0 to below 1, got {self.tax_rate!r}")
        _check_cents(self.delivery_fee_cents, "delivery_fee_cents")
        _check_cents(self.service_fee_cents, "service_fee_cents")
        for rtr_id, fees in self.overrides.items():
            if not isinstance(fees, RestaurantFees):
                raise FeeConfigError(f"override for restaurant {rtr_id!r} must be RestaurantFees")
        object.__setattr__(self, "overrides", MappingProxyType(dict(self.overrides)))

    @property
    def default(self) -> RestaurantFees:
        """The fees of a restaurant without its own."""
        return RestaurantFees(self.delivery_fee_cents, self.service_fee_cents)

    def for_restaurant(self, rtr_id: int | None) -> RestaurantFees:
        """The fees an order from this restaurant pays (the defaults if it has none)."""
        return self.overrides.get(rtr_id, self.default) if rtr_id is not None else self.default

    def order_fee_cents(self, rtr_id: int | None = None, *, pickup: bool = False) -> int:
        """Delivery (unless pickup) plus service fee for one order from rtr_id."""
        return self.for_restaurant(rtr_id).order_fee_cents(pickup=pickup)

    def tax_cents(self, subtotal_cents: int) -> int:
        """Tax on a subtotal, rounded half up to the cent."""
        _check_cents(subtotal_cents, "subtotal")
        return int((Decimal(subtotal_cents) * self.tax_rate).quantize(Decimal(1), ROUND_HALF_UP))

    def meal_cost_cents(self, price_cents: int, rtr_id: int | None = None) -> int:
        """One item ordered on its own for delivery: price + tax + that order's fees."""
        return price_cents + self.tax_cents(price_cents) + self.order_fee_cents(rtr_id)


#: The fee model with no per-restaurant overrides: exactly the pre-M4 charges.
DEFAULT_FEES = FeeSchedule()


def synthetic_delivery_fee_cents(rtr_id: int) -> int:
    """
    The made-up delivery fee the seed data gives restaurant rtr_id, from $1.99 to $5.99.
    Deterministic, so the seed data and the migration agree.
    """
    return SYNTHETIC_DELIVERY_FEES_CENTS[(int(rtr_id) * 7) % len(SYNTHETIC_DELIVERY_FEES_CENTS)]


def ensure_fee_schema(conn) -> None:
    """Create the RestaurantFee table if it does not exist."""
    conn.executescript(SCHEMA_SQL)


def load_fee_schedule(conn) -> FeeSchedule:
    """
    The default fees plus every override in the RestaurantFee table. A database without the
    table (e.g. one built before M4) simply has no overrides.
    Raises:
        FeeConfigError: A stored fee is invalid (the table's CHECKs normally prevent this).
    """
    try:
        rows = conn.execute(
            'SELECT rtr_id, delivery_fee_cents, service_fee_cents FROM "RestaurantFee"'
        ).fetchall()
    except sqlite3.OperationalError:
        return DEFAULT_FEES
    overrides = {
        rtr_id: RestaurantFees(
            DEFAULT_DELIVERY_FEE_CENTS if delivery is None else delivery,
            DEFAULT_SERVICE_FEE_CENTS if service is None else service,
        )
        for rtr_id, delivery, service in rows
    }
    return FeeSchedule(overrides=overrides)
