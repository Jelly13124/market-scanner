"""Valuation - prose section (450-700 words).

Packs PE/PB/PS/EV-EBITDA/FCF-yield from ctx.shared.financials[0] into
the prompt. Persona-aware: buffett/graham/munger/fisher shade the
valuation lens per Phase 2.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(
        description="450-700 word markdown body covering relative + "
        "intrinsic valuation, scenarios, margin of safety, target range."
    )


_SYSTEM_PROMPT = load_prompt("modules/valuation.md")


def _metrics_block(ctx: SectionContext) -> str:
    if not ctx.shared.financials:
        return "No valuation metrics available.\n"
    latest = ctx.shared.financials[0]
    keys = (
        "price_to_earnings_ratio", "price_to_book_ratio",
        "price_to_sales_ratio", "enterprise_value_to_ebitda_ratio",
        "free_cash_flow_yield",
    )
    lines = []
    for k in keys:
        try:
            v = getattr(latest, k, None)
        except Exception:
            v = None
        if v is None:
            continue
        try:
            lines.append(f"  {k}: {float(v):.4f}")
        except (TypeError, ValueError):
            lines.append(f"  {k}: {v}")
    if not lines:
        return "No valuation metrics available.\n"
    return "Latest valuation metrics:\n" + "\n".join(lines) + "\n"


class ValuationSection(Section):
    name = "valuation"
    supports_personas = ["buffett", "graham", "munger", "fisher"]

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + _metrics_block(ctx)
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 450-700 word Valuation Analysis per spec. "
            + "Output as 'narrative' field, markdown WITHOUT the heading. "
            + "Cover: current market inputs, relative valuation, "
            + "intrinsic/scenario math, bear/base/bull assumptions, "
            + "sensitivity, margin of safety, target range + confidence."
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative,
            markdown_heading="## Valuation Analysis",
        )


SECTION_REGISTRY["valuation"] = ValuationSection()
