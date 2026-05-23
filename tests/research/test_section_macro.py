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
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={"sector": "Tech"},
        sector_etf_prices=[], spy_prices=[100, 101, 102],
    )
    return SectionContext(request=req, shared=shared, persona=persona, prior={})


@patch("src.research.sections._llm_runner.call_research_llm")
def test_emits_macro_section(mock_llm):
    from src.research.sections.macro import MacroSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="Macro is bullish.")
    out = MacroSection().run(_ctx())
    assert out.name == "macro"
    assert "Macro Regime" in out.markdown
    assert "Macro is bullish" in out.markdown
    assert out.skipped is False


@patch("src.research.sections._llm_runner.call_research_llm")
def test_supports_druckenmiller_persona(mock_llm):
    from src.research.sections.macro import MacroSection, _Narrative
    mock_llm.return_value = _Narrative(narrative="Fed-aware.")
    out = MacroSection().run(_ctx(persona="druckenmiller"))
    assert out.persona_used == "druckenmiller"


def test_registered_in_section_registry():
    from src.research.sections import SECTION_REGISTRY
    from src.research.sections.macro import MacroSection
    assert "macro" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["macro"], MacroSection)
