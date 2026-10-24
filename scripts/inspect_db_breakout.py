"""Quick one-off: find any persisted ScannerConfig rows referencing breakout_52w."""
import json
import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Jerry\Desktop\ai-hedge-fund\app\backend\hedge_fund.db"

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# List tables
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print(f"tables ({len(tables)}):", tables)

if "scanner_configs" in tables:
    cols = [r[1] for r in cur.execute("PRAGMA table_info(scanner_configs)").fetchall()]
    print("scanner_configs cols:", cols)
    rows = cur.execute("SELECT * FROM scanner_configs").fetchall()
    print(f"rows: {len(rows)}")
    for r in rows:
        row_dict = dict(zip(cols, r))
        # Find any value containing the string breakout_52w
        flat = json.dumps(row_dict, default=str)
        marker = "breakout_52w" in flat
        print(f"  id={row_dict.get('id')} name={row_dict.get('name')!r} has_breakout={marker}")
        if marker:
            for c in cols:
                v = row_dict[c]
                if isinstance(v, str) and "breakout" in v:
                    print(f"    {c} = {v[:200]}")

conn.close()
