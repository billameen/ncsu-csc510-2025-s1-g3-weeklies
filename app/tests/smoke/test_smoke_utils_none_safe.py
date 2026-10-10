from pdf_receipt import _safe_str, _money, _dt_display

def test_smoke_utils_dont_raise():
    # None/empty inputs should never raise
    assert _safe_str(None) == ""
    assert _money(None) in ("",)  # empty string
    assert _dt_display(None) == ""
    assert _dt_display("") == ""
