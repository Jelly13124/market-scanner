from unittest.mock import patch
from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx(risk="balanced"):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance=risk, use_personas=False,
    )
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=None, prior={})


@patch("src.research.sections.conviction.call_research_llm")
def test_total_score_is_weighted_sum_not_llm(mock_llm):
    """The always-75 fix: total_score must be sum(weight*score/100), NOT
    a single LLM-supplied number."""
    from src.research.sections.conviction import (
        ConvictionSection, _ConvictionOut, _CategoryScore, _CATEGORIES, _WEIGHTS)
    # All categories score 80; balanced weights = (15,25,20,15,15,10) → sum=100
    # Expected: 80 * 100 / 100 = 80
    cats = [_CategoryScore(name=c, score=80, rationale="x") for c in _CATEGORIES]
    mock_llm.return_value = _ConvictionOut(categories=cats)
    out = ConvictionSection().run(_ctx(risk="balanced"))
    assert out.structured["total_score"] == 80, \
        f"expected 80 (weighted sum), got {out.structured['total_score']}"
    assert "Score: 80/100" in out.markdown


@patch("src.research.sections.conviction.call_research_llm")
def test_score_varies_by_category_scores(mock_llm):
    """If LLM scores differ per category, total reflects them."""
    from src.research.sections.conviction import (
        ConvictionSection, _ConvictionOut, _CategoryScore, _CATEGORIES)
    # balanced weights: (15,25,20,15,15,10)
    # scores:          (100,100,0,0,0,0) → 100*15/100 + 100*25/100 = 40
    scores = [100, 100, 0, 0, 0, 0]
    cats = [_CategoryScore(name=c, score=s, rationale="x")
            for c, s in zip(_CATEGORIES, scores)]
    mock_llm.return_value = _ConvictionOut(categories=cats)
    out = ConvictionSection().run(_ctx(risk="balanced"))
    assert out.structured["total_score"] == 40


@patch("src.research.sections.conviction.call_research_llm")
def test_weights_swap_by_risk_profile(mock_llm):
    """conservative + aggressive use different weights."""
    from src.research.sections.conviction import (
        ConvictionSection, _ConvictionOut, _CategoryScore, _CATEGORIES)
    # All scores = 50 — total should equal 50 under any profile (since
    # weights sum to 100): 50 * 100 / 100 = 50
    cats = [_CategoryScore(name=c, score=50, rationale="x") for c in _CATEGORIES]
    mock_llm.return_value = _ConvictionOut(categories=cats)
    for profile in ("conservative", "balanced", "aggressive"):
        out = ConvictionSection().run(_ctx(risk=profile))
        assert out.structured["total_score"] == 50, \
            f"profile {profile}: expected 50, got {out.structured['total_score']}"
        assert out.structured["risk_profile"] == profile


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.conviction import ConvictionSection
    assert "conviction" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["conviction"], ConvictionSection)
