import pytest
from pdf_receipt import _safe_str, _money, _dt_display

def test_safe_str_handles_none_and_values():
    assert _safe_str(None) == ""
    assert _safe_str("") == ""
    assert _safe_str(123) == "123"
    assert _safe_str("abc") == "abc"

def test_money_formats_numbers_and_handles_bad_input():
    assert _money(10) == "$10.00"
    assert _money(3.456) == "$3.46"
    assert _money("7.1") == "$7.10"
    assert _money(None) == ""          # gracefully empty
    assert _money("not-a-number") == ""  # invalid → empty

@pytest.mark.parametrize(
    "given,expected_prefix",
    [
        ("2025-11-05T13:45:00", "2025-11-05 13:45"),
        ("2025-01-01 00:00:00", "2025-01-01 00:00"),  # already non-ISO-ish → passed through or parsed
    ],
)
def test_dt_display_formats_known_strings(given, expected_prefix):
    out = _dt_display(given)
    assert out.startswith(expected_prefix)

def test_dt_display_handles_empty_or_bad():
    assert _dt_display("") == ""
    assert _dt_display(None) == ""
    assert _dt_display("not-a-date") == "not-a-date"
