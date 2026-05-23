"""RiskPosition - prose section (350-550 words).

Maps the user's request fields (budget, holdings, cost basis, risk
tolerance) into the prompt. References any prior Technical section so
stops/targets align with support/resistance. Persona-aware:
druckenmiller/burry per Phase 2.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(
        description="350-550 word markdown body. Concrete dollar sizing "
        "when budget given; hold/add/trim/exit framing if already_holds."
    )


_SYSTEM_PROMPT = load_prompt("modules/risk_position.md")


def _risk_context(ctx: SectionContext) -> str:
    r = ctx.request
    tech_note = ""
    tech = ctx.prior.get("technical")
    if tech and not tech.skipped:
        tech_note = (
            "  (technical section ran - stop/target levels should align "
            "with its support/resistance)\n"
        )
    return (
        f"Position budget: ${r.position_budget_usd if r.position_budget_usd else 'not specified'}\n"
        f"Already holds: {r.already_holds}\n"
        f"Cost basis: ${r.cost_basis_usd if r.cost_basis_usd else 'n/a'}\n"
        f"Risk tolerance: {r.risk_tolerance}\n"
        + tech_note
    )


class RiskPositionSection(Section):
    name = "risk_position"
    supports_personas = ["druckenmiller", "burry"]

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + _risk_context(ctx)
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 350-550 word Risk and Position Sizing section per "
            + "spec. Output as 'narrative' field. Compute CONCRETE dollar "
            + "sizing if budget given. Frame as hold/add/trim/exit (NOT "
            + "fresh entry) if already_holds. Map stop logic to "
            + "risk_tolerance: conservative ~<=10% drawdown, balanced "
            + "~10-20%, aggressive ~25%+. State the risk style assumption "
            + "explicitly at the top."
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative,
            markdown_heading="## Risk and Position Sizing",
        )


SECTION_REGISTRY["risk_position"] = RiskPositionSection()
