"""Technical - prose section (350-550 words).

Computes summary stats from ctx.shared.prices (last close, sma50/200,
52w high/low) and packs them into the prompt. Reserves a Backtest
Validation sub-section that the orchestrator (Task 15) fills.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(
        description="350-550 word markdown body. End with a single "
        "placeholder paragraph reserving the Backtest Validation slot."
    )


_SYSTEM_PROMPT = load_prompt("modules/technical.md")


def _tech_block(ctx: SectionContext) -> str:
    px = []
    for p in (ctx.shared.prices or []):
        c = p.get("close") if isinstance(p, dict) else getattr(p, "close", None)
        if c is not None:
            px.append(float(c))
    if not px:
        return "No price history available.\n"
    last = px[-1]
    sma50 = sum(px[-50:]) / min(50, len(px)) if len(px) >= 50 else None
    sma200 = sum(px[-200:]) / min(200, len(px)) if len(px) >= 200 else None
    hi52 = max(px[-252:]) if len(px) >= 5 else max(px)
    lo52 = min(px[-252:]) if len(px) >= 5 else min(px)
    lines = [
        f"  last_close: {last:.2f}",
        f"  sma50: {sma50:.2f}" if sma50 else "  sma50: n/a",
        f"  sma200: {sma200:.2f}" if sma200 else "  sma200: n/a",
        f"  52w_high: {hi52:.2f}",
        f"  52w_low: {lo52:.2f}",
        f"  bars_available: {len(px)}",
    ]
    return "Price snapshot:\n" + "\n".join(lines) + "\n"


class TechnicalSection(Section):
    name = "technical"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + _tech_block(ctx)
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 350-550 word Technical Analysis per spec. "
            + "Output as 'narrative' field, markdown WITHOUT the heading. "
            + "Cover: daily + weekly trend tables (qualitative if intraday "
            + "unavailable), support/resistance, breakout trigger, "
            + "stop/invalidation, ATR risk band, reward/risk. End with a "
            + "single placeholder paragraph: 'Backtest validation: see "
            + "sub-section below.' — the orchestrator (Task 15) appends a "
            + "Backtest Validation sub-section after your output."
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative,
            markdown_heading="## Technical Analysis",
        )


SECTION_REGISTRY["technical"] = TechnicalSection()
