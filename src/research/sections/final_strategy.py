"""FinalStrategy - short/medium/long-term plan + watch levels + monitoring."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext


class _Narrative(BaseModel):
    narrative: str = Field(
        description="280-450 word section with ### Short-term, "
        "### Medium-term, ### Long-term subsections"
    )


_TASK = (
    "Write a 280-450 word Final Conditional Strategy. Output as "
    "'narrative' field, markdown WITHOUT top heading. Use ### "
    "subsections: Short-term, Medium-term, Long-term. End with: "
    "watch levels, stop/invalidation logic, what would change the "
    "view, and 3-5 monitoring items."
)


def _prior_brief(ctx: SectionContext) -> str:
    parts = []
    for k in ("evidence_ledger", "scenarios", "conviction", "risk_position"):
        p = ctx.prior.get(k)
        if p and not p.skipped and p.markdown:
            parts.append(f"### {k}\n{p.markdown[:600]}")
    return "\n\n".join(parts) or "(no prior content)"


class FinalStrategySection(Section):
    name = "final_strategy"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        prompt = (
            _TASK
            + f"\n\nTicker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + f"Already holds: {ctx.request.already_holds}\n\n"
            + "--- PRIOR ---\n"
            + _prior_brief(ctx)
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=prompt,
            output_model=_Narrative,
            markdown_heading="## Final Conditional Strategy",
        )


SECTION_REGISTRY["final_strategy"] = FinalStrategySection()
