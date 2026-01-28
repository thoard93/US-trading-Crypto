import sqlite3
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(__file__), 'trading_platform.db')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Show all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print(f"Tables: {tables}")

# Check each table row count
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"  {table}: {count} rows")

conn.close()
