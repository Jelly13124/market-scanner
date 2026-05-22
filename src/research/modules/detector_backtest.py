"""Detector-replay backtest.

NOT an AnalysisModule subclass — runs after the synthesizer produces
the TradePlan, in its own pipeline node. Reads a per-ticker history
CSV of past detector triggers and computes how a hypothetical replay
of the plan would have fared.

Inputs:
  * today's triggered_detectors (from scanner_context)
  * the synthesized TradePlan
  * a history CSV path (one per ticker)

Output: BacktestSummary.

The CSV schema mirrors the existing v2/backtesting outputs:
  scan_date, ticker, triggered_detectors (pipe-separated),
  close_at_scan, ret_5d, ret_20d, alpha_5d, alpha_20d
"""

from __future__ import annotations

import csv
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

from src.research.models import BacktestSummary, SampleQuality, TradePlan

logger = logging.getLogger(__name__)


@dataclass
class BacktestInputs:
    ticker: str
    triggered_detectors: list[str]
    plan: TradePlan
    history_csv: Path


def _quality_for(n: int) -> SampleQuality:
    if n >= 10:
        return "strong"
    if n >= 5:
        return "moderate"
    if n >= 2:
        return "weak"
    return "insufficient"


def _matches(past_triggers: list[str], today_triggers: list[str]) -> bool:
    """Match rule per spec:
      * n <= 2 today: require exact set match
      * n >= 3 today: Jaccard overlap >= 0.6
    """
    if not past_triggers or not today_triggers:
        return False
    past_set = set(past_triggers)
    today_set = set(today_triggers)
    if len(today_set) <= 2:
        return past_set == today_set
    inter = past_set & today_set
    union = past_set | today_set
    return (len(inter) / len(union)) >= 0.6


def _read_history(csv_path: Path, ticker: str) -> list[dict]:
    if not csv_path.exists():
        return []
    out = []
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker") != ticker:
                continue
            row["_detectors"] = [
                d for d in (row.get("triggered_detectors") or "").split("|") if d
            ]
            out.append(row)
    return out


def replay_trade_plan(inputs: BacktestInputs) -> BacktestSummary:
    """Walk the history CSV; for each matching past date, treat the row's
    close as entry and use its forward returns (ret_20d) as the replayed
    outcome. Approximate — not a full day-by-day walk; uses pre-computed
    forward returns to keep the implementation cheap.
    """
    rows = _read_history(inputs.history_csv, inputs.ticker)
    matches = [r for r in rows if _matches(r["_detectors"], inputs.triggered_detectors)]

    if not matches:
        return BacktestSummary(
            matches_found=0, win_rate=None,
            avg_pnl_pct=None, max_drawdown_pct=None,
            avg_holding_days=None, sample_quality="insufficient",
            caveat=(
                f"No historical matches for {inputs.ticker} with detector "
                f"combo {inputs.triggered_detectors}"
            ),
        )

    returns: list[float] = []
    for r in matches:
        try:
            ret = float(r.get("ret_20d") or 0.0)
        except (TypeError, ValueError):
            continue
        returns.append(ret)

    if not returns:
        return BacktestSummary(
            matches_found=len(matches), win_rate=None,
            avg_pnl_pct=None, max_drawdown_pct=None,
            avg_holding_days=None, sample_quality="insufficient",
            caveat="Matches found but forward returns missing",
        )

    direction_sign = 1.0 if inputs.plan.direction == "long" else (
        -1.0 if inputs.plan.direction == "short" else 0.0
    )
    if direction_sign == 0.0:
        # stand_aside has no actionable plan to replay
        return BacktestSummary(
            matches_found=len(matches), win_rate=None,
            avg_pnl_pct=None, max_drawdown_pct=None,
            avg_holding_days=20.0,
            sample_quality=_quality_for(len(matches)),
            caveat="Plan is stand_aside; replay skipped",
        )

    directional = [ret * direction_sign for ret in returns]
    wins = sum(1 for x in directional if x > 0)
    avg = statistics.mean(directional)
    worst = min(directional)
    quality = _quality_for(len(matches))
    caveat = None
    if quality in ("weak", "moderate"):
        caveat = f"Only {len(matches)} historical matches — interpret with caution"

    return BacktestSummary(
        matches_found=len(matches),
        win_rate=round(wins / len(directional), 3),
        avg_pnl_pct=round(avg, 4),
        max_drawdown_pct=round(worst, 4),
        avg_holding_days=20.0,
        sample_quality=quality,
        caveat=caveat,
    )
