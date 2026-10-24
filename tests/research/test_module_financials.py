"""Financials module: quarter-over-quarter trend summary from the last
N earnings records (each carries an EarningsData under .quarterly)."""

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
    """4 EarningsRecord-shaped objects, newest-first, each with a quarterly
    payload carrying revenue/net_income/free_cash_flow."""
    return [
        SimpleNamespace(
            report_period=f"2025-Q{q}",
            filing_date=f"2025-{q * 3:02d}-30",
            quarterly=SimpleNamespace(
                revenue=40e9 + q * 1e9,
                net_income=15e9 + q * 0.3e9,
                free_cash_flow=12e9 + q * 0.25e9,
            ),
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
            prices=[], financials=[],
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=_series(),
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        out = FinancialsModule().run(_req(), None, shared)
        assert out.skipped is False
        assert "revenue_latest" in out.key_metrics
        # Spot-check: most recent quarter should have non-zero revenue
        assert out.key_metrics["revenue_latest"] > 0

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

    def test_skipped_when_records_have_no_quarterly(self):
        """Filter rejects records where .quarterly is None (e.g., annual-only filings)."""
        annual_only = [SimpleNamespace(
            report_period="2024", filing_date="2024-12-31", quarterly=None,
        )]
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=annual_only,
            company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = FinancialsModule().run(_req(), None, shared)
        assert out.skipped is True
