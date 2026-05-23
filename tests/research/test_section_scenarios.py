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


@patch("src.research.sections.scenarios.call_research_llm")
def test_emits_3_scenarios(mock_llm):
    from src.research.sections.scenarios import (
        ScenariosSection, _Scenario, _ScenariosOut)
    s = _Scenario(target_range="$100-110", time_horizon="3m",
                  key_assumptions="x", confidence="medium", invalidation="x")
    mock_llm.return_value = _ScenariosOut(bear=s, base=s, bull=s)
    out = ScenariosSection().run(_ctx())
    assert out.name == "scenarios"
    assert "Bear/Base/Bull Scenarios" in out.markdown
    assert "Bear" in out.markdown and "Base" in out.markdown and "Bull" in out.markdown
    assert isinstance(out.structured, dict)
    assert "bear" in out.structured and "base" in out.structured and "bull" in out.structured


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.scenarios import ScenariosSection
    assert "scenarios" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["scenarios"], ScenariosSection)
