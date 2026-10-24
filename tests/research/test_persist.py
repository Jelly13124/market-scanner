"""state_to_db_kwargs: convert a ResearchState into the two kwarg dicts
the ResearchReportRepository.create_with_plan expects."""

from __future__ import annotations

from dataclasses import asdict

from src.research.models import (
    BacktestSummary, ResearchRequest, ResearchState, TradePlan,
)
from src.research.persist import state_to_db_kwargs


def _state():
    req = ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=True,
        scanner_context={"scan_date": "2026-05-22",
                         "triggered_detectors": ["earnings_event"]},
    )
    return ResearchState(
        request=req,
        persona_assignments={"fundamentals": "buffett", "_rationale": "x"},
        module_results={},
        report_markdown="# NVDA",
        strategy=TradePlan(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="r",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html="<html></html>",
    )


class TestStateToDbKwargs:
    def test_report_dict_has_required_fields(self):
        report, plan = state_to_db_kwargs(_state(), duration_seconds=42.0)
        assert report["ticker"] == "NVDA"
        assert report["scan_date"] == "2026-05-22"
        assert report["report_markdown"] == "# NVDA"
        assert report["rendered_html"] == "<html></html>"
        assert report["use_personas"] is True
        assert report["persona_assignments_json"]["fundamentals"] == "buffett"
        assert report["duration_seconds"] == 42.0
        assert isinstance(report["request_json"], dict)
        assert report["request_json"]["ticker"] == "NVDA"

    def test_plan_dict_has_trade_plan_and_backtest_fields(self):
        _, plan = state_to_db_kwargs(_state(), duration_seconds=42.0)
        assert plan["direction"] == "long"
        assert plan["entry_price"] == 145.0
        assert plan["confidence"] == 72
        assert plan["backtest_matches_found"] == 5
        assert plan["backtest_win_rate"] == 0.6
        assert plan["backtest_sample_quality"] == "moderate"

    def test_scan_date_falls_back_to_today_when_no_scanner_context(self):
        s = _state()
        s["request"].scanner_context = None
        from datetime import date
        report, _ = state_to_db_kwargs(s, duration_seconds=1.0)
        assert report["scan_date"] == date.today().isoformat()
