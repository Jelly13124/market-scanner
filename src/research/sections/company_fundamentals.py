"""CompanyFundamentals - DEEPEST SOP section (700-1100 words).

Reads latest financials from ctx.shared.financials[0] and packs the
metric values into the prompt so the LLM can anchor claims on real
numbers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(
        description="700-1100 word markdown body. Use ### subsections "
        "(Core investment question, Business and segment map, etc.)."
    )


_SYSTEM_PROMPT = load_prompt("modules/company_fundamentals.md")


def _metrics_block(ctx: SectionContext) -> str:
    if not ctx.shared.financials:
        return "No financial metrics available.\n"
    latest = ctx.shared.financials[0]
    keys = (
        "revenue_growth", "gross_margin", "operating_margin",
        "net_margin", "return_on_invested_capital",
        "free_cash_flow_yield", "debt_to_equity",
    )
    lines = []
    for k in keys:
        v = getattr(latest, k, None)
        if v is not None:
            try:
                lines.append(f"  {k}: {float(v):.4f}")
            except (TypeError, ValueError):
                lines.append(f"  {k}: {v}")
    if not lines:
        return "No financial metrics available.\n"
    return "Latest metrics:\n" + "\n".join(lines) + "\n"


class CompanyFundamentalsSection(Section):
    name = "company_fundamentals"
    supports_personas = ["buffett", "munger", "fisher"]

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + f"Sector: {(ctx.shared.company_facts or {}).get('sector', 'Unknown')}\n"
            + _metrics_block(ctx)
            + "\n\n--- YOUR TASK ---\n"
            + "Write the DEEPEST section of the report (700-1100 words). "
            + "Output as 'narrative' field - markdown WITHOUT the top "
            + "heading. Use ### subsections in this order: "
            + "Core investment question, Business and segment map, "
            + "Revenue model and unit economics, Industry structure, "
            + "Customer/segment/geography exposure, Moat and competitors, "
            + "Strategic catalysts, Management and capital allocation, "
            + "Financial translation (link metrics to valuation assumptions), "
            + "Thesis breakers and variant view, Evidence gaps and confidence. "
            + "Anchor every quantitative claim on the metrics above when "
            + "available; flag explicitly when reasoning is qualitative."
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative, markdown_heading="## Company Fundamentals",
        )


SECTION_REGISTRY["company_fundamentals"] = CompanyFundamentalsSection()
