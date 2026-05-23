"""ExecutiveSummary - bullet decision summary. Reads conviction.total_score
from prior section (the second layer of the always-75 fix - the LLM
never independently invents the score)."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext

logger = logging.getLogger(__name__)


class _ExecOut(BaseModel):
    overall_view: str = Field(description="1-2 sentence decision summary")
    main_bullish: str
    main_bearish: str
    target_range: str = Field(description="e.g. '$80 / $115 / $160' bear/base/bull")
    strategy_type: str = Field(description="e.g. 'value swing trade'")
    confidence_qualitative: Literal["high", "medium", "low"]
    key_invalidation: str


def _prior_brief(ctx: SectionContext) -> str:
    parts = []
    for k in ("evidence_ledger", "scenarios"):
        p = ctx.prior.get(k)
        if p and not p.skipped and p.markdown:
            parts.append(f"### {k}\n{p.markdown[:800]}")
    return "\n\n".join(parts) or "(no prior content)"


def _conviction_score(ctx: SectionContext) -> int | None:
    p = ctx.prior.get("conviction")
    if not p or p.skipped or not isinstance(p.structured, dict):
        return None
    return p.structured.get("total_score")


_TASK_INSTRUCTION = (
    "Write the Executive Summary as a bullet list. Output: overall_view, "
    "main_bullish, main_bearish, target_range (bear/base/bull dollar "
    "ranges), strategy_type, confidence_qualitative (high/medium/low), "
    "key_invalidation. Do NOT invent a numeric score - the score is "
    "pulled from the prior conviction section by the runner."
)


class ExecutiveSummarySection(Section):
    name = "executive_summary"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        prompt = (
            _TASK_INSTRUCTION
            + f"\n\nTicker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n\n"
            + "--- PRIOR ---\n"
            + _prior_brief(ctx)
        )
        try:
            out = call_research_llm(
                prompt, _ExecOut,
                default_factory=lambda: _ExecOut(
                    overall_view="LLM failed; no summary.",
                    main_bullish="n/a", main_bearish="n/a",
                    target_range="n/a", strategy_type="n/a",
                    confidence_qualitative="low", key_invalidation="n/a",
                ),
            )
        except Exception as e:
            logger.exception("executive_summary raised: %s", e)
            return SectionPayload(
                name=self.name,
                markdown="## Executive Summary\n\n_unavailable_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=str(e),
            )

        score = _conviction_score(ctx)
        score_line = f"- **Score:** {score}/100\n" if score is not None else ""

        md = (
            "## Executive Summary\n\n"
            f"- **Overall view:** {out.overall_view}\n"
            f"- **Main bullish argument:** {out.main_bullish}\n"
            f"- **Main bearish risk:** {out.main_bearish}\n"
            f"- **Bear/base/bull target range:** {out.target_range}\n"
            f"- **Strategy type:** {out.strategy_type}\n"
            f"- **Confidence:** {out.confidence_qualitative}\n"
            f"- **Key invalidation:** {out.key_invalidation}\n"
            f"{score_line}"
        )
        return SectionPayload(
            name=self.name, markdown=md,
            structured={**out.model_dump(), "score_from_conviction": score},
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["executive_summary"] = ExecutiveSummarySection()
