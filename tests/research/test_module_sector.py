"""Sector module: read ticker prices + sector ETF prices from SharedData,
compute relative strength (RS = ticker_20d_return - etf_20d_return)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.sector import SectorModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _bars(start: float, ret: float, n: int = 21):
    end = start * (1 + ret)
    closes = [start + (end - start) * (i / (n - 1)) for i in range(n)]
    return [
        SimpleNamespace(time=f"2026-04-{i + 1:02d}", close=c, adjusted_close=c)
        for i, c in enumerate(closes)
    ]


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=None,
    )


def _shared(ticker_ret=0.10, etf_ret=0.04):
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=_bars(100.0, ticker_ret),
        financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None,
        earnings_history=[],
        company_facts={"sector": "Technology"},
        sector_etf_prices=_bars(200.0, etf_ret),
        spy_prices=[],
    )


class TestSectorModule:
    def test_name(self):
        assert SectorModule().name == "sector"

    @patch("src.research.modules.sector.call_research_llm")
    def test_relative_strength_positive(self, mock_llm):
        from src.research.modules.sector import _SectorNarrative
        mock_llm.return_value = _SectorNarrative(narrative="NVDA outperforms XLK.")

        out = SectorModule().run(_req(), None, _shared(ticker_ret=0.10, etf_ret=0.04))
        assert out.skipped is False
        assert out.key_metrics["relative_strength_pp"] == round((0.10 - 0.04) * 100, 2)

    def test_skipped_when_no_etf_data(self):
        shared = _shared()
        shared.sector_etf_prices = []
        out = SectorModule().run(_req(), None, shared)
        assert out.skipped is True
