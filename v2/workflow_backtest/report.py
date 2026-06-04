"""Render the workflow-backtest results to disk.

Two artifacts land in ``out_dir``:

  * ``findings_agent_backtest.md`` — human-readable summary with an
    "## A/B by regime" section (scanner vs random direction-adjusted SIGNAL
    return deltas of directional bets (long+short) + Welch t per regime) and an
    "## Absolute (post-cutoff)" section (per-arm portfolio metrics restricted to
    post-cutoff dates).
  * ``decisions.csv`` — one row per (scan_date, arm, ticker) decision, flat
    enough to pivot in a spreadsheet.

``write`` is pure I/O over the ``results`` dict the runner assembles — it does
no computation beyond formatting, so the runner stays the single source of
truth for the numbers.
"""

from __future__ import annotations

import csv
import os


def _fmt(x, pct=False):
    """Format a number for the markdown tables; ``-`` for None/NaN."""
    if x is None:
        return "-"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if v != v:  # NaN
        return "-"
    return f"{v * 100:.2f}%" if pct else f"{v:.3f}"


def _write_decisions_csv(path, decision_rows):
    fields = ["scan_date", "arm", "regime_name", "regime_label", "is_post_cutoff",
              "ticker", "action", "quantity", "confidence", "ret_21d", "ret_42d",
              "ret_63d", "alpha_21d", "signal_ret_21d"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in decision_rows:
            w.writerow(r)


def write(out_dir, results) -> dict:
    """Write the markdown report + decisions CSV; return their paths."""
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "findings_agent_backtest.md")
    decisions_csv = os.path.join(out_dir, "decisions.csv")

    ab_by_regime = results.get("ab_by_regime") or {}
    abs_metrics = results.get("absolute_post_cutoff") or {}
    decision_rows = results.get("decision_rows") or []
    n_dates = results.get("n_dates", 0)

    lines: list[str] = []
    lines.append("# Agent Workflow Backtest — scanner vs random")
    lines.append("")
    lines.append(f"- scan dates: {n_dates}")
    lines.append(f"- decisions logged: {len(decision_rows)}")
    lines.append("")

    # --- A/B by regime ----------------------------------------------------
    lines.append("## A/B by regime")
    lines.append("")
    lines.append("Direction-adjusted 21d SIGNAL return of directional bets (long+short): "
                 "scanner arm vs random arm.")
    lines.append("")
    lines.append("| regime | label | n_scanner | n_random | mean_scanner | mean_random | diff | welch_t |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for regime, ab in sorted(ab_by_regime.items()):
        label = ab.get("regime_label", "")
        lines.append(
            f"| {regime} | {label} | {ab.get('n_a', 0)} | {ab.get('n_b', 0)} | "
            f"{_fmt(ab.get('mean_a'), pct=True)} | {_fmt(ab.get('mean_b'), pct=True)} | "
            f"{_fmt(ab.get('diff'), pct=True)} | {_fmt(ab.get('t'))} |"
        )
    if not ab_by_regime:
        lines.append("| (no regimes) | | | | | | | |")
    lines.append("")

    # --- Absolute (post-cutoff) ------------------------------------------
    lines.append("## Absolute (post-cutoff)")
    lines.append("")
    lines.append("Equal-weight fixed-hold portfolio metrics, post-cutoff scan dates only.")
    lines.append("")
    lines.append("| arm | final_value | total_return | sharpe_ratio | max_drawdown | n_trades |")
    lines.append("|---|---|---|---|---|---|")
    for arm in sorted(abs_metrics.keys()):
        m = abs_metrics[arm] or {}
        metrics = m.get("metrics") or {}
        lines.append(
            f"| {arm} | {_fmt(m.get('final_value'))} | {_fmt(m.get('total_return'), pct=True)} | "
            f"{_fmt(metrics.get('sharpe_ratio'))} | {_fmt(metrics.get('max_drawdown'), pct=True)} | "
            f"{m.get('n_trades', 0)} |"
        )
    if not abs_metrics:
        lines.append("| (no arms) | | | | | |")
    lines.append("")

    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    _write_decisions_csv(decisions_csv, decision_rows)

    return {"report_path": report_path, "decisions_csv": decisions_csv}
