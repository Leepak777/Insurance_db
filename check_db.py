import sqlite3
import os

DB_FILE = os.path.join(os.path.dirname(__file__), "insurance.db")

print("DB path:", os.path.abspath(DB_FILE))

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table'
    ORDER BY name
""")

tables = cur.fetchall()

if not tables:
    print("❌ No tables found")
else:
    print("✅ Tables:")
    for t in tables:
        print(" -", t[0])

conn.close()
