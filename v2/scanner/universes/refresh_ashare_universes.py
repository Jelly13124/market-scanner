"""One-off snapshot script: fetch SSE 50 / CSI 300 / CSI 500 / CSI 1000
constituents from Eastmoney and write CSVs alongside the US universes.

Run manually when you want to refresh; not invoked by the running app.

Usage:
    C:/Users/Jerry/anaconda3/python.exe v2/scanner/universes/refresh_ashare_universes.py

Writes 5 CSVs to v2/scanner/universes/data/:
    sse50.csv         ~50 rows
    csi300.csv        ~300 rows
    csi500.csv        ~500 rows
    csi1000.csv       ~1000 rows
    hs300_ext.csv     ~800 rows (csi300 + csi500 union, dedup)
"""

from __future__ import annotations

import csv
from pathlib import Path

import requests

_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"

_INDEX_CODES = {
    "sse50": "000016",
    "csi300": "000300",
    "csi500": "000905",
    "csi1000": "000852",
}

_HERE = Path(__file__).parent / "data"


def fetch(index_code: str) -> list[tuple[str, str, str]]:
    """Return [(ticker_canonical, name, sector)] for an index's constituents."""
    out: list[tuple[str, str, str]] = []
    page = 1
    while True:
        params = {
            "reportName": "RPT_INDEX_TS_COMPONENT",
            "columns": "ALL",
            "filter": f'(TYPE="2")(BASE_CODE="{index_code}")',
            "pageNumber": page,
            "pageSize": 500,
            "sortColumns": "WEIGHT",
            "sortTypes": "-1",
        }
        r = requests.get(_BASE, params=params, timeout=15)
        r.raise_for_status()
        data = (r.json().get("result") or {}).get("data") or []
        if not data:
            break
        for row in data:
            code = (row.get("SECURITY_CODE") or "").strip()
            exch_raw = (row.get("MARKET") or "").strip().upper()
            exch = "SH" if exch_raw in ("SH", "SHA", "1") else "SZ"
            name = row.get("SECURITY_NAME_ABBR") or ""
            sector = row.get("INDUSTRY") or ""
            if code:
                out.append((f"{code}.{exch}", name, sector))
        if len(data) < 500:
            break
        page += 1
    return out


def write_csv(name: str, rows: list[tuple[str, str, str]]) -> None:
    _HERE.mkdir(parents=True, exist_ok=True)
    p = _HERE / f"{name}.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "name", "sector"])
        w.writerows(rows)
    print(f"wrote {p} ({len(rows)} rows)")


def write_empty_csv(name: str) -> None:
    """Stub CSV with header only - used when live fetch fails."""
    _HERE.mkdir(parents=True, exist_ok=True)
    p = _HERE / f"{name}.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "name", "sector"])
    print(f"wrote {p} (0 rows - stub)")


def main():
    snapshots = {}
    for name, code in _INDEX_CODES.items():
        snapshots[name] = fetch(code)
        write_csv(name, snapshots[name])
    # Composite hs300_ext = csi300 + csi500 (union, dedup by ticker)
    seen = set()
    ext = []
    for row in snapshots["csi300"] + snapshots["csi500"]:
        if row[0] not in seen:
            ext.append(row)
            seen.add(row[0])
    write_csv("hs300_ext", ext)


if __name__ == "__main__":
    main()
