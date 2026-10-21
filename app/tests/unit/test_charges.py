"""Tests for charges.py: order charges in integer cents (M2)."""
import pytest
from hypothesis import given, strategies as st

from charges import (
    DELIVERY_FEE_CENTS,
    SERVICE_FEE_CENTS,
    compute_charges,
    item_cents,
    order_charges_cents,
    tax_cents,
)


def test_a_delivery_order_matches_the_hand_computed_example():
    # 2 x $10.00, delivery, $2.00 tip: 2000 + 145 tax + 399 + 149 + 200 = 2893
    assert compute_charges([(1000, 2)], "delivery", 200) == {
        "subtotal": 2000, "tax": 145, "delivery_fee": 399, "service_fee": 149,
        "tip": 200, "total": 2893,
    }


def test_pickup_has_no_delivery_fee():
    c = compute_charges([(1000, 1)], "pickup")
    assert c["delivery_fee"] == 0 and c["total"] == 1000 + 73 + SERVICE_FEE_CENTS


def test_several_lines_add_up():
    c = compute_charges([(250, 3), (1199, 1)], "delivery", 0)
    assert c["subtotal"] == 750 + 1199
    assert c["total"] == c["subtotal"] + c["tax"] + DELIVERY_FEE_CENTS + SERVICE_FEE_CENTS


@pytest.mark.parametrize("subtotal,tax", [(0, 0), (1000, 73), (2000, 145), (1, 0), (7, 1), (6, 0)])
def test_tax_rounds_half_up(subtotal, tax):
    assert tax_cents(subtotal) == tax


def test_integer_tax_matches_the_old_float_formula_for_every_subtotal_up_to_500_dollars():
    old = lambda c: int(round(round(c / 100 * 0.0725 + 1e-9, 2) * 100))  # the pre-M2 code
    assert [c for c in range(50_001) if tax_cents(c) != old(c)] == []


@pytest.mark.parametrize("lines,tip", [
    ([(10.0, 1)], 0),          # float price
    ([(1000, 1.0)], 0),        # float quantity
    ([(1000, 0)], 0),          # zero quantity
    ([(-1, 1)], 0),            # negative price
    ([(1000, 1)], -1),         # negative tip
    ([(1000, 1)], 2.0),        # float tip
    ([(True, 1)], 0),          # bool is not money
])
def test_bad_inputs_are_refused(lines, tip):
    with pytest.raises(ValueError):
        compute_charges(lines, "delivery", tip)


@given(st.lists(st.tuples(st.integers(0, 50_000), st.integers(1, 20)), max_size=8),
       st.sampled_from(["delivery", "pickup"]), st.integers(0, 10_000))
def test_charges_are_ints_and_the_total_is_their_sum(lines, delivery_type, tip):
    c = compute_charges(lines, delivery_type, tip)
    assert all(type(v) is int for v in c.values())
    assert c["total"] == c["subtotal"] + c["tax"] + c["delivery_fee"] + c["service_fee"] + c["tip"]
    assert abs(c["tax"] * 10_000 - c["subtotal"] * 725) <= 5_000   # within half a cent


# --- Reading stored orders, new and old -----------------------------------------

def test_new_orders_are_read_as_stored():
    stored = {"charges_cents": {"subtotal": 2000, "tax": 145, "delivery_fee": 399,
                                "service_fee": 149, "tip": 200, "total": 2893}}
    assert order_charges_cents(stored)["total"] == 2893


def test_old_float_orders_still_read_exactly():
    old = {"charges": {"subtotal": 20.0, "tax": 1.45, "delivery_fee": 3.99,
                       "service_fee": 1.49, "tip": 2.0, "total": 28.93}}
    assert order_charges_cents(old) == {"subtotal": 2000, "tax": 145, "delivery_fee": 399,
                                        "service_fee": 149, "tip": 200, "total": 2893}


@pytest.mark.parametrize("old,total", [
    ({"charges": {"grand_total": 12.34}}, 1234),
    ({"charges": {"amount": "5.10"}}, 510),
    ({"charges": {"subtotal": 1.0, "tax": 0.07}}, 107),   # no total: sum of parts
    ({"charges": {"total": 0.0}}, 0),
    ({"charges": {"total": "garbage"}}, 0),
    ({}, 0),
    (None, 0),
])
def test_old_order_variants(old, total):
    assert order_charges_cents(old)["total"] == total


def test_item_prices_new_and_old():
    assert item_cents({"unit_price_cents": 250, "line_total_cents": 750, "qty": 3}) == (250, 750)
    assert item_cents({"unit_price": 2.5, "line_total": 7.5, "qty": 3}) == (250, 750)
    assert item_cents({"unit_price": 2.29, "qty": 2}) == (229, 458)
    assert item_cents({}) == (0, 0)
