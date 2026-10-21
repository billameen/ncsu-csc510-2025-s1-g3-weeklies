import json, sqlite3, tempfile, os
import pdf_receipt as mod
from pdf_receipt import generate_order_receipt_pdf

def test_smoke_minimal_receipt():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "mini.db")
        con = sqlite3.connect(db)
        con.executescript("""
        CREATE TABLE "User"(usr_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT, phone TEXT);
        CREATE TABLE "Restaurant"(rtr_id INTEGER PRIMARY KEY, name TEXT, address TEXT, city TEXT, state TEXT, zip TEXT, phone TEXT);
        CREATE TABLE "Order"(ord_id INTEGER PRIMARY KEY, rtr_id INTEGER, usr_id INTEGER, details TEXT, status TEXT);
        """)
        con.execute('INSERT INTO "User" VALUES (1,"A","B","a@b.com","555")')
        con.execute('INSERT INTO "Restaurant" VALUES (1,"R","Addr","City","ST","00000","555")')
        con.execute('INSERT INTO "Order" VALUES (1,1,1,?,?)', (json.dumps({"items":[],"charges":{"total":0}}), "created"))
        con.commit(); con.close()

        # direct sqlite connect
        mod.create_connection = lambda p: sqlite3.connect(p)
        mod.close_connection = lambda c: c.close()

        b = generate_order_receipt_pdf(db, 1)
        assert b.startswith(b"%PDF")
        assert len(b) > 400
