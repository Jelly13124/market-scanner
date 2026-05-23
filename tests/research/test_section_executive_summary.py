from unittest.mock import patch
from src.research.models import AnalyzeRequest, SectionPayload
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx(with_conviction_score=None):
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
    prior = {}
    if with_conviction_score is not None:
        prior["conviction"] = SectionPayload(
            name="conviction", markdown="x",
            structured={"total_score": with_conviction_score, "categories": [],
                        "weights": [], "risk_profile": "balanced"},
            skipped=False, persona_used=None,
        )
    return SectionContext(request=req, shared=shared, persona=None, prior=prior)


@patch("src.research.sections.executive_summary.call_research_llm")
def test_emits_bullet_summary(mock_llm):
    from src.research.sections.executive_summary import (
        ExecutiveSummarySection, _ExecOut)
    mock_llm.return_value = _ExecOut(
        overall_view="bullish", main_bullish="ai", main_bearish="comp",
        target_range="$100/120/140", strategy_type="swing",
        confidence_qualitative="medium", key_invalidation="earnings miss",
    )
    out = ExecutiveSummarySection().run(_ctx())
    assert out.name == "executive_summary"
    assert "Overall view" in out.markdown
    assert "bullish" in out.markdown


@patch("src.research.sections.executive_summary.call_research_llm")
def test_score_pulled_from_conviction_not_llm(mock_llm):
    """Key fix: the score in the summary comes from prior conviction,
    NOT from the LLM (the _ExecOut model has no score field)."""
    from src.research.sections.executive_summary import (
        ExecutiveSummarySection, _ExecOut)
    mock_llm.return_value = _ExecOut(
        overall_view="x", main_bullish="x", main_bearish="x",
        target_range="x", strategy_type="x",
        confidence_qualitative="medium", key_invalidation="x",
    )
    out = ExecutiveSummarySection().run(_ctx(with_conviction_score=42))
    assert "**Score:** 42/100" in out.markdown
    assert out.structured["score_from_conviction"] == 42


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.executive_summary import ExecutiveSummarySection
    assert "executive_summary" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["executive_summary"], ExecutiveSummarySection)
