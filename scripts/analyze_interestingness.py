"""One-off: measure 'interestingness' of triggered stocks.

Reframe: triggers are an ATTENTION FILTER for downstream agents, not
alpha signals. The right question is "do triggered stocks MOVE more
than baseline?" — mean absolute return / mean absolute alpha.

Compares each detector's triggered subset against:
  - Overall mean (all 1705 entries, which are all top-20-by-composite)
  - SPY |bench_ret| as the market baseline
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

CSV_PATH = Path("backtest_ndx100_90d.csv")


def _f(s: str) -> float | None:
    if s in (None, "", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> None:
    rows = []
    with CSV_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            r["_ret_5d"] = _f(r.get("ret_5d"))
            r["_ret_20d"] = _f(r.get("ret_20d"))
            r["_ret_63d"] = _f(r.get("ret_63d"))
            r["_alpha_5d"] = _f(r.get("alpha_5d"))
            r["_alpha_20d"] = _f(r.get("alpha_20d"))
            r["_alpha_63d"] = _f(r.get("alpha_63d"))
            r["_bench_ret_5d"] = _f(r.get("bench_ret_5d"))
            r["_bench_ret_20d"] = _f(r.get("bench_ret_20d"))
            r["_bench_ret_63d"] = _f(r.get("bench_ret_63d"))
            r["_detectors"] = [
                d for d in (r.get("triggered_detectors") or "").split("|") if d
            ]
            rows.append(r)

    print(f"Loaded {len(rows)} rows from {CSV_PATH}")
    print()

    def mean_abs(vals):
        clean = [abs(v) for v in vals if v is not None]
        return (sum(clean) / len(clean), len(clean)) if clean else (None, 0)

    # === Overall baselines (top-20 universe + SPY) ===
    print("=" * 78)
    print("BASELINES")
    print("=" * 78)
    print(f"{'series':<35s} {'n':>6s} {'mean|x|':>10s}")
    for label, key in [
        ("all rows |ret_5d|     (top-20)",   "_ret_5d"),
        ("all rows |ret_20d|    (top-20)",   "_ret_20d"),
        ("all rows |ret_63d|    (top-20)",   "_ret_63d"),
        ("all rows |alpha_5d|   (top-20 vs SPY)",  "_alpha_5d"),
        ("all rows |alpha_20d|  (top-20 vs SPY)",  "_alpha_20d"),
        ("all rows |alpha_63d|  (top-20 vs SPY)",  "_alpha_63d"),
        ("SPY    |bench_ret_5d|",   "_bench_ret_5d"),
        ("SPY    |bench_ret_20d|",  "_bench_ret_20d"),
        ("SPY    |bench_ret_63d|",  "_bench_ret_63d"),
    ]:
        m, n = mean_abs([r[key] for r in rows])
        print(f"{label:<35s} {n:>6d}  {m*100:>8.2f}%" if m is not None else f"{label:<35s} {n:>6d}  {'—':>9s}")

    # === Per-detector |alpha| for 5d / 20d / 63d ===
    print()
    print("=" * 78)
    print("PER-DETECTOR INTERESTINGNESS — mean |alpha| at 5d/20d/63d")
    print("=" * 78)
    print(f"(Compares to overall top-20 baseline. >1.0× means 'detector picks bigger movers'.)")
    print()

    by_det: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for d in r["_detectors"]:
            by_det[d].append(r)

    baseline_5d = mean_abs([r["_alpha_5d"] for r in rows])[0]
    baseline_20d = mean_abs([r["_alpha_20d"] for r in rows])[0]
    baseline_63d = mean_abs([r["_alpha_63d"] for r in rows])[0]

    print(f"{'detector':<26s} {'n':>5s}  "
          f"{'|alpha_5d|':>10s} {'vs base':>8s}  "
          f"{'|alpha_20d|':>11s} {'vs base':>8s}  "
          f"{'|alpha_63d|':>11s} {'vs base':>8s}")
    print("-" * 100)
    for det in sorted(by_det.keys()):
        subset = by_det[det]
        m5, n5 = mean_abs([r["_alpha_5d"] for r in subset])
        m20, n20 = mean_abs([r["_alpha_20d"] for r in subset])
        m63, n63 = mean_abs([r["_alpha_63d"] for r in subset])
        r5 = f"{m5/baseline_5d:.2f}×" if (m5 and baseline_5d) else "—"
        r20 = f"{m20/baseline_20d:.2f}×" if (m20 and baseline_20d) else "—"
        r63 = f"{m63/baseline_63d:.2f}×" if (m63 and baseline_63d) else "—"
        m5s = f"{m5*100:.2f}%" if m5 else "—"
        m20s = f"{m20*100:.2f}%" if m20 else "—"
        m63s = f"{m63*100:.2f}%" if m63 else "—"
        print(f"{det:<26s} {len(subset):>5d}  "
              f"{m5s:>10s} {r5:>8s}  "
              f"{m20s:>11s} {r20:>8s}  "
              f"{m63s:>11s} {r63:>8s}")

    # === Multi-detector confluence ===
    print()
    print("=" * 78)
    print("CONFLUENCE — does multi-detector overlap surface bigger movers?")
    print("=" * 78)
    by_n_det: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_n_det[len(r["_detectors"])].append(r)
    print(f"{'n_detectors':>12s} {'n_rows':>8s}  "
          f"{'|alpha_5d|':>11s}  {'|alpha_20d|':>12s}  {'|alpha_63d|':>12s}")
    for n_det in sorted(by_n_det.keys()):
        subset = by_n_det[n_det]
        m5, _ = mean_abs([r["_alpha_5d"] for r in subset])
        m20, _ = mean_abs([r["_alpha_20d"] for r in subset])
        m63, _ = mean_abs([r["_alpha_63d"] for r in subset])
        print(f"{n_det:>12d} {len(subset):>8d}  "
              f"{(m5*100 if m5 else 0):>10.2f}%  "
              f"{(m20*100 if m20 else 0):>11.2f}%  "
              f"{(m63*100 if m63 else 0):>11.2f}%")

    # === Direction concordance (a quick sanity check) ===
    print()
    print("=" * 78)
    print("DIRECTION SANITY — fraction of triggered entries where forward")
    print("ret_5d sign matches direction (would be ~50% if random)")
    print("=" * 78)
    print(f"{'detector':<26s} {'n':>5s}  {'hit %':>8s}")
    print("-" * 50)
    for det in sorted(by_det.keys()):
        subset = [r for r in by_det[det]
                  if r["_ret_5d"] is not None and r["direction"] in ("bullish", "bearish")]
        if not subset:
            continue
        hits = sum(
            1 for r in subset
            if (r["direction"] == "bullish" and r["_ret_5d"] > 0)
            or (r["direction"] == "bearish" and r["_ret_5d"] < 0)
        )
        rate = hits / len(subset)
        print(f"{det:<26s} {len(subset):>5d}  {rate*100:>7.1f}%")


if __name__ == "__main__":
    main()
