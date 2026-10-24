"""FinancialStatements - 2nd deepest SOP section (600-950 words).

Serializes last 4 quarters from ctx.shared.earnings_history (NOT
.financials - quarterly revenue/ni/fcf live on EarningsRecord.quarterly,
same gotcha as Phase 1 financials module).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(
        description="600-950 word markdown body. Include a trend table "
        "when data permits."
    )


_SYSTEM_PROMPT = load_prompt("modules/financial_statements.md")


def _earnings_block(ctx: SectionContext) -> str:
    rows = []
    for er in (ctx.shared.earnings_history or [])[:4]:
        q = getattr(er, "quarterly", None)
        if q is None:
            continue
        rows.append(
            f"  {getattr(er, 'period', '?')}: "
            f"rev={getattr(q, 'revenue', None)}, "
            f"ni={getattr(q, 'net_income', None)}, "
            f"fcf={getattr(q, 'free_cash_flow', None)}"
        )
    body = "\n".join(rows) if rows else "  (no quarterly earnings available)"
    return "Earnings history (newest first):\n" + body + "\n"


class FinancialStatementsSection(Section):
    name = "financial_statements"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + _earnings_block(ctx)
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 600-950 word Financial Statement Review per spec. "
            + "Output as 'narrative' field - markdown WITHOUT the top "
            + "heading. Cover: reporting period + sources, revenue/margin/"
            + "EPS trend, balance sheet + liquidity, cash-flow quality, "
            + "dilution/SBC, GAAP vs non-GAAP, guidance + transcript tone. "
            + "Include a markdown trend table when data permits."
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative,
            markdown_heading="## Financial Statement Review",
        )


SECTION_REGISTRY["financial_statements"] = FinancialStatementsSection()
