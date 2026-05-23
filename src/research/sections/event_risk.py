"""EventRisk - upcoming earnings + macro events + options IV considerations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext


class _Narrative(BaseModel):
    narrative: str = Field(description="150-300 word event risk section")


_TASK = (
    "Write a 150-300 word Event Risk Check. Output as 'narrative' field, "
    "markdown WITHOUT heading. Cover: upcoming earnings date and historical "
    "post-earnings reaction tendencies, macro events inside the relevant "
    "trading window, company-specific events (FDA, regulatory, contracts), "
    "options IV / gap-risk notes, and the effect on confidence."
)


class EventRiskSection(Section):
    name = "event_risk"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        earnings_count = len(ctx.shared.earnings_history or [])
        prompt = (
            _TASK
            + f"\n\nTicker: {ctx.request.ticker}\n"
            + f"Risk tolerance: {ctx.request.risk_tolerance}\n"
            + f"Earnings records available: {earnings_count}\n"
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=prompt,
            output_model=_Narrative, markdown_heading="## Event Risk Check",
        )


SECTION_REGISTRY["event_risk"] = EventRiskSection()
