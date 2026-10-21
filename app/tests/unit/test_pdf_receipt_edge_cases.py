import sqlite3
import os
import json
import tempfile

import pdf_receipt as mod
from pdf_receipt import generate_order_receipt_pdf


SCHEMA = """
CREATE TABLE "User"(usr_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT, phone TEXT);
CREATE TABLE "Restaurant"(rtr_id INTEGER PRIMARY KEY, name TEXT, address TEXT, city TEXT, state TEXT, zip TEXT, phone TEXT);
CREATE TABLE "Order"(ord_id INTEGER PRIMARY KEY, rtr_id INTEGER, usr_id INTEGER, details TEXT, status TEXT);
"""


def _init_db(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    for stmt in SCHEMA.strip().split(";"):
        if stmt.strip():
            cur.execute(stmt)
    return con, cur


def test_generate_receipt_handles_non_json_details_and_missing_parties(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "app.db")
        con, cur = _init_db(db_path)

        # Insert an order that references non-existent user and restaurant ids
        details = "NOT JSON AT ALL"
        cur.execute(
            'INSERT INTO "Order"(ord_id, rtr_id, usr_id, details, status) VALUES (1, 999, 999, ?, ?)',
            (details, "paid"),
        )
        con.commit()
        con.close()

        # Use direct sqlite3 connections for this test
        monkeypatch.setattr(mod, "create_connection", lambda p: sqlite3.connect(p))
        monkeypatch.setattr(mod, "close_connection", lambda c: c.close())

        pdf = generate_order_receipt_pdf(db_path, 1)
        assert pdf.startswith(b"%PDF")
        # Even with missing user/restaurant and bad JSON, we should get a non-trivial PDF
        assert len(pdf) > 400
