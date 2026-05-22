"""Macro module: read SPY trailing return + VIX from SharedData,
compute regime classification, call LLM for narrative. Returns a
ModuleResult with markdown + key_metrics."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from src.research.modules.macro import MacroModule
from src.research.models import ResearchRequest, ModuleResult
from src.research.shared_data import SharedData


def _make_request():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=None,
    )


def _make_shared(spy_returns_pct: float = 0.05):
    """Build SharedData with 21 SPY closes producing a known trailing 20d return."""
    from types import SimpleNamespace
    base = 400.0
    end = base * (1 + spy_returns_pct)
    closes = [base + (end - base) * (i / 20) for i in range(21)]
    spy_prices = [
        SimpleNamespace(time=f"2026-04-{i + 1:02d}", close=c, adjusted_close=c)
        for i, c in enumerate(closes)
    ]
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={"sector": "Technology"},
        sector_etf_prices=[], spy_prices=spy_prices,
    )


class TestMacroModule:
    def test_name_and_no_personas(self):
        m = MacroModule()
        assert m.name == "macro"
        assert m.supports_personas == []

    @patch("src.research.modules.macro.call_research_llm")
    def test_run_returns_module_result(self, mock_llm):
        from src.research.modules.macro import _MacroNarrative
        mock_llm.return_value = _MacroNarrative(narrative="SPY up 5%, regime up.")

        m = MacroModule()
        out = m.run(_make_request(), None, _make_shared(spy_returns_pct=0.05))
        assert isinstance(out, ModuleResult)
        assert out.module_name == "macro"
        assert out.markdown
        assert "spy_return_20d" in out.key_metrics
        assert out.key_metrics["spy_return_20d"] == round(0.05, 4)
        assert out.skipped is False

    def test_skipped_when_no_spy_data(self):
        shared = _make_shared()
        shared.spy_prices = []
        m = MacroModule()
        out = m.run(_make_request(), None, shared)
        assert out.skipped is True
        assert "SPY" in (out.skip_reason or "")
