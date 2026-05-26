"""Aggregate the A/B backtest CSV into a human-readable comparison report.

Usage:
    python scripts/ab_backtest_summary.py outputs/ab_backtest_<...>.csv

Produces, next to the input CSV, a ``_summary.txt`` with:
  * Row counts per group + action
  * Mean PnL per group (5d, 20d) with bootstrap 95% CI
  * Two-sample Welch t-test A vs B (each window)
  * Hit rate (PnL > 0) per group, with binomial CI
  * Per-action breakdown (BUY only / SHORT only) per group
  * Per-day net PnL trace per group
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as _scipy

# Reuse the analyze.py bootstrap_ci so CI methodology is consistent
# across all reports in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from v2.backtesting.analyze import bootstrap_ci  # noqa: E402


def _read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_float(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_dollar(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:,.0f}"


def _bootstrap_dollar_ci(values: list[float], n_resamples: int = 5000) -> str:
    if not values:
        return "—"
    mean, lo, hi = bootstrap_ci(values, n_resamples=n_resamples)
    if mean is None:
        return "—"
    if lo is None or hi is None:
        return f"{_fmt_dollar(mean)}  (n={len(values)})"
    return f"{_fmt_dollar(mean):>10s}  [{_fmt_dollar(lo):>10s}, {_fmt_dollar(hi):>10s}]  n={len(values)}"


def _t_test(a: list[float], b: list[float]) -> str:
    """Welch two-sample t-test (a vs b), two-sided. Returns formatted line."""
    if len(a) < 2 or len(b) < 2:
        return "t-test: insufficient samples"
    res = _scipy.ttest_ind(a, b, equal_var=False)
    p = float(res.pvalue)
    diff = float(np.mean(a) - np.mean(b))
    sig = " *" if p < 0.05 else ""
    return f"t-test (A − B): diff={_fmt_dollar(diff)},  p={p:.4f}{sig}"


def _hit_rate(values: list[float]) -> str:
    if not values:
        return "—"
    wins = sum(1 for v in values if v > 0)
    n = len(values)
    rate = wins / n
    # Wilson 95% CI for a binomial proportion
    ci = _scipy.binomtest(wins, n).proportion_ci(method="wilson")
    return f"{rate * 100:5.1f}%  [{ci.low * 100:5.1f}%, {ci.high * 100:5.1f}%]  ({wins}/{n})"


def _pnl_lists(rows: list[dict], group: str, window_col: str) -> list[float]:
    """All non-None PnL values for one group/window. HOLD (PnL=0) is included —
    a HOLD that misses a winning move is a real (counterfactual) cost, so we
    keep it in the average rather than excluding."""
    out: list[float] = []
    for r in rows:
        if r.get("group") != group:
            continue
        v = _to_float(r.get(window_col))
        if v is not None:
            out.append(v)
    return out


def _per_action_pnl(rows: list[dict], group: str, window_col: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("group") != group:
            continue
        action = (r.get("action") or "").lower()
        v = _to_float(r.get(window_col))
        if v is not None:
            out[action].append(v)
    return out


def _daily_net_pnl(rows: list[dict], group: str, window_col: str) -> list[tuple[str, float, int]]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("group") != group:
            continue
        v = _to_float(r.get(window_col))
        if v is not None:
            by_day[r["scan_date"]].append(v)
    return [(d, float(sum(vs)), len(vs)) for d, vs in sorted(by_day.items())]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/ab_backtest_summary.py <csv_path>", file=sys.stderr)
        return 1
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        return 1
    rows = _read_rows(csv_path)
    if not rows:
        print(f"ERROR: {csv_path} is empty", file=sys.stderr)
        return 1

    out_path = csv_path.with_name(csv_path.stem + "_summary.txt")
    lines: list[str] = []
    w = lines.append

    # ---- §1 Counts ----
    n_a = sum(1 for r in rows if r["group"] == "A")
    n_b = sum(1 for r in rows if r["group"] == "B")
    days = sorted({r["scan_date"] for r in rows})

    w("=" * 78)
    w("A/B BACKTEST SUMMARY — scanner vs random ticker selection")
    w("=" * 78)
    w(f"Source CSV:    {csv_path}")
    w(f"Window:        {days[0]} → {days[-1]}  ({len(days)} trading days)")
    w(f"Group A rows:  {n_a}  (scanner-flagged tickers)")
    w(f"Group B rows:  {n_b}  (random tickers, empty scanner_context)")
    w("")

    # ---- §2 Action distribution ----
    w("-" * 78)
    w("ACTION DISTRIBUTION")
    w("-" * 78)
    for grp in ("A", "B"):
        actions = defaultdict(int)
        for r in rows:
            if r["group"] == grp:
                actions[(r.get("action") or "—").lower()] += 1
        w(f"  Group {grp}: " + ", ".join(f"{a}={c}" for a, c in sorted(actions.items())))
    w("")

    # ---- §3 PnL by window with CI + t-test ----
    for win in ("pnl_5d", "pnl_20d"):
        label = win.replace("pnl_", "").upper()
        w("-" * 78)
        w(f"{label} REALIZED PnL  (per-decision $ change; bootstrap 95% CI)")
        w("-" * 78)
        a_pnl = _pnl_lists(rows, "A", win)
        b_pnl = _pnl_lists(rows, "B", win)
        w(f"  Group A:  {_bootstrap_dollar_ci(a_pnl)}")
        w(f"  Group B:  {_bootstrap_dollar_ci(b_pnl)}")
        w(f"  {_t_test(a_pnl, b_pnl)}")
        w("")
        w(f"  Hit rate (PnL > 0):")
        w(f"    Group A:  {_hit_rate(a_pnl)}")
        w(f"    Group B:  {_hit_rate(b_pnl)}")
        w("")
        # Per-action breakdown
        a_act = _per_action_pnl(rows, "A", win)
        b_act = _per_action_pnl(rows, "B", win)
        all_actions = sorted(set(a_act) | set(b_act))
        if all_actions:
            w(f"  Per-action mean PnL:")
            w(f"    {'action':<8s}  {'A mean':>12s}  {'A n':>4s}  {'B mean':>12s}  {'B n':>4s}")
            for act in all_actions:
                a_vals = a_act.get(act, [])
                b_vals = b_act.get(act, [])
                a_m = _fmt_dollar(float(np.mean(a_vals))) if a_vals else "—"
                b_m = _fmt_dollar(float(np.mean(b_vals))) if b_vals else "—"
                w(f"    {act:<8s}  {a_m:>12s}  {len(a_vals):>4d}  {b_m:>12s}  {len(b_vals):>4d}")
        w("")

    # ---- §4 Per-day net PnL trace ----
    w("-" * 78)
    w("PER-DAY NET PnL  (sum of position $ changes that day, per group)")
    w("-" * 78)
    a_daily_5d = {d: (p, n) for d, p, n in _daily_net_pnl(rows, "A", "pnl_5d")}
    b_daily_5d = {d: (p, n) for d, p, n in _daily_net_pnl(rows, "B", "pnl_5d")}
    a_daily_20d = {d: (p, n) for d, p, n in _daily_net_pnl(rows, "A", "pnl_20d")}
    b_daily_20d = {d: (p, n) for d, p, n in _daily_net_pnl(rows, "B", "pnl_20d")}
    w(f"  {'date':<11s}  {'A 5d':>10s}  {'B 5d':>10s}  {'A 20d':>10s}  {'B 20d':>10s}")
    for day in days:
        a5 = a_daily_5d.get(day, (None, 0))[0]
        b5 = b_daily_5d.get(day, (None, 0))[0]
        a20 = a_daily_20d.get(day, (None, 0))[0]
        b20 = b_daily_20d.get(day, (None, 0))[0]
        w(
            f"  {day:<11s}  {_fmt_dollar(a5):>10s}  {_fmt_dollar(b5):>10s}  "
            f"{_fmt_dollar(a20):>10s}  {_fmt_dollar(b20):>10s}"
        )
    w("")
    w(f"  Cumulative 5d:  A {_fmt_dollar(sum((a5 or 0) for a5,_ in a_daily_5d.values()))}, "
      f"B {_fmt_dollar(sum((b5 or 0) for b5,_ in b_daily_5d.values()))}")
    w(f"  Cumulative 20d: A {_fmt_dollar(sum((a20 or 0) for a20,_ in a_daily_20d.values()))}, "
      f"B {_fmt_dollar(sum((b20 or 0) for b20,_ in b_daily_20d.values()))}")
    w("")

    # ---- §5 Interpretation guide ----
    w("-" * 78)
    w("INTERPRETATION GUIDE")
    w("-" * 78)
    w("  * Per-design (project-scanner-design-intent memory), scanner is an")
    w("    LLM-cost pre-filter, not a directional predictor. The right")
    w("    question is whether group A's PM decisions beat group B's.")
    w("  * A > B with p < 0.05 → scanner adds information value AT the")
    w("    agent layer (the agents make better decisions on its picks).")
    w("  * A ≈ B → scanner is 'just' a cost saver (still valuable — we don't")
    w("    pay GPT-4 to analyze 5000 tickers every day).")
    w("  * A < B → scanner picks systematically mislead the agents — real")
    w("    problem; investigate which detector triggers correlate with the")
    w("    largest PnL gaps.")
    w("  * Single-window sample sizes here are small (~30 decisions per")
    w("    group). Treat results as directional, not statistically definitive.")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
