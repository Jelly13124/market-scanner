"""Financials module: quarter-over-quarter trend summary from the last
N financial_metrics rows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.financials import FinancialsModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _series():
    return [
        SimpleNamespace(
            report_period=f"2025-Q{q}",
            revenue=40e9 + q * 1e9,
            net_income=15e9 + q * 0.3e9,
            free_cash_flow=12e9 + q * 0.25e9,
        )
        for q in range(4, 0, -1)
    ]


class TestFinancialsModule:
    def test_name(self):
        assert FinancialsModule().name == "financials"

    @patch("src.research.modules.financials.call_research_llm")
    def test_run_with_4q_data(self, mock_llm):
        from src.research.modules.financials import _FinancialsNarrative
        mock_llm.return_value = _FinancialsNarrative(narrative="Revenue grew QoQ.")
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_series(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        out = FinancialsModule().run(_req(), None, shared)
        assert out.skipped is False
        assert "revenue_latest" in out.key_metrics

    def test_skipped_when_empty(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = FinancialsModule().run(_req(), None, shared)
        assert out.skipped is True
