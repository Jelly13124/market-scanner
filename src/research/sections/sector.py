"""Sector section - runs the skill's sector module prompt."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(description="markdown body for Sector and Peer Comparison section")


_SYSTEM_PROMPT = load_prompt("modules/sector.md")


class SectorSection(Section):
    name = "sector"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        sector = (ctx.shared.company_facts or {}).get("sector", "Unknown")
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + f"Sector: {sector}\n"
            + f"Sector ETF bars: {len(ctx.shared.sector_etf_prices)}\n"
            + f"SPY bars: {len(ctx.shared.spy_prices)}\n"
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 280-450 word Sector and Peer Comparison per the spec. "
            + "Output as 'narrative' field - markdown WITHOUT the heading. "
            + "Cover sector ETF proxy, 20-day relative strength vs SPY and "
            + "sector, peer growth/margin/valuation comparison qualitatively, "
            + "sector catalysts, and premium/discount justification."
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative, markdown_heading="## Sector and Peer Comparison",
        )


SECTION_REGISTRY["sector"] = SectorSection()
