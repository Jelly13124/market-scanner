from unittest.mock import patch
from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx(with_earnings=True):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=False,
    )
    # Synthetic earnings history with `period` + `quarterly` attrs
    class _Quarterly:
        def __init__(self, rev, ni, fcf):
            self.revenue = rev; self.net_income = ni; self.free_cash_flow = fcf
    class _ER:
        def __init__(self, period, rev, ni, fcf):
            self.period = period
            self.quarterly = _Quarterly(rev, ni, fcf)
    earnings = []
    if with_earnings:
        earnings = [
            _ER("2026-Q1", 35e9, 19e9, 18e9),
            _ER("2025-Q4", 34e9, 18e9, 17e9),
            _ER("2025-Q3", 30e9, 16e9, 15e9),
            _ER("2025-Q2", 28e9, 14e9, 13e9),
        ]
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=earnings, company_facts={"sector": "Tech"},
        sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=None, prior={})


@patch("src.research.sections._llm_runner.call_research_llm")
def test_emits_financial_statements(mock_llm):
    from src.research.sections.financial_statements import (
        FinancialStatementsSection, _Narrative)
    mock_llm.return_value = _Narrative(narrative="Revenue growing.")
    out = FinancialStatementsSection().run(_ctx())
    assert out.name == "financial_statements"
    assert "Financial Statement Review" in out.markdown
    assert "Revenue growing" in out.markdown


@patch("src.research.sections._llm_runner.call_research_llm")
def test_packs_earnings_history_into_prompt(mock_llm):
    from src.research.sections.financial_statements import (
        FinancialStatementsSection, _Narrative)
    captured = {}
    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")
    mock_llm.side_effect = _capture
    FinancialStatementsSection().run(_ctx())
    p = captured["prompt"]
    assert "2026-Q1" in p
    assert "rev=" in p
    assert "ni=" in p
    assert "fcf=" in p


@patch("src.research.sections._llm_runner.call_research_llm")
def test_handles_missing_earnings(mock_llm):
    from src.research.sections.financial_statements import (
        FinancialStatementsSection, _Narrative)
    mock_llm.return_value = _Narrative(narrative="No data.")
    out = FinancialStatementsSection().run(_ctx(with_earnings=False))
    assert out.skipped is False


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.financial_statements import FinancialStatementsSection
    assert "financial_statements" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["financial_statements"], FinancialStatementsSection)
