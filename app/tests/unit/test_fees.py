"""Tests for the fee model, planner/fees.py (M4)."""
import sqlite3
from decimal import ROUND_HALF_UP, Decimal

import pytest

from charges import compute_charges
from planner.fees import (
    DEFAULT_FEES,
    SYNTHETIC_DELIVERY_FEES_CENTS,
    FeeConfigError,
    FeeSchedule,
    RestaurantFees,
    ensure_fee_schema,
    load_fee_schedule,
    synthetic_delivery_fee_cents,
)
from planner.menu import meal_cost_cents


def _pre_m4_meal_cost(price_cents):
    """What a single delivered meal cost before M4: price + 7.25% tax + $3.99 + $1.49."""
    tax = (Decimal(price_cents) * Decimal("0.0725")).quantize(Decimal(1), ROUND_HALF_UP)
    return price_cents + int(tax) + 399 + 149


# --- Defaults reproduce today's charges ---------------------------------------

def test_default_fees_are_the_pre_m4_numbers():
    assert (DEFAULT_FEES.tax_rate, DEFAULT_FEES.delivery_fee_cents, DEFAULT_FEES.service_fee_cents) \
        == (Decimal("0.0725"), 399, 149)
    assert DEFAULT_FEES.overrides == {}


def test_default_fees_reproduce_every_single_meal_charge_up_to_50_dollars():
    assert [p for p in range(5001) if DEFAULT_FEES.meal_cost_cents(p) != _pre_m4_meal_cost(p)] == []
    assert meal_cost_cents(1000) == 1621


def test_default_checkout_charges_are_unchanged():
    assert compute_charges([(1000, 2)], "delivery", 200) == {
        "subtotal": 2000, "tax": 145, "delivery_fee": 399, "service_fee": 149,
        "tip": 200, "total": 2893,
    }


def test_a_21_meal_week_pays_115_dollars_8_cents_in_fees_before_any_food():
    # The issue's motivating number: 21 separate delivery orders at $3.99 + $1.49.
    assert 21 * DEFAULT_FEES.order_fee_cents() == 11508


# --- Per-restaurant overrides and pickup --------------------------------------

def test_a_restaurant_override_applies_only_to_that_restaurant():
    fees = FeeSchedule(overrides={3: RestaurantFees(199, 149)})
    assert fees.order_fee_cents(3) == 199 + 149
    assert fees.order_fee_cents(4) == 399 + 149
    assert fees.order_fee_cents(None) == 399 + 149
    assert compute_charges([(1000, 1)], "delivery", schedule=fees, rtr_id=3)["delivery_fee"] == 199


def test_pickup_has_no_delivery_fee_but_keeps_the_service_fee():
    fees = FeeSchedule(overrides={3: RestaurantFees(599, 99)})
    assert fees.order_fee_cents(3, pickup=True) == 99
    assert DEFAULT_FEES.order_fee_cents(pickup=True) == 149
    assert compute_charges([(1000, 1)], "pickup", schedule=fees, rtr_id=3)["delivery_fee"] == 0


# --- Invalid configuration ----------------------------------------------------

@pytest.mark.parametrize("make", [
    lambda: RestaurantFees(-1, 149),                       # negative delivery fee
    lambda: RestaurantFees(399, -149),                     # negative service fee
    lambda: RestaurantFees(3.99, 149),                     # dollars as a float
    lambda: RestaurantFees(True, 149),                     # bool is not money
    lambda: FeeSchedule(delivery_fee_cents=-5),
    lambda: FeeSchedule(service_fee_cents=-1),
    lambda: FeeSchedule(tax_rate=Decimal("-0.01")),
    lambda: FeeSchedule(tax_rate=Decimal("1")),
    lambda: FeeSchedule(tax_rate=0.0725),                  # must be a Decimal
    lambda: FeeSchedule(tax_rate=Decimal("NaN")),
    lambda: FeeSchedule(overrides={1: (199, 149)}),        # not RestaurantFees
])
def test_invalid_fee_configuration_is_refused(make):
    with pytest.raises(FeeConfigError):
        make()


def test_fee_config_errors_are_value_errors():
    assert issubclass(FeeConfigError, ValueError)


def test_overrides_cannot_be_changed_after_creation():
    fees = FeeSchedule(overrides={1: RestaurantFees(199, 149)})
    with pytest.raises(TypeError):
        fees.overrides[2] = RestaurantFees(1, 1)


# --- Loading from the database ------------------------------------------------

def test_a_database_without_the_fee_table_uses_the_defaults(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    assert load_fee_schedule(conn) is DEFAULT_FEES


def test_loading_overrides_with_null_meaning_default(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "f.db"))
    ensure_fee_schema(conn)
    conn.executemany('INSERT INTO "RestaurantFee" VALUES (?, ?, ?)', [(1, 199, None), (2, None, 99)])
    fees = load_fee_schedule(conn)
    assert fees.for_restaurant(1) == RestaurantFees(199, 149)
    assert fees.for_restaurant(2) == RestaurantFees(399, 99)
    assert fees.for_restaurant(3) == RestaurantFees(399, 149)


@pytest.mark.parametrize("row", [(1, -1, None), (1, None, -5), (1, 3.99, None)])
def test_the_database_refuses_invalid_fees(tmp_path, row):
    conn = sqlite3.connect(str(tmp_path / "f.db"))
    ensure_fee_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO "RestaurantFee" VALUES (?, ?, ?)', row)


# --- Seed data and migration --------------------------------------------------

def test_synthetic_fees_are_varied_and_between_1_99_and_5_99():
    fees = [synthetic_delivery_fee_cents(r) for r in range(1, 21)]
    assert all(199 <= f <= 599 and f % 50 == 49 for f in fees)
    assert set(fees) == set(SYNTHETIC_DELIVERY_FEES_CENTS)


def test_the_seed_gives_every_restaurant_its_synthetic_fee(tmp_path):
    from scripts.init_db import init_db

    db = tmp_path / "seed.db"
    init_db(db_file=str(db))
    conn = sqlite3.connect(str(db))
    restaurants = [r for (r,) in conn.execute('SELECT rtr_id FROM "Restaurant"')]
    fees = load_fee_schedule(conn)
    assert sorted(fees.overrides) == sorted(restaurants)
    assert all(fees.for_restaurant(r).delivery_fee_cents == synthetic_delivery_fee_cents(r)
               for r in restaurants)
    assert all(fees.for_restaurant(r).service_fee_cents == 149 for r in restaurants)


def test_the_migration_adds_missing_fees_and_never_changes_existing_ones(tmp_path):
    from migrations.add_restaurant_fees import migrate

    conn = sqlite3.connect(str(tmp_path / "m.db"))
    conn.execute('CREATE TABLE "Restaurant" (rtr_id INTEGER PRIMARY KEY)')
    conn.executemany('INSERT INTO "Restaurant" VALUES (?)', [(1,), (2,), (3,)])
    ensure_fee_schema(conn)
    conn.execute('INSERT INTO "RestaurantFee" VALUES (2, 1, 2)')   # someone's custom fee

    assert migrate(conn) == 2
    assert migrate(conn) == 0                                      # idempotent
    rows = dict((r, (d, s)) for r, d, s in conn.execute('SELECT * FROM "RestaurantFee"'))
    assert rows == {1: (synthetic_delivery_fee_cents(1), None), 2: (1, 2),
                    3: (synthetic_delivery_fee_cents(3), None)}


def test_the_planner_menu_and_eval_catalog_carry_the_fees(tmp_path):
    from scripts.init_db import init_db
    from planner.menu import load_menu
    from eval.catalog import load_catalog

    db = tmp_path / "seed.db"
    init_db(db_file=str(db))
    menu, catalog = load_menu(str(db)), load_catalog(str(db))
    assert menu.fees.overrides and menu.fees == catalog.fees
    r = next(iter(menu.fees.overrides))
    assert menu.fees.order_fee_cents(r) == synthetic_delivery_fee_cents(r) + 149
