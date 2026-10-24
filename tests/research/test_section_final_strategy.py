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
def test_emits_final_strategy_section(mock_llm):
    from src.research.sections.final_strategy import FinalStrategySection, _Narrative
    mock_llm.return_value = _Narrative(
        narrative="### Short-term\nbuy dips.\n### Medium-term\nhold.\n### Long-term\nadd."
    )
    out = FinalStrategySection().run(_ctx())
    assert out.name == "final_strategy"
    assert "Final Conditional Strategy" in out.markdown
    assert "Short-term" in out.markdown
    assert out.skipped is False


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.final_strategy import FinalStrategySection
    assert "final_strategy" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["final_strategy"], FinalStrategySection)
