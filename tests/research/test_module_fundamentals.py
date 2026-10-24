"""Fundamentals module: extract revenue_growth / margins / ROIC etc.
from SharedData.financials, ask LLM for moat/quality narrative."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.fundamentals import FundamentalsModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _fundamentals():
    return [SimpleNamespace(
        report_period="2025-Q4",
        revenue=50_000_000_000, revenue_growth=0.38,
        gross_margin=0.74, operating_margin=0.55,
        net_margin=0.45, return_on_invested_capital=0.42,
        free_cash_flow_margin=0.40, debt_to_equity=0.18,
    )]


class TestFundamentalsModule:
    def test_name(self):
        m = FundamentalsModule()
        assert m.name == "fundamentals"

    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_emits_key_metrics(self, mock_llm):
        from src.research.modules.fundamentals import _FundamentalsNarrative
        mock_llm.return_value = _FundamentalsNarrative(
            narrative="Strong margins, high ROIC, growing 38%.",
        )
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        out = FundamentalsModule().run(_req(), None, shared)
        assert out.skipped is False
        assert out.key_metrics["revenue_growth"] == 0.38
        assert out.key_metrics["roic"] == 0.42

    def test_skipped_when_no_financials(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = FundamentalsModule().run(_req(), None, shared)
        assert out.skipped is True


class TestFundamentalsPersonaPath:
    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_buffett_persona_recorded(self, mock_llm):
        from src.research.modules.fundamentals import _FundamentalsNarrative
        mock_llm.return_value = _FundamentalsNarrative(
            narrative="Quality moat per Buffett lens.",
        )
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        out = FundamentalsModule().run(_req(), "buffett", shared)
        assert out.persona_used == "buffett"

    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_buffett_prompt_includes_persona_voice(self, mock_llm):
        from src.research.modules.fundamentals import _FundamentalsNarrative
        captured = {}
        def _capture(prompt, model, **kw):
            captured["prompt"] = prompt
            return _FundamentalsNarrative(narrative="ok")
        mock_llm.side_effect = _capture
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        FundamentalsModule().run(_req(), "buffett", shared)
        # Persona system prompt should reference Buffett's voice
        prompt_text = captured["prompt"].lower()
        assert any(kw in prompt_text for kw in ("buffett", "moat", "owner earnings"))

    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_unsupported_persona_coerced_to_none(self, mock_llm):
        """Router could pick a persona not in this module's supports_personas;
        _coerce_persona returns None and the module runs objective."""
        from src.research.modules.fundamentals import _FundamentalsNarrative
        mock_llm.return_value = _FundamentalsNarrative(narrative="objective.")
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        # Wood is NOT in fundamentals.supports_personas
        out = FundamentalsModule().run(_req(), "wood", shared)
        assert out.persona_used is None
