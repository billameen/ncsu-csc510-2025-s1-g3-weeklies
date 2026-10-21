import json, sqlite3, tempfile, os
from pdf_receipt import generate_order_receipt_pdf

SCHEMA = """
CREATE TABLE "User"(usr_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT, phone TEXT);
CREATE TABLE "Restaurant"(rtr_id INTEGER PRIMARY KEY, name TEXT, address TEXT, city TEXT, state TEXT, zip TEXT, phone TEXT);
CREATE TABLE "Order"(ord_id INTEGER PRIMARY KEY, rtr_id INTEGER, usr_id INTEGER, details TEXT, status TEXT);
"""

def test_generate_receipt_sqlite_basic(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "app.db")
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        for stmt in SCHEMA.strip().split(";"):
            if stmt.strip():
                cur.execute(stmt)
        cur.execute('INSERT INTO "User"(usr_id, first_name, last_name, email, phone) VALUES (100,"Ada","Lovelace","ada@example.com","555-0000")')
        cur.execute('INSERT INTO "Restaurant"(rtr_id, name, address, city, state, zip, phone) VALUES (10,"Tasty Place","123 Main","Raleigh","NC","27606","555-1111")')
        details = {
            "placed_at": "2025-11-05T13:45:00",
            "delivery_type": "pickup",
            "items": [{"qty":1,"name":"Bowl","unit_price":9.0,"line_total":9.0}],
            "charges": {"subtotal":9.0,"tax":0.72,"total":9.72},
        }
        cur.execute('INSERT INTO "Order"(ord_id, rtr_id, usr_id, details, status) VALUES (1,10,100,?,?)', (json.dumps(details), "paid"))
        con.commit(); con.close()

        # patch create_connection to use sqlite3 directly (bypasses your sqlQueries impl)
        import pdf_receipt as mod
        monkeypatch.setattr(mod, "create_connection", lambda path: sqlite3.connect(path))
        monkeypatch.setattr(mod, "close_connection", lambda c: c.close())

        pdf = generate_order_receipt_pdf(db_path, 1)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 800
