import json, sqlite3, tempfile, os
from pdf_receipt import generate_order_receipt_pdf
import pdf_receipt as mod

def test_e2e_full_flow_generates_pdf(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "prod.db")
        con = sqlite3.connect(db_path); cur = con.cursor()
        cur.executescript("""
        CREATE TABLE "User"(usr_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT, phone TEXT);
        CREATE TABLE "Restaurant"(rtr_id INTEGER PRIMARY KEY, name TEXT, address TEXT, city TEXT, state TEXT, zip TEXT, phone TEXT);
        CREATE TABLE "Order"(ord_id INTEGER PRIMARY KEY, rtr_id INTEGER, usr_id INTEGER, details TEXT, status TEXT);
        """)
        cur.execute('INSERT INTO "User" VALUES (200,"Grace","Hopper","grace@example.com","555-4444")')
        cur.execute('INSERT INTO "Restaurant" VALUES (30,"Navy Diner","77 Bug Blvd","Raleigh","NC","27606","555-5555")')

        details = {
            "placed_at":"2025-11-05T19:30:00",
            "delivery_type":"delivery",
            "notes":"Ring bell once",
            "items":[
                {"qty":2,"name":"Pasta","unit_price":12.0,"line_total":24.0},
                {"qty":1,"name":"Tea","unit_price":3.0,"line_total":3.0},
            ],
            "charges":{"subtotal":27.0,"tax":2.16,"delivery_fee":3.0,"service_fee":1.0,"tip":3.0,"total":36.16},
        }
        cur.execute('INSERT INTO "Order" VALUES (5,30,200,?,?)', (json.dumps(details), "paid"))
        con.commit(); con.close()

        monkeypatch.setattr(mod, "create_connection", lambda p: sqlite3.connect(p))
        monkeypatch.setattr(mod, "close_connection", lambda c: c.close())

        pdf = generate_order_receipt_pdf(db_path, 5)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 1200
