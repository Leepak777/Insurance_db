import sqlite3
import os

SCHEMA_SQL = """
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
);

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
);

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
);

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
);

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
);

CREATE TABLE IF NOT EXISTS renewal_notice_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    renewal_notice_id INTEGER,
    label TEXT,
    amount REAL,
    FOREIGN KEY (renewal_notice_id)
        REFERENCES renewal_notices(id)
        ON DELETE CASCADE
);
"""
import os
import sys
import sqlite3

# ---------------- PERSISTENT DB PATH ----------------
if getattr(sys, 'frozen', False):
    # Running as exe
    base_path = os.path.dirname(sys.executable)
else:
    # Running as normal script
    base_path = os.path.dirname(__file__)

DB_FILE = os.path.join(base_path, "insurance.db")


# ---------------- CONNECTION ----------------
def get_conn():
    first_time = not os.path.exists(DB_FILE)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    if first_time:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    return conn

# ---------------- DEBIT NOTES ----------------
def insert_debit_note(data, financials=None):
    if financials is None:
        financials = []

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO debit_notes (
            issue_date, insured_or_agent, insurance_class,
            policy_number, endorsement_number, account_number,
            created_at, uploaded_by, file_name, file_data
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
    """, (
        data['issue_date'],
        data.get('insured_or_agent'),
        data.get('insurance_class'),
        data.get('policy_number'),
        data.get('endorsement_number'),
        data.get('account_number'),
        data.get('uploaded_by', 'admin'),
        data.get('file_name'),
        data.get('file_data')
    ))

    note_id = cur.lastrowid

    for f in financials:
        cur.execute("""
            INSERT INTO debit_note_financials (
                debit_note_id, category, gross_premium,
                commission, overriding_insurer, cost, profit
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            note_id,
            f['category'],
            f['gross_premium'],
            f['commission'],
            f['overriding_insurer'],
            f['cost'],
            f['profit']
        ))

    conn.commit()
    conn.close()
    return note_id


def fetch_debit_notes(filters=None):
    """Fetch debit notes for listing (no file_data)"""
    if filters is None:
        filters = []

    conn = get_conn()
    cur = conn.cursor()

    query = """
        SELECT id, issue_date, insured_or_agent, insurance_class,
               policy_number, endorsement_number, account_number, uploaded_by,
               file_name
        FROM debit_notes
        WHERE 1=1
    """
    params = []
    fields = {'id','issue_date','insured_or_agent','insurance_class',
              'policy_number','endorsement_number','account_number','uploaded_by'}

    for f in filters:
        if f['field'] in fields:
            if f['op'].upper() == 'LIKE':
                query += f" AND {f['field']} LIKE ?"
                params.append(f"%{f['value']}%")
            else:
                query += f" AND {f['field']} {f['op']} ?"
                params.append(f['value'])

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_debit_note_by_id(note_id):
    """Fetch a single debit note (includes file_data + financials)"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM debit_notes WHERE id = ?", (note_id,))
    note = cur.fetchone()
    if not note:
        conn.close()
        return None

    cur.execute("""
        SELECT id, category, gross_premium, commission,
               overriding_insurer, cost, profit
        FROM debit_note_financials
        WHERE debit_note_id = ?
        ORDER BY id
    """, (note_id,))
    financials = [dict(r) for r in cur.fetchall()]

    conn.close()

    result = dict(note)
    result["financials"] = financials
    return result


def fetch_debit_note_financials(note_id, filters=None):
    if filters is None:
        filters = []

    conn = get_conn()
    cur = conn.cursor()

    query = """
        SELECT id, category, gross_premium, commission,
               overriding_insurer, cost, profit
        FROM debit_note_financials
        WHERE debit_note_id = ?
    """
    params = [note_id]
    fields = {'category','gross_premium','commission','overriding_insurer','cost','profit'}

    for f in filters:
        if f['field'] in fields:
            if f['op'].upper() == 'LIKE':
                query += f" AND {f['field']} LIKE ?"
                params.append(f"%{f['value']}%")
            else:
                query += f" AND {f['field']} {f['op']} ?"
                params.append(f['value'])

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------- ACCOUNT STATEMENTS ----------------
def insert_account_statement(data, entries=None):
    if entries is None:
        entries = []

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO account_statements (
            issue_date, address, account_number,
            total_premium_due, premium_due_date,
            created_at, uploaded_by, file_name, file_data
        ) VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
    """, (
        data['issue_date'],
        data.get('address'),
        data.get('account_number'),
        data.get('total_premium_due'),
        data.get('premium_due_date'),
        data.get('uploaded_by', 'admin'),
        data.get('file_name'),
        data.get('file_data')
    ))

    stmt_id = cur.lastrowid

    for e in entries:
        cur.execute("""
            INSERT INTO account_statement_entries (
                account_statement_id, effective_date,
                debit_note, policy_number, premium
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            stmt_id,
            e['effective_date'],
            e['debit_note'],
            e['policy_number'],
            e['premium']
        ))

    conn.commit()
    conn.close()
    return stmt_id


def fetch_account_statements(filters=None):
    """Fetch account statements for listing (no file_data)"""
    if filters is None:
        filters = []

    conn = get_conn()
    cur = conn.cursor()

    query = """
        SELECT id, issue_date, address, account_number,
               total_premium_due, premium_due_date, uploaded_by,
               file_name
        FROM account_statements
        WHERE 1=1
    """
    params = []
    fields = {'id','issue_date','address','account_number','total_premium_due','premium_due_date','uploaded_by'}

    for f in filters:
        if f['field'] in fields:
            if f['op'].upper() == 'LIKE':
                query += f" AND {f['field']} LIKE ?"
                params.append(f"%{f['value']}%")
            else:
                query += f" AND {f['field']} {f['op']} ?"
                params.append(f['value'])

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_account_statement_by_id(stmt_id):
    """Fetch a single account statement (includes file_data + entries)"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM account_statements WHERE id = ?", (stmt_id,))
    stmt = cur.fetchone()
    if not stmt:
        conn.close()
        return None

    cur.execute("""
        SELECT id, effective_date, debit_note, policy_number, premium
        FROM account_statement_entries
        WHERE account_statement_id = ?
        ORDER BY id
    """, (stmt_id,))
    entries = [dict(r) for r in cur.fetchall()]

    conn.close()

    result = dict(stmt)
    result["entries"] = entries
    return result



def fetch_account_statement_entries(stmt_id, filters=None):
    if filters is None:
        filters = []

    conn = get_conn()
    cur = conn.cursor()

    query = """
        SELECT id, effective_date, debit_note, policy_number, premium
        FROM account_statement_entries
        WHERE account_statement_id = ?
    """
    params = [stmt_id]
    fields = {'effective_date','debit_note','policy_number','premium'}

    for f in filters:
        if f['field'] in fields:
            if f['op'].upper() == 'LIKE':
                query += f" AND {f['field']} LIKE ?"
                params.append(f"%{f['value']}%")
            else:
                query += f" AND {f['field']} {f['op']} ?"
                params.append(f['value'])

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------- RENEWAL NOTICES ----------------
def insert_renewal_notice(data, entries=None):
    if entries is None:
        entries = []

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO renewal_notices (
            issue_date, insured, insurance_class,
            policy_number, expiry_date, ac_code,
            total_earning, renewal_premium,
            created_at, uploaded_by, file_name, file_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
    """, (
        data['issue_date'],
        data.get('insured'),
        data.get('insurance_class'),
        data.get('policy_number'),
        data.get('expiry_date'),
        data.get('ac_code'),
        data.get('total_earning', 0),
        data.get('renewal_premium', 0),
        data.get('uploaded_by', 'admin'),
        data.get('file_name'),
        data.get('file_data')
    ))

    notice_id = cur.lastrowid

    for e in entries:
        cur.execute("""
            INSERT INTO renewal_notice_entries (renewal_notice_id, label, amount)
            VALUES (?, ?, ?)
        """, (notice_id, e['label'], e['amount']))

    conn.commit()
    conn.close()
    return notice_id


def fetch_renewal_notices(filters=None):
    """Fetch renewal notices for listing (no file_data)"""
    if filters is None:
        filters = []

    conn = get_conn()
    cur = conn.cursor()

    query = """
        SELECT id, issue_date, insured, insurance_class,
               policy_number, expiry_date, ac_code,
               total_earning, renewal_premium, uploaded_by,
               file_name
        FROM renewal_notices
        WHERE 1=1
    """
    params = []
    fields = {'id','issue_date','insured','insurance_class','policy_number','expiry_date','ac_code','total_earning','renewal_premium','uploaded_by'}

    for f in filters:
        if f['field'] in fields:
            if f['op'].upper() == 'LIKE':
                query += f" AND {f['field']} LIKE ?"
                params.append(f"%{f['value']}%")
            else:
                query += f" AND {f['field']} {f['op']} ?"
                params.append(f['value'])

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_renewal_notice_by_id(notice_id):
    """Fetch a single renewal notice (includes file_data + entries)"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM renewal_notices WHERE id = ?", (notice_id,))
    notice = cur.fetchone()
    if not notice:
        conn.close()
        return None

    cur.execute("""
        SELECT id, label, amount
        FROM renewal_notice_entries
        WHERE renewal_notice_id = ?
        ORDER BY id
    """, (notice_id,))
    entries = [dict(r) for r in cur.fetchall()]

    conn.close()

    result = dict(notice)
    result["entries"] = entries
    return result


def fetch_renewal_notice_entries(notice_id, filters=None):
    if filters is None:
        filters = []

    conn = get_conn()
    cur = conn.cursor()

    query = """
        SELECT id, label, amount
        FROM renewal_notice_entries
        WHERE renewal_notice_id = ?
    """
    params = [notice_id]
    fields = {'label','amount'}

    for f in filters:
        if f['field'] in fields:
            if f['op'].upper() == 'LIKE':
                query += f" AND {f['field']} LIKE ?"
                params.append(f"%{f['value']}%")
            else:
                query += f" AND {f['field']} {f['op']} ?"
                params.append(f['value'])

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------- COMBINED FETCH ----------------
def fetch_all_documents(doc_type='all', filters=None, sort_by='id', sort_order='asc'):
    if filters is None:
        filters = []

    data = []

    if doc_type in ('debit_note', 'all'):
        notes = fetch_debit_notes(filters)
        for n in notes:
            n['doc_type'] = 'debit_note'
            n['children'] = fetch_debit_note_financials(n['id'], filters)
        data.extend(notes)

    if doc_type in ('account_statement', 'all'):
        stmts = fetch_account_statements(filters)
        for s in stmts:
            s['doc_type'] = 'account_statement'
            s['children'] = fetch_account_statement_entries(s['id'], filters)
        data.extend(stmts)

    if doc_type in ('renewal_notice', 'all'):
        notices = fetch_renewal_notices(filters)
        for r in notices:
            r['doc_type'] = 'renewal_notice'
            r['children'] = fetch_renewal_notice_entries(r['id'], filters)
        data.extend(notices)

    reverse = sort_order == 'desc'

    def sort_key(d):
        v = d.get(sort_by)
        return (v is None, v, d.get('id', 0))

    data.sort(key=sort_key, reverse=reverse)
    return data


def delete_debit_note(note_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM debit_note_financials WHERE debit_note_id = ?", (note_id,))
    cur.execute("DELETE FROM debit_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()

def delete_account_statement(stmt_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM account_statement_entries WHERE account_statement_id = ?", (stmt_id,))
    cur.execute("DELETE FROM account_statements WHERE id = ?", (stmt_id,))
    conn.commit()
    conn.close()

def delete_renewal_notice(notice_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM renewal_notice_entries WHERE renewal_notice_id = ?", (notice_id,))
    cur.execute("DELETE FROM renewal_notices WHERE id = ?", (notice_id,))
    conn.commit()
    conn.close()

def update_debit_note(data, financials=None):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE debit_notes SET
            issue_date=?, insured_or_agent=?, insurance_class=?,
            policy_number=?, endorsement_number=?, account_number=?,
            uploaded_by=?, file_name=?, file_data=?
        WHERE id=?
    """, (
        data['issue_date'], data.get('insured_or_agent'), data.get('insurance_class'),
        data.get('policy_number'), data.get('endorsement_number'), data.get('account_number'),
        data.get('uploaded_by'), data.get('file_name'), data.get('file_data'),
        data['id']
    ))

    if financials:
        cur.execute(
            "DELETE FROM debit_note_financials WHERE debit_note_id=?",
            (data['id'],)
        )

        for f in financials:
            cur.execute("""
                INSERT INTO debit_note_financials (
                    debit_note_id, category, gross_premium,
                    commission, overriding_insurer, cost, profit
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data['id'], f['category'], f['gross_premium'],
                f['commission'], f['overriding_insurer'],
                f['cost'], f['profit']
            ))

    conn.commit()
    conn.close()

def update_account_statement(data, entries=None):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE account_statements SET
            issue_date=?, address=?, account_number=?,
            total_premium_due=?, premium_due_date=?,
            uploaded_by=?, file_name=?, file_data=?
        WHERE id=?
    """, (
        data['issue_date'], data.get('address'), data.get('account_number'),
        data.get('total_premium_due'), data.get('premium_due_date'),
        data.get('uploaded_by'), data.get('file_name'), data.get('file_data'),
        data['id']
    ))

    # Remove old entries
    if entries:
        cur.execute("DELETE FROM account_statement_entries WHERE account_statement_id=?", (data['id'],))

        for e in entries:
            cur.execute("""
                INSERT INTO account_statement_entries (
                    account_statement_id, effective_date,
                    debit_note, policy_number, premium
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                data['id'], e['effective_date'], e['debit_note'], e['policy_number'], e['premium']
            ))

    conn.commit()
    conn.close()

def update_renewal_notice(data, entries=None):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE renewal_notices SET
            issue_date=?, insured=?, insurance_class=?,
            policy_number=?, expiry_date=?, ac_code=?,
            total_earning=?, renewal_premium=?,
            uploaded_by=?, file_name=?, file_data=?
        WHERE id=?
    """, (
        data['issue_date'], data.get('insured'), data.get('insurance_class'),
        data.get('policy_number'), data.get('expiry_date'), data.get('ac_code'),
        data.get('total_earning', 0), data.get('renewal_premium', 0),
        data.get('uploaded_by'), data.get('file_name'), data.get('file_data'),
        data['id']
    ))

    # Remove old entries
    if entries:
        cur.execute("DELETE FROM renewal_notice_entries WHERE renewal_notice_id=?", (data['id'],))

        for e in entries:
            cur.execute("""
                INSERT INTO renewal_notice_entries (renewal_notice_id, label, amount)
                VALUES (?, ?, ?)
            """, (data['id'], e['label'], e['amount']))

    conn.commit()
    conn.close()
