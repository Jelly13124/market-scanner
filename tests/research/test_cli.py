"""CLI: python -m src.research --ticker NVDA prints a TradePlan summary."""

from __future__ import annotations

from unittest.mock import patch
from io import StringIO
import sys

from src.research.models import (
    BacktestSummary, ResearchRequest, ResearchState, TradePlan,
)


def _fake_state(direction="long"):
    return ResearchState(
        request=ResearchRequest(
            ticker="NVDA", holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=False, scanner_context=None,
        ),
        persona_assignments=None,
        module_results={},
        report_markdown="# NVDA report",
        strategy=TradePlan(
            direction=direction, entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="test",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html=None,
    )


class TestCLI:
    def test_main_prints_summary(self, capsys):
        from src.research.__main__ import main
        with patch("src.research.__main__.run_research",
                   return_value=_fake_state()):
            exit_code = main(["--ticker", "NVDA"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "NVDA" in captured.out
        assert "long" in captured.out.lower()
        assert "145" in captured.out
        assert "moderate" in captured.out.lower()

    def test_main_with_custom_request(self, capsys):
        from src.research.__main__ import main
        with patch("src.research.__main__.run_research",
                   return_value=_fake_state(direction="stand_aside")):
            exit_code = main([
                "--ticker", "NVDA",
                "--holding-status", "considering_buy",
                "--position-pct", "0.03",
                "--risk", "aggressive",
                "--goal", "new_entry",
            ])
        assert exit_code == 0
