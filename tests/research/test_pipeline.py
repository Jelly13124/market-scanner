"""Pipeline: glue everything together. With mocks, run_research(request)
should fetch SharedData, run all registered modules, pass valuation+
technical to risk_position, run synthesizer, run detector_backtest,
return a ResearchState with all fields populated."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from src.research.models import (
    ResearchRequest, ModuleResult, TradePlan, BacktestSummary,
)
from src.research.shared_data import SharedData


def _req(scanner_ctx=None):
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=scanner_ctx,
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


class TestRunResearch:
    @patch("src.research.pipeline.fetch_shared_data")
    @patch("src.research.pipeline.synthesize")
    @patch("src.research.pipeline.replay_trade_plan")
    def test_happy_path(self, mock_replay, mock_synth, mock_fetch):
        from src.research.pipeline import run_research
        from src.research.modules.base import AnalysisModule

        mock_fetch.return_value = _shared()
        mock_synth.return_value = ("# report", TradePlan(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="x",
        ))
        mock_replay.return_value = BacktestSummary(
            matches_found=0, win_rate=None, avg_pnl_pct=None,
            max_drawdown_pct=None, avg_holding_days=None,
            sample_quality="insufficient", caveat="no history",
        )

        # Patch ALL_MODULES with one stub module that always returns a
        # ModuleResult, to keep this test isolated from real modules.
        class _Stub(AnalysisModule):
            name = "stub"
            supports_personas = []
            def run(self, request, persona, shared_data):
                return ModuleResult(
                    module_name="stub", persona_used=None,
                    markdown="stub output",
                )

        with patch("src.research.pipeline.ALL_MODULES", [_Stub]):
            state = run_research(_req())

        assert state["strategy"].direction == "long"
        assert state["backtest_summary"].matches_found == 0
        assert "stub" in state["module_results"]
        assert state["report_markdown"] == "# report"

    @patch("src.research.pipeline.fetch_shared_data")
    def test_no_scanner_context_uses_empty_triggers(self, mock_fetch):
        """When scanner_context is None, backtest is invoked with empty
        triggered_detectors list — replay_trade_plan returns insufficient."""
        from src.research.pipeline import run_research
        mock_fetch.return_value = _shared()
        with patch("src.research.pipeline.ALL_MODULES", []), \
             patch("src.research.pipeline.synthesize",
                   return_value=("r", TradePlan(
                       direction="stand_aside", entry_price=None,
                       target_price=None, stop_price=None,
                       horizon_days=0, sizing_pct=0.0, confidence=0,
                       rationale="x",
                   ))), \
             patch("src.research.pipeline.replay_trade_plan") as mock_replay:
            mock_replay.return_value = BacktestSummary(
                matches_found=0, win_rate=None, avg_pnl_pct=None,
                max_drawdown_pct=None, avg_holding_days=None,
                sample_quality="insufficient", caveat="no triggers",
            )
            state = run_research(_req(scanner_ctx=None))
            args = mock_replay.call_args[0][0]  # BacktestInputs
            assert args.triggered_detectors == []
