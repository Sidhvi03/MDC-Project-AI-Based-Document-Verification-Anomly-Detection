import sqlite3, json
from app.config import DB_PATH

def connect():
    con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row; return con

def init_db():
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL, file_hash TEXT NOT NULL UNIQUE,
        invoice_no TEXT, invoice_date TEXT, seller TEXT, client TEXT, tax_id TEXT, total REAL, total_raw TEXT,
        status TEXT NOT NULL, reasons TEXT NOT NULL, duplicate_status TEXT, anomaly_status TEXT,
        ocr_text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_invoices_invoice_no ON invoices(invoice_no)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_invoices_seller_invoice ON invoices(seller, invoice_no)')

def get_all():
    with connect() as con: return [dict(r) for r in con.execute('SELECT * FROM invoices ORDER BY id DESC').fetchall()]

def get_by_hash(value):
    with connect() as con:
        row=con.execute('SELECT * FROM invoices WHERE file_hash=?',(value,)).fetchone()
        return dict(row) if row else None

def insert(fields, decision, duplicate, anomaly, file_hash, file_name):
    with connect() as con:
        cur=con.execute('''INSERT INTO invoices(file_name,file_hash,invoice_no,invoice_date,seller,client,tax_id,total,total_raw,status,reasons,duplicate_status,anomaly_status,ocr_text)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(file_name,file_hash,fields.get('invoice_no'),fields.get('invoice_date'),fields.get('seller'),fields.get('client'),fields.get('tax_id'),fields.get('total'),fields.get('total_raw'),decision['status'],json.dumps(decision['reasons']),duplicate.get('status'),anomaly.get('status'),fields.get('ocr_text','')))
        return cur.lastrowid
