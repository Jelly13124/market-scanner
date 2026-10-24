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
        company_facts={"sector": "Tech"},
        sector_etf_prices=[100, 101], spy_prices=[100, 101],
    )
    return SectionContext(request=req, shared=shared, persona=None, prior={})


@patch("src.research.sections._llm_runner.call_research_llm")
def test_emits_sector_section(mock_llm):
    from src.research.sections.sector import SectorSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="Tech sector outperforming.")
    out = SectorSection().run(_ctx())
    assert out.name == "sector"
    assert "Sector and Peer Comparison" in out.markdown
    assert "Tech sector outperforming" in out.markdown
    assert out.skipped is False


def test_registered_in_section_registry():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.sector import SectorSection
    assert "sector" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["sector"], SectorSection)
