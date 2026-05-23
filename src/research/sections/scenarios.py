"""Scenarios - bear/base/bull target ranges + assumptions table.
Reads ctx.prior['valuation'] when present to base scenarios on
the valuation work."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from src.research.llm import call_research_llm
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext

logger = logging.getLogger(__name__)


class _Scenario(BaseModel):
    target_range: str
    time_horizon: str
    key_assumptions: str
    confidence: Literal["high", "medium", "low"]
    invalidation: str


class _ScenariosOut(BaseModel):
    bear: _Scenario
    base: _Scenario
    bull: _Scenario


_TASK_INSTRUCTION = (
    "Produce bear / base / bull scenarios for this ticker. Each: "
    "target_range (e.g. '$140-160'), time_horizon (e.g. '3-6 months'), "
    "key_assumptions (one paragraph), confidence (high/medium/low), "
    "invalidation (what would prove this scenario wrong)."
)


def _valuation_context(ctx: SectionContext) -> str:
    val = ctx.prior.get("valuation")
    if val and not val.skipped:
        return val.markdown[:1500]
    return "(valuation section not yet available)"


class ScenariosSection(Section):
    name = "scenarios"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        prompt = (
            _TASK_INSTRUCTION
            + f"\n\nTicker: {ctx.request.ticker}\n\n"
            + "--- VALUATION CONTEXT ---\n"
            + _valuation_context(ctx)
        )
        try:
            out = call_research_llm(
                prompt, _ScenariosOut,
                default_factory=lambda: _ScenariosOut(
                    bear=_Scenario(target_range="n/a", time_horizon="n/a",
                                   key_assumptions="LLM failed", confidence="low",
                                   invalidation="n/a"),
                    base=_Scenario(target_range="n/a", time_horizon="n/a",
                                   key_assumptions="LLM failed", confidence="low",
                                   invalidation="n/a"),
                    bull=_Scenario(target_range="n/a", time_horizon="n/a",
                                   key_assumptions="LLM failed", confidence="low",
                                   invalidation="n/a"),
                ),
            )
        except Exception as e:
            logger.exception("scenarios raised: %s", e)
            return SectionPayload(
                name=self.name,
                markdown="## Bear/Base/Bull Scenarios\n\n_unavailable_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=str(e),
            )

        rows = [
            "| Scenario | Target Range | Time Horizon | Key Assumptions | Confidence | Invalidation |",
            "|---|---|---|---|---|---|",
        ]
        for label, sc in (("Bear", out.bear), ("Base", out.base), ("Bull", out.bull)):
            rows.append(
                f"| {label} | {sc.target_range} | {sc.time_horizon} | "
                f"{sc.key_assumptions} | {sc.confidence} | {sc.invalidation} |"
            )
        md = "## Bear/Base/Bull Scenarios\n\n" + "\n".join(rows) + "\n"
        return SectionPayload(
            name=self.name, markdown=md,
            structured={
                "bear": out.bear.model_dump(),
                "base": out.base.model_dump(),
                "bull": out.bull.model_dump(),
            },
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["scenarios"] = ScenariosSection()
