"""Synthesizer — compiles module outputs into a coherent report + TradePlan.

One LLM call. Prompt contains the ResearchRequest framing
(holding_status, risk_tolerance, report_goal) plus every non-skipped
module's markdown. LLM returns a structured object with the report
narrative and the TradePlan fields.

The synthesizer does NOT see the BacktestSummary — that's computed
after it. Keeps the LLM from tuning the plan to historical sample
results.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest, TradePlan

logger = logging.getLogger(__name__)


_GOAL_FRAMING = {
    "new_entry": (
        "User is evaluating a NEW position. Emphasize entry rationale, "
        "valuation gap, near-term catalysts. Plan should be actionable now."
    ),
    "hold_review": (
        "User already HOLDS this. Emphasize thesis check, catalysts since "
        "last review, exit signposts. Plan can be hold/trim/add."
    ),
    "exit_decision": (
        "User is considering an EXIT. Emphasize bear case strength, what "
        "would change the mind. Plan can be hold/trim/exit."
    ),
    "general_research": (
        "Balanced research, no specific action bias. Plan should reflect "
        "the strongest evidence direction or stand_aside."
    ),
}


class _SynthOutput(BaseModel):
    """LLM output: report narrative + flat TradePlan fields."""

    report_markdown: str = Field(
        description="800-1500 word markdown report. Use headings for sections."
    )
    direction: Literal["long", "short", "stand_aside"]
    entry_price: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    horizon_days: int = 0
    sizing_pct: float = 0.0
    confidence: int = Field(ge=0, le=100, default=0)
    rationale: str = Field(description="1-2 sentence plan summary.")


def synthesize(
    request: ResearchRequest,
    module_results: dict[str, ModuleResult],
) -> tuple[str, TradePlan]:
    """Run one LLM call to produce report + TradePlan."""
    framing = _GOAL_FRAMING.get(request.report_goal, _GOAL_FRAMING["general_research"])

    sections = []
    for name, result in module_results.items():
        if result.skipped:
            continue
        if not result.markdown.strip():
            continue
        sections.append(f"### {name}\n{result.markdown.strip()}\n")
    sections_block = "\n".join(sections) if sections else "(no module produced content)"

    prompt = (
        f"You are an institutional research analyst writing a single-ticker "
        f"report for {request.ticker}.\n\n"
        f"Position context:\n"
        f"  Holding status: {request.holding_status}\n"
        f"  Target position size: {request.target_position_pct * 100:.2f}% of portfolio\n"
        f"  Risk tolerance: {request.risk_tolerance}\n"
        f"  Report goal: {request.report_goal}\n\n"
        f"Framing instruction: {framing}\n\n"
        f"--- ANALYTICAL MODULE OUTPUTS ---\n\n"
        f"{sections_block}\n\n"
        f"--- YOUR TASK ---\n\n"
        f"Produce TWO things:\n\n"
        f"1. A markdown report (800-1500 words) synthesizing the modules "
        f"into one coherent narrative. Use section headings. Anchor every "
        f"claim on a number from the module outputs.\n\n"
        f"2. A single-shot trade plan: direction (long/short/stand_aside), "
        f"entry_price, target_price, stop_price, horizon_days, sizing_pct "
        f"(<= target_position_size), confidence (0-100), rationale.\n\n"
        f"Choose direction=stand_aside when the bear case dominates and "
        f"the user is not already holding, OR when data is too thin to "
        f"justify a position. In that case set entry/target/stop to null, "
        f"horizon_days=0, sizing_pct=0.\n\n"
        f"Adjust stop tightness and target ambition to the user's risk "
        f"tolerance: conservative=tighter stops + closer targets; aggressive=wider."
    )

    out = call_research_llm(
        prompt, _SynthOutput,
        default_factory=lambda: _SynthOutput(
            report_markdown=f"# {request.ticker}\n\nReport synthesis failed.",
            direction="stand_aside", confidence=0,
            rationale="Synthesizer LLM failed; defaulting to stand_aside.",
        ),
    )

    if out.direction == "stand_aside":
        plan = TradePlan(
            direction="stand_aside", entry_price=None, target_price=None,
            stop_price=None, horizon_days=0, sizing_pct=0.0,
            confidence=out.confidence, rationale=out.rationale,
        )
    else:
        plan = TradePlan(
            direction=out.direction,
            entry_price=out.entry_price,
            target_price=out.target_price,
            stop_price=out.stop_price,
            horizon_days=out.horizon_days,
            sizing_pct=min(out.sizing_pct, request.target_position_pct),
            confidence=out.confidence,
            rationale=out.rationale,
        )
    return out.report_markdown, plan
