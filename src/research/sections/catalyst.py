"""Near-term Catalysts section — scheduled/likely events that could move the stock.

A toggleable analysis module like macro/sector/etc.: the user can include or
exclude it per analyze run (it's in SECTION_ORDER, so it shows up in the
frontend section picker). Uses run_llm_section, so it inherits the per-user
api_keys, i18n heading, and persona plumbing for free.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext


class _Narrative(BaseModel):
    narrative: str = Field(description="markdown body for the Near-term Catalysts section")


_TASK = (
    "Analyze NEAR-TERM CATALYSTS (next ~1-2 quarters) for this ticker — scheduled "
    "or likely events that could move the stock, and how a position should treat "
    "each.\n\n"
    "Cover, where applicable:\n"
    "  - Earnings: the next report's approximate window + what the market will key on.\n"
    "  - Product / launch events, conferences, analyst or investor days.\n"
    "  - Regulatory / legal (FDA, antitrust, rulings), guidance updates.\n"
    "  - Index / corporate actions (additions, splits, buybacks, lockup expiries).\n"
    "  - Macro or sector prints that disproportionately hit THIS name.\n\n"
    "For each catalyst give: rough timing, direction/impact (bullish / bearish / "
    "two-sided), and a position implication (size into it / wait for it / hedge). "
    "Finish with the single most important catalyst to watch and the outcome that "
    "would invalidate the thesis. Be concrete, but if you are unsure of an exact "
    "date say 'approx' rather than inventing one. 250-400 words. Output as the "
    "'narrative' field — markdown WITHOUT the heading."
)


class CatalystSection(Section):
    name = "catalyst"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        sector = (ctx.shared.company_facts or {}).get("sector", "Unknown")
        prompt = (
            f"Ticker: {ctx.request.ticker}\n"
            f"Objective: {ctx.request.objective}\n"
            f"Sector: {sector}\n\n"
            "--- YOUR TASK ---\n" + _TASK
        )
        return run_llm_section(
            section_name=self.name,
            ctx=ctx,
            prompt=prompt,
            output_model=_Narrative,
            markdown_heading="## Near-term Catalysts",
        )


SECTION_REGISTRY["catalyst"] = CatalystSection()
