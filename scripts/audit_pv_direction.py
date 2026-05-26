"""Audit the price_volume_anomaly detector's direction sign.

For each (ticker, scan_date) where PV fired in the last ~60 trading days,
look at PV's own direction (from ``today_return`` sign in
``triggered_components_json["price_volume_anomaly"]``), then compute the
dir-adjusted forward 5-day alpha. If forward returns systematically move
OPPOSITE to PV's direction (reversal_rate well above 50%, with a sample
big enough to be statistically meaningful), the detector's direction
sign is probably wrong.

Decision rule (per user spec):
  Flip the sign ONLY if BOTH:
    * sample n ≥ 100  (avoid flipping on noise)
    * reversal_rate ≥ 60%
  AND the binomial test p-value (H0: reversal=50%) is < 0.05.

Output:
  outputs/pv_direction_audit.txt  — diagnostic; safe to commit to .gitignore.

Caller decides whether to actually flip — this script PRINTS the
recommendation but does NOT mutate volume_anomaly.py. Flip in a separate
step after eyeballing the diagnostic.

Usage:
    python scripts/audit_pv_direction.py [--csv PATH] [--days N]
Defaults to ``backtest_ndx100_90d.csv`` at repo root, last 60 trading
days. The CSV must contain ``triggered_components_json`` (already
present in v2/backtesting/engine.py output).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from scipy import stats as _scipy_stats


def _parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=Path("backtest_ndx100_90d.csv"))
    ap.add_argument("--days", type=int, default=60,
                    help="Trailing trading-day window to filter rows to.")
    ap.add_argument("--out", type=Path,
                    default=Path("outputs/pv_direction_audit.txt"))
    ap.add_argument("--reversal-threshold", type=float, default=0.60,
                    help="Reversal rate above which to recommend flip.")
    ap.add_argument("--min-n", type=int, default=100,
                    help="Minimum sample size required for flip recommendation.")
    return ap.parse_args()


def _row_pv_direction(comp_json_str: str) -> str | None:
    """Return 'bullish'/'bearish'/'neutral' for this row's PV trigger, or
    None if PV didn't fire / components malformed. Mirrors the detector's
    own direction rule: today_return sign with a ±1e-4 deadband."""
    if not comp_json_str:
        return None
    try:
        comp = json.loads(comp_json_str)
    except json.JSONDecodeError:
        return None
    pv = comp.get("price_volume_anomaly")
    if not isinstance(pv, dict):
        return None
    ret = pv.get("today_return")
    if not isinstance(ret, (int, float)):
        return None
    if ret > 1e-4:
        return "bullish"
    if ret < -1e-4:
        return "bearish"
    return "neutral"


def _to_float(v: str | None) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def main() -> int:
    args = _parse_args()
    if not args.csv.exists():
        print(f"ERROR: CSV not found at {args.csv}", file=sys.stderr)
        return 1

    with args.csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Filter to last N trading days based on max scan_date in the file.
    all_dates = sorted({r["scan_date"] for r in rows})
    if not all_dates:
        print("ERROR: CSV has no rows", file=sys.stderr)
        return 1
    cutoff_idx = max(0, len(all_dates) - args.days)
    cutoff_date = all_dates[cutoff_idx]
    in_window = [r for r in rows if r["scan_date"] >= cutoff_date]

    # Filter to rows where PV fired.
    pv_rows: list[dict] = []
    for r in in_window:
        tr = (r.get("triggered_detectors") or "").split(",")
        if "price_volume_anomaly" in tr:
            pv_rows.append(r)

    # Compute reversal counts per direction.
    # "Reversal" = forward 5-day alpha sign opposite to PV's stated direction.
    # Bullish PV with alpha_5d < 0 → reversal.
    # Bearish PV with alpha_5d > 0 → reversal.
    # Neutral PV → no directional claim → excluded from rate.
    by_direction: Counter[str] = Counter()
    reversals = 0
    forward_count = 0
    skipped_no_return = 0
    skipped_neutral = 0
    samples: list[tuple[str, str, str, float]] = []  # (date, ticker, pv_dir, alpha_5d)

    for r in pv_rows:
        pv_dir = _row_pv_direction(r.get("triggered_components_json") or "")
        if pv_dir is None:
            skipped_no_return += 1
            continue
        by_direction[pv_dir] += 1
        if pv_dir == "neutral":
            skipped_neutral += 1
            continue
        alpha_5d = _to_float(r.get("alpha_5d"))
        if alpha_5d is None:
            skipped_no_return += 1
            continue
        forward_count += 1
        is_reversed = (
            (pv_dir == "bullish" and alpha_5d < 0)
            or (pv_dir == "bearish" and alpha_5d > 0)
        )
        if is_reversed:
            reversals += 1
        samples.append((r["scan_date"], r["ticker"], pv_dir, alpha_5d))

    reversal_rate = reversals / forward_count if forward_count else 0.0
    # One-sided binomial test against H0: reversal_rate = 0.50, alternative:
    # reversal > 0.50 (i.e. detector's sign is wrong).
    if forward_count >= 1:
        binom_result = _scipy_stats.binomtest(
            k=reversals, n=forward_count, p=0.5, alternative="greater",
        )
        binom_p = float(binom_result.pvalue)
    else:
        binom_p = float("nan")

    flip_recommended = (
        forward_count >= args.min_n
        and reversal_rate >= args.reversal_threshold
        and binom_p < 0.05
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        def w(line: str = "") -> None:
            f.write(line + "\n")

        w("=" * 70)
        w("price_volume_anomaly direction audit")
        w("=" * 70)
        w()
        w(f"Source CSV:          {args.csv}")
        w(f"Window:              last {args.days} trading days "
          f"({cutoff_date} → {all_dates[-1]})")
        w(f"Total in-window rows:    {len(in_window)}")
        w(f"PV-triggered rows:       {len(pv_rows)}")
        w()
        w("By PV direction:")
        for d in ("bullish", "bearish", "neutral"):
            w(f"  {d:<8s}  {by_direction[d]}")
        w()
        w(f"Rows excluded (no PV components / no 5d forward):  {skipped_no_return}")
        w(f"Rows excluded (PV direction = neutral):            {skipped_neutral}")
        w(f"Directional rows with valid forward 5d return:     {forward_count}")
        w(f"Reversals (forward sign opposite to PV direction): {reversals}")
        w(f"Reversal rate:                                     {reversal_rate * 100:.1f}%")
        w(f"Binomial p-value (H0: rate=50%, alt: >50%):        {binom_p:.4f}")
        w()
        w(f"Flip thresholds:  n >= {args.min_n}  "
          f"AND  reversal >= {args.reversal_threshold * 100:.0f}%  "
          f"AND  binomial p < 0.05")
        w(f"  n ok?            {'YES' if forward_count >= args.min_n else 'NO'}  ({forward_count})")
        w(f"  reversal ok?     {'YES' if reversal_rate >= args.reversal_threshold else 'NO'}  ({reversal_rate * 100:.1f}%)")
        w(f"  significance ok? {'YES' if binom_p < 0.05 else 'NO'}  (p={binom_p:.4f})")
        w()
        if flip_recommended:
            w("RECOMMENDATION: FLIP the direction sign in volume_anomaly.py.")
            w("  Edit v2/scanner/detectors/volume_anomaly.py around line 122:")
            w("    today_ret > 1e-4 → 'bearish' (not 'bullish')")
            w("    today_ret < -1e-4 → 'bullish' (not 'bearish')")
        else:
            w("RECOMMENDATION: DO NOT flip — at least one gate failed.")
            if forward_count < args.min_n:
                w(f"  (Sample too small at n={forward_count}; need ≥ {args.min_n}.)")
            elif reversal_rate < args.reversal_threshold:
                w(f"  (Reversal rate {reversal_rate * 100:.1f}% under "
                  f"{args.reversal_threshold * 100:.0f}% threshold.)")
            elif binom_p >= 0.05:
                w(f"  (Binomial p={binom_p:.4f} not significant — could be noise.)")
        w()
        w("First 10 samples (scan_date, ticker, pv_direction, alpha_5d):")
        for s in samples[:10]:
            w(f"  {s[0]}  {s[1]:<6s}  {s[2]:<8s}  {s[3]*100:+.2f}%")

    print(f"Wrote {args.out}")
    print(f"flip_recommended = {flip_recommended}")
    print(f"  n={forward_count}, reversal_rate={reversal_rate * 100:.1f}%, "
          f"binom_p={binom_p:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
