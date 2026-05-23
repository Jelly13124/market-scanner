"""Shared LLM section runner — handles persona prepend + try/except."""

from unittest.mock import patch
from pydantic import BaseModel
from src.research.models import AnalyzeRequest, SectionPayload
from src.research.sections.base import SectionContext
from src.research.sections._llm_runner import run_llm_section
from src.research.shared_data import SharedData


class _Narr(BaseModel):
    narrative: str


def _ctx(persona=None):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=None, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=bool(persona),
    )
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={"sector": "Tech"},
        sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=persona, prior={})


class TestRunLlmSection:
    @patch("src.research.sections._llm_runner.call_research_llm")
    def test_returns_payload_with_markdown(self, mock_llm):
        mock_llm.return_value = _Narr(narrative="Macro is up.")
        out = run_llm_section(
            section_name="macro",
            ctx=_ctx(),
            prompt="Write macro summary.",
            output_model=_Narr,
            markdown_heading="## Macro Regime",
        )
        assert isinstance(out, SectionPayload)
        assert out.name == "macro"
        assert "Macro is up." in out.markdown
        assert "## Macro Regime" in out.markdown

    @patch("src.research.sections._llm_runner.call_research_llm")
    def test_persona_recorded(self, mock_llm):
        mock_llm.return_value = _Narr(narrative="ok")
        out = run_llm_section(
            section_name="valuation", ctx=_ctx(persona="buffett"),
            prompt="Write valuation.", output_model=_Narr,
            markdown_heading="## Valuation",
        )
        assert out.persona_used == "buffett"

    @patch("src.research.sections._llm_runner.call_research_llm")
    def test_returns_skipped_on_exception(self, mock_llm):
        mock_llm.side_effect = Exception("boom")
        out = run_llm_section(
            section_name="macro", ctx=_ctx(),
            prompt="x", output_model=_Narr, markdown_heading="## M",
        )
        assert out.skipped is True
        assert "boom" in (out.skip_reason or "")
