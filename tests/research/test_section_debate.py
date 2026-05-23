from unittest.mock import patch
from src.research.models import AnalyzeRequest, SectionPayload, ModuleResult
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx(use_personas=True, with_assignments=None):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=use_personas,
    )
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={"sector": "Tech"}, sector_etf_prices=[], spy_prices=[],
    )
    prior = {}
    if with_assignments is not None:
        prior["_persona_assignments"] = SectionPayload(
            name="_persona_assignments", markdown="",
            structured={"debate": with_assignments},
            skipped=False, persona_used=None,
        )
    return SectionContext(request=req, shared=shared, persona=None, prior=prior)


def test_skipped_when_personas_off():
    from src.research.sections.debate import DebateSection
    out = DebateSection().run(_ctx(use_personas=False))
    assert out.skipped is True
    assert "personas disabled" in out.markdown.lower()
    assert "use_personas" in (out.skip_reason or "").lower()


def test_skipped_when_no_assignments():
    from src.research.sections.debate import DebateSection
    out = DebateSection().run(_ctx(with_assignments=None))
    assert out.skipped is True


def test_skipped_when_only_one_persona():
    from src.research.sections.debate import DebateSection
    out = DebateSection().run(_ctx(with_assignments=["buffett"]))
    assert out.skipped is True


@patch("src.research.sections.debate.run_debate")
def test_runs_debate_when_two_personas(mock_rd):
    from src.research.sections.debate import DebateSection
    mock_rd.return_value = ModuleResult(
        module_name="debate", persona_used="wood+burry",
        markdown="**Wood:** ...\n**Burry:** ...", key_metrics={},
    )
    out = DebateSection().run(_ctx(with_assignments=["wood", "burry"]))
    assert out.skipped is False
    assert "Debate Summary" in out.markdown
    assert "Wood" in out.markdown


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.debate import DebateSection
    assert "debate" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["debate"], DebateSection)
