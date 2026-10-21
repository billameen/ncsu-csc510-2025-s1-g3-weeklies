import json, sqlite3, tempfile, os
from pdf_receipt import generate_order_receipt_pdf
import pdf_receipt as mod

SCHEMA = """
CREATE TABLE "User"(usr_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT, phone TEXT);
CREATE TABLE "Restaurant"(rtr_id INTEGER PRIMARY KEY, name TEXT, address TEXT, city TEXT, state TEXT, zip TEXT, phone TEXT);
CREATE TABLE "Order"(ord_id INTEGER PRIMARY KEY, rtr_id INTEGER, usr_id INTEGER, details TEXT, status TEXT);
"""

def test_generate_receipt_many_items_spans_pages(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "app.db")
        con = sqlite3.connect(db_path); cur = con.cursor()
        for stmt in SCHEMA.strip().split(";"):
            if stmt.strip():
                cur.execute(stmt)
        cur.execute('INSERT INTO "User"(usr_id, first_name, last_name, email, phone) VALUES (100,"Linus","Torvalds","linus@example.com","555-2222")')
        cur.execute('INSERT INTO "Restaurant"(rtr_id, name, address, city, state, zip, phone) VALUES (10,"Code Cafe","1 Kernel Way","Raleigh","NC","27606","555-3333")')

        items = [{"qty":1,"name":f"Item {i}","unit_price":1.0,"line_total":1.0} for i in range(60)]
        details = {"placed_at":"2025-11-05T12:00:00","items":items,"charges":{"subtotal":60,"tax":4.8,"total":64.8}}
        cur.execute('INSERT INTO "Order"(ord_id, rtr_id, usr_id, details, status) VALUES (1,10,100,?,?)', (json.dumps(details), "paid"))
        con.commit(); con.close()

        monkeypatch.setattr(mod, "create_connection", lambda p: sqlite3.connect(p))
        monkeypatch.setattr(mod, "close_connection", lambda c: c.close())

        pdf = generate_order_receipt_pdf(db_path, 1)
        assert pdf.startswith(b"%PDF")
        # Expect a larger PDF due to multiple pages
        assert len(pdf) > 2000
