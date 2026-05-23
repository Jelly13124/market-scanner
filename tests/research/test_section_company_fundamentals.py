from unittest.mock import patch
from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx(persona=None, with_financials=True):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=bool(persona),
    )
    # Synthetic latest financials object with attribute-style access
    class _FinObj:
        revenue_growth = 0.45
        gross_margin = 0.75
        operating_margin = 0.50
        net_margin = 0.42
        return_on_invested_capital = 0.85
        free_cash_flow_yield = 0.025
        debt_to_equity = 0.15
    financials = [_FinObj()] if with_financials else []
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=financials, insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={"sector": "Tech"},
        sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=persona, prior={})


@patch("src.research.sections._llm_runner.call_research_llm")
def test_emits_company_fundamentals(mock_llm):
    from src.research.sections.company_fundamentals import (
        CompanyFundamentalsSection, _Narrative)
    mock_llm.return_value = _Narrative(narrative="Strong moat.")
    out = CompanyFundamentalsSection().run(_ctx())
    assert out.name == "company_fundamentals"
    assert "Company Fundamentals" in out.markdown
    assert out.skipped is False


@patch("src.research.sections._llm_runner.call_research_llm")
def test_supports_personas(mock_llm):
    from src.research.sections.company_fundamentals import (
        CompanyFundamentalsSection, _Narrative)
    mock_llm.return_value = _Narrative(narrative="ok")
    for persona in ("buffett", "munger", "fisher"):
        out = CompanyFundamentalsSection().run(_ctx(persona=persona))
        assert out.persona_used == persona


@patch("src.research.sections._llm_runner.call_research_llm")
def test_packs_metrics_into_prompt(mock_llm):
    from src.research.sections.company_fundamentals import (
        CompanyFundamentalsSection, _Narrative)
    captured = {}
    def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return _Narrative(narrative="ok")
    mock_llm.side_effect = _capture
    CompanyFundamentalsSection().run(_ctx())
    p = captured["prompt"]
    # Metrics should be in the prompt
    assert "revenue_growth" in p
    assert "0.45" in p or "0.4500" in p


@patch("src.research.sections._llm_runner.call_research_llm")
def test_handles_missing_financials(mock_llm):
    from src.research.sections.company_fundamentals import (
        CompanyFundamentalsSection, _Narrative)
    mock_llm.return_value = _Narrative(narrative="No metrics.")
    out = CompanyFundamentalsSection().run(_ctx(with_financials=False))
    assert out.skipped is False  # still runs; just notes lack of metrics


def test_registered_in_section_registry():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.company_fundamentals import CompanyFundamentalsSection
    assert "company_fundamentals" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["company_fundamentals"], CompanyFundamentalsSection)
