"""Cross-regime summary for the quant on/off ablation A/B.

Reads the 3 per-regime CSVs from scripts/ab_backtest_quant_ablation.py,
produces one report with:

  * Per-regime block: A (quant on) vs B (quant off) — 20d PnL mean + CI,
    cumulative PnL, win rate, action mix.
  * Combined block: same metrics aggregated across all 3 regimes.
  * Welch t-test on per-decision 20d PnL gap.

Labels A=quant ON, B=quant OFF — opposite semantic of ab_backtest_summary
(which is scanner vs random), so we use a parallel script rather than
parameterizing.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as _scipy

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from v2.backtesting.analyze import bootstrap_ci  # noqa: E402


WINDOWS = ("5d", "20d")


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


def _ci(values: list[float]) -> str:
    if not values:
        return "—"
    mean, lo, hi = bootstrap_ci(values, n_resamples=5000)
    if mean is None:
        return "—"
    if lo is None or hi is None:
        return f"{_fmt_dollar(mean)} (n={len(values)})"
    return f"{_fmt_dollar(mean):>9s}  [{_fmt_dollar(lo):>9s}, {_fmt_dollar(hi):>9s}]  n={len(values)}"


def _pnl(rows: list[dict], group: str, win: str) -> list[float]:
    col = f"pnl_{win}"
    out: list[float] = []
    for r in rows:
        if r.get("group") != group:
            continue
        v = _to_float(r.get(col))
        if v is not None:
            out.append(v)
    return out


def _hit_rate(values: list[float]) -> str:
    if not values:
        return "—"
    wins = sum(1 for v in values if v > 0)
    n = len(values)
    rate = wins / n
    ci = _scipy.binomtest(wins, n).proportion_ci(method="wilson")
    return f"{rate * 100:5.1f}%  [{ci.low*100:.1f}%, {ci.high*100:.1f}%]  ({wins}/{n})"


def _action_mix(rows: list[dict], group: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.get("group") == group:
            out[(r.get("action") or "—").lower()] += 1
    return dict(out)


def _ticker_overlap(rows: list[dict]) -> tuple[set[str], set[str], int]:
    """Returns (A-only, B-only, shared-count) of (scan_date, ticker) pairs."""
    a = {(r["scan_date"], r["ticker"]) for r in rows if r.get("group") == "A"}
    b = {(r["scan_date"], r["ticker"]) for r in rows if r.get("group") == "B"}
    return a - b, b - a, len(a & b)


def _emit_block(label: str, rows: list[dict], w) -> None:
    w("=" * 78)
    w(f"  {label}")
    w("=" * 78)
    days = sorted({r["scan_date"] for r in rows})
    n_a = sum(1 for r in rows if r["group"] == "A")
    n_b = sum(1 for r in rows if r["group"] == "B")
    w(f"  Days:                {len(days)}  ({days[0]} → {days[-1]})")
    w(f"  Group A decisions:   {n_a}  (quant ON)")
    w(f"  Group B decisions:   {n_b}  (quant OFF)")

    # Ticker overlap
    a_only, b_only, shared = _ticker_overlap(rows)
    total_unique = len(a_only) + len(b_only) + shared
    if total_unique:
        w(f"  Ticker overlap:      shared={shared}/{total_unique} "
          f"({shared/total_unique*100:.0f}%), A-only={len(a_only)}, "
          f"B-only={len(b_only)}")
    w("")

    # Action mix
    a_mix = _action_mix(rows, "A")
    b_mix = _action_mix(rows, "B")
    actions = sorted(set(a_mix) | set(b_mix))
    if actions:
        w("  Action mix:")
        w(f"    {'action':<8}  {'A':>5}  {'B':>5}")
        for a in actions:
            w(f"    {a:<8}  {a_mix.get(a, 0):>5}  {b_mix.get(a, 0):>5}")
        w("")

    # PnL per window
    for win in WINDOWS:
        a_pnl = _pnl(rows, "A", win)
        b_pnl = _pnl(rows, "B", win)
        w(f"  {win} per-decision PnL (bootstrap 95% CI):")
        w(f"    A (quant ON):   {_ci(a_pnl)}")
        w(f"    B (quant OFF):  {_ci(b_pnl)}")
        if len(a_pnl) >= 2 and len(b_pnl) >= 2:
            res = _scipy.ttest_ind(a_pnl, b_pnl, equal_var=False)
            diff = float(np.mean(a_pnl) - np.mean(b_pnl))
            sig = " *" if res.pvalue < 0.05 else ""
            w(f"    t-test (A−B):   diff={_fmt_dollar(diff)},  p={res.pvalue:.4f}{sig}")
        w(f"    Cumulative:     A {_fmt_dollar(sum(a_pnl))}  vs  B {_fmt_dollar(sum(b_pnl))}  "
          f"→ Δ {_fmt_dollar(sum(a_pnl) - sum(b_pnl))}")
        w(f"    Hit rate:")
        w(f"      A:  {_hit_rate(a_pnl)}")
        w(f"      B:  {_hit_rate(b_pnl)}")
        w("")


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: python scripts/ab_quant_ablation_summary.py "
              "<up.csv> <down.csv> <chop.csv> [--out path]", file=sys.stderr)
        return 1

    up_csv = Path(sys.argv[1])
    down_csv = Path(sys.argv[2])
    chop_csv = Path(sys.argv[3])

    out_path = Path("outputs/ab_quant_ablation_combined_summary.txt")
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])

    sources = [
        ("UP regime",   up_csv),
        ("DOWN regime", down_csv),
        ("CHOP regime", chop_csv),
    ]

    lines: list[str] = []
    w = lines.append

    w("#" * 78)
    w("# QUANT SIGNALS ON/OFF — FULL PIPELINE A/B (scanner → 11 agents → PM)")
    w("# A = quant_signals enabled (composite = 0.6×event + 0.4×quant)")
    w("# B = quant_signals disabled (composite = event_score only)")
    w("#" * 78)
    w("")

    all_rows: list[dict] = []
    for label, path in sources:
        if not path.exists():
            w(f"MISSING: {label} CSV not found at {path}")
            w("")
            continue
        rows = _read_rows(path)
        if not rows:
            w(f"EMPTY: {label} CSV at {path}")
            w("")
            continue
        # Tag every row with its regime for the combined view
        for r in rows:
            r["_regime"] = label
        all_rows.extend(rows)
        _emit_block(label, rows, w)

    if all_rows:
        _emit_block("COMBINED — all 3 regimes pooled", all_rows, w)

    # Interpretation guide
    w("-" * 78)
    w("INTERPRETATION")
    w("-" * 78)
    w("  * A > B with p<0.05 → quant_signals add real value at the agent")
    w("    layer (better-scored watchlists → better PM decisions).")
    w("  * A ≈ B → quant_signals are inert in the agent path; scanner")
    w("    edge (Part 1) comes from event detection alone.")
    w("  * A < B → quant_signals actively mislead PM; investigate which")
    w("    quant component dominates the worst picks.")
    w("  * Compare against Part 1 (A=scanner vs B=random):")
    w("      Part 1 UP   20d cum: A+$32.8k vs B+$6.8k    → +$26k")
    w("      Part 1 DOWN 20d cum: A+$0.7k  vs B−$11.8k  → +$12.4k")
    w("      Part 1 CHOP 20d cum: A+$11.3k vs B+$11.9k   → −$0.6k")
    w("    If this Part 2 A−B is small relative to Part 1's, quant's")
    w("    contribution is incremental on top of event detection.")
    w("  * Single-window n=~30 per group: results are directional.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
