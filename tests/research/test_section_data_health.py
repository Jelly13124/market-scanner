from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.sections.data_health import DataHealthSection
from src.research.shared_data import SharedData


def _req():
    return AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=False,
    )


def _shared(**overrides):
    base = dict(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[1, 2, 3], financials=[1], insider_trades=[1],
        news=[1], analyst_actions=[1], analyst_targets={"target": 200},
        earnings_history=[1], company_facts={"sector": "Tech"},
        sector_etf_prices=[1, 2], spy_prices=[1, 2],
    )
    base.update(overrides)
    return SharedData(**base)


def test_emits_data_health_section():
    ctx = SectionContext(request=_req(), shared=_shared(), persona=None, prior={})
    out = DataHealthSection().run(ctx)
    assert out.name == "data_health"
    assert out.skipped is False
    # Table-style markdown with every required row
    for row in ("Quote", "Daily chart", "Financials", "Macro", "Sector", "News"):
        assert row in out.markdown


def test_marks_missing_inputs():
    ctx = SectionContext(request=_req(), shared=_shared(prices=[], news=[]), persona=None, prior={})
    out = DataHealthSection().run(ctx)
    # missing prices/news should be flagged
    assert "missing" in out.markdown.lower() or "unavailable" in out.markdown.lower()


def test_registered_in_section_registry():
    from src.research.sections import SECTION_REGISTRY
    assert "data_health" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["data_health"], DataHealthSection)
