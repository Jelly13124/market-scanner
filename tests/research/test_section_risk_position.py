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
def test_emits_risk_position(mock_llm):
    from src.research.sections.risk_position import RiskPositionSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="body.")
    out = RiskPositionSection().run(_ctx())
    assert out.name == "risk_position"
    assert "Risk and Position Sizing" in out.markdown


@patch("src.research.sections._llm_runner.call_research_llm")
def test_risk_position_persona(mock_llm):
    from src.research.sections.risk_position import RiskPositionSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="ok")
    out = RiskPositionSection().run(_ctx(persona="druckenmiller"))
    assert out.persona_used == "druckenmiller"


def test_risk_position_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.risk_position import RiskPositionSection
    assert "risk_position" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["risk_position"], RiskPositionSection)
