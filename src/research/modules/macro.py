"""Macro module — SPY trailing return + regime label as narrative.

Phase 1 is objective-only (no Druckenmiller persona variant). Reads
SharedData.spy_prices (already fetched once at pipeline start), computes
trailing 20d return + regime label deterministically, and asks the LLM
for a 2-3 sentence narrative anchored on those numbers.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _MacroNarrative(BaseModel):
    narrative: str = Field(
        description="2-3 sentences describing the macro regime and its "
                    "relevance to this ticker. Reference the numbers."
    )


def _compute_macro(shared: SharedData) -> dict[str, float] | None:
    bars = sorted(shared.spy_prices, key=lambda p: p.time[:10])
    if len(bars) < 21:
        return None
    closes = [float(getattr(b, "adjusted_close", None) or b.close) for b in bars[-21:]]
    ret_20d = (closes[-1] / closes[0]) - 1.0
    regime = "up" if ret_20d > 0.01 else ("down" if ret_20d < -0.01 else "chop")
    return {
        "spy_return_20d": round(ret_20d, 4),
        "regime_code": 1.0 if regime == "up" else (-1.0 if regime == "down" else 0.0),
    }


class MacroModule(AnalysisModule):
    name = "macro"
    supports_personas: list[str] = []  # Phase 2 may add ["druckenmiller"]

    def run(
        self,
        request: ResearchRequest,
        persona: str | None,
        shared_data: SharedData,
    ) -> ModuleResult:
        persona = self._coerce_persona(persona)  # None always in Phase 1

        metrics = _compute_macro(shared_data)
        if metrics is None:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="SPY price history insufficient",
            )

        regime = {1.0: "up", -1.0: "down", 0.0: "chop"}[metrics["regime_code"]]
        ret_pct = metrics["spy_return_20d"] * 100

        prompt = (
            f"Macro regime snapshot for {shared_data.scan_date}:\n"
            f"  SPY trailing 20-day return: {ret_pct:+.2f}%\n"
            f"  Regime label: {regime}\n"
            f"\nTicker under analysis: {request.ticker}.\n"
            f"Holding status: {request.holding_status}.\n"
            f"\nWrite a 2-3 sentence objective summary of the macro context\n"
            f"and its implications for a position in {request.ticker}. Cite\n"
            f"the numbers above. Do not predict; describe."
        )

        try:
            narrative = call_research_llm(
                prompt, _MacroNarrative,
                default_factory=lambda: _MacroNarrative(
                    narrative=f"SPY {ret_pct:+.2f}% over 20d ({regime} regime)."
                ),
            )
        except Exception as e:
            logger.warning("macro module LLM failed: %s", e)
            narrative = _MacroNarrative(
                narrative=f"SPY {ret_pct:+.2f}% over 20d ({regime} regime).",
            )

        return ModuleResult(
            module_name=self.name,
            persona_used=None,
            markdown=narrative.narrative,
            key_metrics=metrics,
        )
