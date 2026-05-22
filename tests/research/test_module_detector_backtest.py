"""Detector backtest: replays a TradePlan over past dates where the same
detector set fired on this ticker. Pure deterministic math; no LLM."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.research.modules.detector_backtest import (
    replay_trade_plan,
    BacktestInputs,
)
from src.research.models import TradePlan, BacktestSummary


def _write_history_csv(path: Path, rows: list[dict]):
    cols = ["scan_date", "ticker", "triggered_detectors", "close_at_scan",
            "ret_5d", "ret_20d", "alpha_5d", "alpha_20d"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _plan(entry=145.0, target=165.0, stop=138.0, horizon=30):
    return TradePlan(
        direction="long", entry_price=entry, target_price=target,
        stop_price=stop, horizon_days=horizon, sizing_pct=0.05,
        confidence=70, rationale="test",
    )


class TestReplay:
    def test_strong_sample(self, tmp_path):
        csv_path = tmp_path / "nvda_history.csv"
        _write_history_csv(csv_path, [
            {"scan_date": "2025-01-15", "ticker": "NVDA",
             "triggered_detectors": "earnings_event|insider_cluster",
             "close_at_scan": 100.0, "ret_20d": 0.15},
            {"scan_date": "2025-03-20", "ticker": "NVDA",
             "triggered_detectors": "earnings_event|insider_cluster",
             "close_at_scan": 110.0, "ret_20d": -0.05},
        ] * 6)  # 12 rows total — strong sample

        summary = replay_trade_plan(BacktestInputs(
            ticker="NVDA",
            triggered_detectors=["earnings_event", "insider_cluster"],
            plan=_plan(),
            history_csv=csv_path,
        ))
        assert isinstance(summary, BacktestSummary)
        assert summary.matches_found == 12
        assert summary.sample_quality == "strong"
        assert summary.win_rate is not None

    def test_insufficient(self, tmp_path):
        csv_path = tmp_path / "nvda_history.csv"
        _write_history_csv(csv_path, [])
        summary = replay_trade_plan(BacktestInputs(
            ticker="NVDA",
            triggered_detectors=["earnings_event"],
            plan=_plan(),
            history_csv=csv_path,
        ))
        assert summary.matches_found == 0
        assert summary.sample_quality == "insufficient"
        assert summary.caveat is not None

    def test_jaccard_overlap_match(self, tmp_path):
        """When today's trigger set has >=3 detectors, accept past dates
        with Jaccard overlap >= 0.6. Today: {a,b,c}; past with {a,b}
        has overlap 2/3 = 0.67 -> matches."""
        csv_path = tmp_path / "x.csv"
        _write_history_csv(csv_path, [
            {"scan_date": "2025-01-15", "ticker": "NVDA",
             "triggered_detectors": "a|b",
             "close_at_scan": 100.0, "ret_20d": 0.10},
        ] * 5)
        summary = replay_trade_plan(BacktestInputs(
            ticker="NVDA",
            triggered_detectors=["a", "b", "c"],  # 3 today
            plan=_plan(),
            history_csv=csv_path,
        ))
        assert summary.matches_found == 5
