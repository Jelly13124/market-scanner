from unittest.mock import patch

from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx(persona=None):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=bool(persona),
    )
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[{"close": float(100 + i * 0.1)} for i in range(300)],
        financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={"sector": "Tech"},
        sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=persona, prior={})


@patch("src.research.sections._llm_runner.call_research_llm")
def test_emits_technical(mock_llm):
    from src.research.sections.technical import TechnicalSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="body.")
    out = TechnicalSection().run(_ctx())
    assert out.name == "technical"
    assert "Technical Analysis" in out.markdown


@patch("src.research.sections._llm_runner.call_research_llm")
def test_technical_includes_backtest_placeholder(mock_llm):
    from src.research.sections.technical import TechnicalSection, _Narrative
    mock_llm.return_value = _Narrative(
        narrative="Daily trend up. Backtest validation: see sub-section below."
    )
    out = TechnicalSection().run(_ctx())
    assert "Backtest" in out.markdown


def test_technical_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.technical import TechnicalSection
    assert "technical" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["technical"], TechnicalSection)
