from src.research.models import AnalyzeRequest, SectionPayload
from src.research.sections.base import SectionContext
from src.research.sections.missing_data import MissingDataSection
from src.research.shared_data import SharedData


def _ctx(prior=None):
    req = AnalyzeRequest(
        ticker="X", objective="general_research",
        position_budget_usd=None, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=False,
    )
    shared = SharedData(
        ticker="X", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=None, prior=prior or {})


def test_all_completed_no_table():
    out = MissingDataSection().run(_ctx())
    assert "All sections completed" in out.markdown
    assert out.structured["skipped_sections"] == []


def test_lists_skipped_sections():
    prior = {
        "macro": SectionPayload(name="macro", markdown="ok", structured=None,
                                skipped=False, persona_used=None),
        "valuation": SectionPayload(name="valuation", markdown="", structured=None,
                                    skipped=True, persona_used=None,
                                    skip_reason="LLM timeout"),
    }
    out = MissingDataSection().run(_ctx(prior=prior))
    assert "valuation" in out.markdown
    assert "LLM timeout" in out.markdown
    assert "macro" not in out.structured["skipped_sections"]
    assert "valuation" in out.structured["skipped_sections"]


def test_ignores_underscore_keys():
    """Magic keys like _persona_assignments must not appear."""
    prior = {
        "_persona_assignments": SectionPayload(
            name="_persona_assignments", markdown="",
            structured={}, skipped=False, persona_used=None,
        ),
    }
    out = MissingDataSection().run(_ctx(prior=prior))
    assert "_persona_assignments" not in out.markdown


def test_registered():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.missing_data import MissingDataSection
    assert "missing_data" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["missing_data"], MissingDataSection)
