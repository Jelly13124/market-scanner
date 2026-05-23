from unittest.mock import patch
from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx():
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=False,
    )
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=None, prior={})


@patch("src.research.sections._llm_runner.call_research_llm")
def test_emits_event_risk_section(mock_llm):
    from src.research.sections.event_risk import EventRiskSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="Earnings in 3 weeks; IV elevated.")
    out = EventRiskSection().run(_ctx())
    assert out.name == "event_risk"
    assert "Event Risk Check" in out.markdown
    assert "Earnings in 3 weeks" in out.markdown
    assert out.skipped is False


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.event_risk import EventRiskSection
    assert "event_risk" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["event_risk"], EventRiskSection)
