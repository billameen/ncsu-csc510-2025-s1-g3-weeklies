import json
from types import SimpleNamespace
from app import pdf_receipt as m

def _fake_conn():
    return SimpleNamespace()

def test_generate_pdf_unit_db_mocks(monkeypatch):
    order_details = {
        "placed_at": "2025-11-05T13:45:00",
        "delivery_type": "delivery",
        "notes": "Leave at door",
        "items": [
            {"qty": 2, "name": "Burrito", "unit_price": 8.5, "line_total": 17.0},
            {"qty": 1, "name": "Soda", "unit_price": 2.0, "line_total": 2.0},
        ],
        "charges": {"subtotal": 19.0, "tax": 1.50, "tip": 2.25, "total": 22.75},
    }

    def fake_create_connection(db_file):
        assert isinstance(db_file, str)
        return _fake_conn()

    def fake_fetch_one(conn, sql, params):
        sql = sql.lower()
        if " from \"order\"" in sql:
            return (1, 10, 100, json.dumps(order_details), "paid")
        if " from \"user\"" in sql:
            return ("Ada", "Lovelace", "ada@example.com", "555-0000")
        if " from \"restaurant\"" in sql:
            return ("Tasty Place", "123 Main", "Raleigh", "NC", "27606", "555-1111")
        return None

    calls = {"closed": False}
    def fake_close_connection(conn):
        calls["closed"] = True

    monkeypatch.setattr(m, "create_connection", fake_create_connection)
    monkeypatch.setattr(m, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(m, "close_connection", fake_close_connection)

    pdf_bytes = m.generate_order_receipt_pdf("fake.db", 1)
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert pdf_bytes.startswith(b"%PDF")
    assert calls["closed"] is True  # ensure connection was closed

def test_generate_pdf_unit_order_not_found(monkeypatch):
    monkeypatch.setattr(m, "create_connection", lambda _: _fake_conn())
    monkeypatch.setattr(m, "fetch_one", lambda *_: None)  # first query returns no order
    monkeypatch.setattr(m, "close_connection", lambda *_: None)
    import pytest
    with pytest.raises(ValueError):
        m.generate_order_receipt_pdf("fake.db", 999)
