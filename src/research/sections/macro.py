"""Macro section - runs the skill's macro module prompt."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(description="markdown body for the Macro Regime section")


_SYSTEM_PROMPT = load_prompt("modules/macro.md")


class MacroSection(Section):
    name = "macro"
    supports_personas = ["druckenmiller"]

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + f"SPY bars available: {len(ctx.shared.spy_prices)}\n"
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 250-400 word Macro Regime section per the spec above. "
            + "Output as the 'narrative' field - markdown body WITHOUT the "
            + "heading (the runner adds '## Macro Regime' for you). Reference "
            + "SPY trend, rate regime, liquidity, and the implication for "
            + "valuation multiples and stop width on this ticker."
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative, markdown_heading="## Macro Regime",
        )


SECTION_REGISTRY["macro"] = MacroSection()
