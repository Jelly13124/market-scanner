"""Probe EODHD endpoints to verify response shapes before writing the adapter.

Run once: ``python scripts/probe_eodhd.py``. Prints the first 1-2 rows of each
endpoint so we can map fields confidently.
"""

from __future__ import annotations

import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["EODHD_API_KEY"]
BASE = "https://eodhd.com/api"

TICKER = "AAPL.US"


def hit(path: str, params: dict) -> None:
    params = {**params, "api_token": KEY, "fmt": "json"}
    url = f"{BASE}{path}"
    print(f"\n=== GET {path}  params={ {k: v for k, v in params.items() if k != 'api_token'} } ===")
    try:
        r = requests.get(url, params=params, timeout=30)
    except Exception as e:
        print(f"  ERROR: {e}")
        return
    print(f"  status: {r.status_code}")
    if r.status_code != 200:
        print(f"  body[:300]: {r.text[:300]}")
        return
    try:
        data = r.json()
    except Exception:
        print(f"  body[:300] (not JSON): {r.text[:300]}")
        return
    # Print shape preview
    if isinstance(data, list):
        print(f"  type: list  len={len(data)}")
        if data:
            print(f"  first item:\n{json.dumps(data[0], indent=2, default=str)[:800]}")
    elif isinstance(data, dict):
        print(f"  type: dict  keys={list(data.keys())[:20]}")
        # If response has a 'data' / 'Earnings' / etc key, peek inside
        for k in ("data", "Earnings", "earnings"):
            if k in data and isinstance(data[k], list) and data[k]:
                print(f"  data[{k!r}] first:\n{json.dumps(data[k][0], indent=2, default=str)[:600]}")
                break
        else:
            print(f"  body[:600]:\n{json.dumps(data, indent=2, default=str)[:600]}")
    else:
        print(f"  type: {type(data).__name__}")
        print(f"  body[:300]: {str(data)[:300]}")


def main() -> int:
    # 1) EOD prices
    hit(f"/eod/{TICKER}", {"from": "2026-04-13", "to": "2026-05-13", "order": "a"})

    # 2) Insider transactions
    hit("/insider-transactions", {"code": TICKER, "from": "2025-11-13", "to": "2026-05-13", "limit": 5})

    # 3) News
    hit("/news", {"s": TICKER, "from": "2026-04-13", "to": "2026-05-13", "limit": 3})

    # 4) Sentiments
    hit("/sentiments", {"s": TICKER, "from": "2026-04-13", "to": "2026-05-13"})

    # 5) Earnings calendar (last 90 days)
    hit("/calendar/earnings", {"symbols": TICKER, "from": "2025-11-13", "to": "2026-05-13"})

    # 6) Fundamentals (just key counts; very large response)
    hit(f"/fundamentals/{TICKER}", {})

    # 7) Latest quote / general (for market cap)
    hit(f"/real-time/{TICKER}", {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
