"""One-off: recompute §6 (composite-rank quartile) at 1d/5d/20d/63d.

Reuses load_rows / bootstrap_ci from v2.backtesting.analyze. Prints
side-by-side no-quant vs with-quant so we can see whether the rank
inversion (negative Top-Bottom spread) persists at 20d — where the
"directional regime amplifier" alpha actually shows up.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make repo root importable when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v2.backtesting.analyze import (
    bootstrap_ci,
    load_rows,
    _direction_adjust,
    _fmt_pct,
)


WINDOWS = (1, 5, 20, 63)
BUCKETS = (
    ("Rank 1-5",   range(1, 6)),
    ("Rank 6-10",  range(6, 11)),
    ("Rank 11-15", range(11, 16)),
    ("Rank 16-20", range(16, 21)),
)


def _bucket_alphas(rows, window: int) -> dict[str, list[float]]:
    out = {label: [] for label, _ in BUCKETS}
    for r in rows:
        a = _direction_adjust(r.alpha[window], r.direction)
        if a is None:
            continue
        for label, rng in BUCKETS:
            if r.rank in rng:
                out[label].append(a)
                break
    return out


def _print_one(label: str, rows) -> None:
    print()
    print("=" * 78)
    print(f"  {label}  (n_total={len(rows)})")
    print("=" * 78)
    print(f"  {'window':<6}  {'Rank 1-5':>18}  {'Rank 6-10':>18}  "
          f"{'Rank 11-15':>18}  {'Rank 16-20':>18}  {'Top-Bot':>10}")

    for w in WINDOWS:
        buckets = _bucket_alphas(rows, w)
        cells: list[str] = []
        means: dict[str, float | None] = {}
        for bkt_label, _ in BUCKETS:
            vals = buckets[bkt_label]
            mean, lo, hi = bootstrap_ci(vals, n_resamples=5000)
            means[bkt_label] = mean
            if mean is None:
                cells.append("—")
            elif lo is None or hi is None:
                cells.append(f"{_fmt_pct(mean)} n={len(vals)}")
            else:
                cells.append(f"{_fmt_pct(mean)} n={len(vals)}")
        top, bot = means["Rank 1-5"], means["Rank 16-20"]
        spread = (top - bot) if (top is not None and bot is not None) else None
        spread_s = _fmt_pct(spread) if spread is not None else "—"
        print(f"  {w:>3}d    " + "  ".join(f"{c:>18}" for c in cells)
              + f"  {spread_s:>10}")

    # CI on the spread itself for each window — use independent bootstrap
    # of (top - bot) by resampling within each bucket.
    print()
    print("  Spread 95% CI (paired bootstrap, 5000 resamples):")
    import numpy as np
    rng = np.random.default_rng(42)
    for w in WINDOWS:
        buckets = _bucket_alphas(rows, w)
        top_vals = np.array(buckets["Rank 1-5"], dtype=float)
        bot_vals = np.array(buckets["Rank 16-20"], dtype=float)
        if len(top_vals) < 2 or len(bot_vals) < 2:
            print(f"    {w:>3}d   — (insufficient n)")
            continue
        top_idx = rng.integers(0, len(top_vals), size=(5000, len(top_vals)))
        bot_idx = rng.integers(0, len(bot_vals), size=(5000, len(bot_vals)))
        sample_spreads = top_vals[top_idx].mean(axis=1) - bot_vals[bot_idx].mean(axis=1)
        mean = float(sample_spreads.mean())
        lo = float(np.percentile(sample_spreads, 2.5))
        hi = float(np.percentile(sample_spreads, 97.5))
        crosses_zero = lo <= 0 <= hi
        flag = "" if not crosses_zero else "  (CI includes 0)"
        print(f"    {w:>3}d   {_fmt_pct(mean)}  [{_fmt_pct(lo)}, {_fmt_pct(hi)}]"
              f"  n_top={len(top_vals)} n_bot={len(bot_vals)}{flag}")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    pairs = [
        ("no quant", repo / "backtest_ndx100_30d_no_quant.csv"),
        ("with quant", repo / "backtest_ndx100_30d_with_quant.csv"),
    ]
    for label, path in pairs:
        if not path.exists():
            print(f"MISSING: {path}", file=sys.stderr)
            return 2
        rows = load_rows(path)
        _print_one(label, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
