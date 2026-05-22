"""Technical module: compute RSI(14), 50d/200d SMA, recent support/resistance
from SharedData.prices."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.technical import TechnicalModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _bars(closes):
    return [
        SimpleNamespace(
            time=f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
            close=c, adjusted_close=c,
            high=c * 1.01, low=c * 0.99, open=c, volume=1_000_000,
        )
        for i, c in enumerate(closes)
    ]


class TestTechnicalModule:
    def test_name(self):
        assert TechnicalModule().name == "technical"

    @patch("src.research.modules.technical.call_research_llm")
    def test_run_with_long_history(self, mock_llm):
        from src.research.modules.technical import _TechnicalNarrative
        mock_llm.return_value = _TechnicalNarrative(narrative="Above 50d SMA.")
        closes = [100 + i * 0.5 for i in range(250)]
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=_bars(closes), financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = TechnicalModule().run(_req(), None, shared)
        assert out.skipped is False
        assert "rsi_14" in out.key_metrics
        assert "sma_50" in out.key_metrics
        assert "support" in out.key_metrics

    def test_skipped_when_short_history(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=_bars([100, 101, 102]),
            financials=[], insider_trades=[], news=[],
            analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = TechnicalModule().run(_req(), None, shared)
        assert out.skipped is True
