"""One-off: re-apply transaction cost to existing AB backtest CSVs.

The existing CSVs in outputs/ were computed with cost=0 (gross PnL). This
script reads them, deducts ``--cost-bp`` from each non-HOLD row's pnl_5d
and pnl_20d, writes back to a sibling ``_costed.csv``. Then runs the
existing summary script on the costed CSV so we can see edge erosion
without re-running the 4-hour backtest.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def _to_float(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def recompute(in_csv: Path, out_csv: Path, cost_bp: float) -> int:
    with in_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"Empty: {in_csv}", file=sys.stderr)
        return 0

    fieldnames = list(rows[0].keys())
    cost_rate = cost_bp / 10_000.0
    adjusted = 0
    for r in rows:
        action = (r.get("action") or "").lower()
        if action not in ("buy", "short", "sell", "cover"):
            continue
        qty = _to_float(r.get("quantity"))
        entry = _to_float(r.get("entry_price"))
        if qty is None or entry is None:
            continue
        cost = cost_rate * qty * entry
        for w in (1, 5, 20, 63):
            key = f"pnl_{w}d"
            if key not in r:
                continue
            gross = _to_float(r.get(key))
            if gross is None:
                continue
            r[key] = round(gross - cost, 4)
        adjusted += 1

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return adjusted


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv_paths", type=Path, nargs="+",
                   help="Input CSVs to re-cost.")
    p.add_argument("--cost-bp", type=float, default=10.0,
                   help="Round-trip cost in bp (default 10 = 0.10%%).")
    p.add_argument("--suffix", default="_costed",
                   help="Filename suffix for output (default: _costed).")
    args = p.parse_args()

    for path in args.csv_paths:
        if not path.exists():
            print(f"MISSING: {path}", file=sys.stderr)
            continue
        out = path.with_name(path.stem + args.suffix + path.suffix)
        n = recompute(path, out, args.cost_bp)
        print(f"  {path.name} -> {out.name}: {n} non-HOLD rows adjusted ({args.cost_bp:g} bp)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
