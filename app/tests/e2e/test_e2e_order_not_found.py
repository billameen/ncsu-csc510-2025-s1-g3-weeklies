import sqlite3, tempfile, os, pytest
import pdf_receipt as mod
from pdf_receipt import generate_order_receipt_pdf

def test_e2e_order_not_found_raises(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "prod.db")
        con = sqlite3.connect(db_path)
        con.executescript("""
        CREATE TABLE "User"(usr_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT, phone TEXT);
        CREATE TABLE "Restaurant"(rtr_id INTEGER PRIMARY KEY, name TEXT, address TEXT, city TEXT, state TEXT, zip TEXT, phone TEXT);
        CREATE TABLE "Order"(ord_id INTEGER PRIMARY KEY, rtr_id INTEGER, usr_id INTEGER, details TEXT, status TEXT);
        """)
        con.commit(); con.close()

        monkeypatch.setattr(mod, "create_connection", lambda p: sqlite3.connect(p))
        monkeypatch.setattr(mod, "close_connection", lambda c: c.close())

        with pytest.raises(ValueError):
            generate_order_receipt_pdf(db_path, 404)
