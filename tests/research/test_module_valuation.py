"""Valuation module: compute simple DCF + relative multiples;
emit fair_value_low / fair_value_high in key_metrics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.valuation import ValuationModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _shared(price=145.0, eps_ttm=4.0, fcf_per_share=0.5, shares=24e9):
    """FinancialMetrics carries per-share metrics + market_cap. Absolute
    FCF derived as fcf_per_share * shares."""
    fin = SimpleNamespace(
        earnings_per_share=eps_ttm,
        free_cash_flow_per_share=fcf_per_share,
        market_cap=price * shares,
    )
    bars = [SimpleNamespace(time="2026-05-22", close=price, adjusted_close=price)]
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=bars, financials=[fin],
        insider_trades=[], news=[], analyst_actions=[],
        analyst_targets=None, earnings_history=[],
        company_facts={"market_cap": price * shares, "weighted_average_shares": shares},
        sector_etf_prices=[], spy_prices=[],
    )


class TestValuationModule:
    def test_name(self):
        assert ValuationModule().name == "valuation"

    @patch("src.research.modules.valuation.call_research_llm")
    def test_outputs_fair_value_range(self, mock_llm):
        from src.research.modules.valuation import _ValuationNarrative
        mock_llm.return_value = _ValuationNarrative(narrative="Fairly valued.")
        out = ValuationModule().run(_req(), None, _shared())
        assert out.skipped is False
        assert "fair_value_low" in out.key_metrics
        assert "fair_value_high" in out.key_metrics
        assert out.key_metrics["fair_value_low"] <= out.key_metrics["fair_value_high"]

    def test_skipped_when_no_financials(self):
        shared = _shared()
        shared.financials = []
        out = ValuationModule().run(_req(), None, shared)
        assert out.skipped is True

    def test_skipped_when_neither_eps_nor_fcf_positive(self):
        shared = _shared(eps_ttm=0.0, fcf_per_share=0.0)
        out = ValuationModule().run(_req(), None, shared)
        assert out.skipped is True
