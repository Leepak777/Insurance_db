import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "insurance.db")

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("PRAGMA foreign_keys = ON")

# ---------------- DEBIT NOTES ----------------
cur.execute("""
CREATE TABLE IF NOT EXISTS debit_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_date TEXT,
    insured_or_agent TEXT,
    insurance_class TEXT,
    policy_number TEXT,
    endorsement_number TEXT,
    account_number TEXT,
    created_at TEXT,
    uploaded_by TEXT,
    file_name TEXT,
    file_data BLOB
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS debit_note_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    debit_note_id INTEGER,
    category TEXT,
    gross_premium REAL,
    commission REAL,
    overriding_insurer REAL,
    cost REAL,
    profit REAL,
    FOREIGN KEY (debit_note_id)
        REFERENCES debit_notes(id)
        ON DELETE CASCADE
)
""")

# ---------------- ACCOUNT STATEMENTS ----------------
cur.execute("""
CREATE TABLE IF NOT EXISTS account_statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_date TEXT,
    address TEXT,
    account_number TEXT,
    total_premium_due REAL,
    premium_due_date TEXT,
    created_at TEXT,
    uploaded_by TEXT,
    file_name TEXT,
    file_data BLOB
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS account_statement_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_statement_id INTEGER,
    effective_date TEXT,
    debit_note TEXT,
    policy_number TEXT,
    premium REAL,
    FOREIGN KEY (account_statement_id)
        REFERENCES account_statements(id)
        ON DELETE CASCADE
)
""")

# ---------------- RENEWAL NOTICES ----------------
cur.execute("""
CREATE TABLE IF NOT EXISTS renewal_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_date TEXT,
    insured TEXT,
    insurance_class TEXT,
    policy_number TEXT,
    expiry_date TEXT,
    ac_code TEXT,
    total_earning REAL,
    renewal_premium REAL,
    created_at TEXT,
    uploaded_by TEXT,
    file_name TEXT,
    file_data BLOB
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS renewal_notice_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    renewal_notice_id INTEGER,
    label TEXT,
    amount REAL,
    FOREIGN KEY (renewal_notice_id)
        REFERENCES renewal_notices(id)
        ON DELETE CASCADE
)
""")

conn.commit()
conn.close()

print("✅ Database initialized at:", DB_FILE)
