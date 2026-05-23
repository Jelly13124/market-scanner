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
def test_emits_valuation(mock_llm):
    from src.research.sections.valuation import ValuationSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="body.")
    out = ValuationSection().run(_ctx())
    assert out.name == "valuation"
    assert "Valuation Analysis" in out.markdown


@patch("src.research.sections._llm_runner.call_research_llm")
def test_valuation_persona(mock_llm):
    from src.research.sections.valuation import ValuationSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="ok")
    out = ValuationSection().run(_ctx(persona="buffett"))
    assert out.persona_used == "buffett"


def test_valuation_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.valuation import ValuationSection
    assert "valuation" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["valuation"], ValuationSection)
