"""Risk-position module — deterministic stop/target ladder from prior
valuation + technical module outputs.

Unlike the other modules, ``run()`` takes a ``prior_results`` kwarg.
The pipeline orchestrator passes the module_results dict so this
module can read ``valuation.key_metrics['fair_value_high']`` and
``technical.key_metrics['support']``. Synthesizer can override the
final TradePlan; this module's output is a *suggestion*.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _RiskNarrative(BaseModel):
    narrative: str = Field(
        description="2-4 sentences justifying the stop/target ladder."
    )


_RISK_PROFILES = {
    "conservative": {"stop_mult": 1.5, "target_mult": 1.5, "sizing_dampener": 0.6},
    "moderate":     {"stop_mult": 2.0, "target_mult": 2.0, "sizing_dampener": 1.0},
    "aggressive":   {"stop_mult": 3.0, "target_mult": 3.0, "sizing_dampener": 1.2},
}


class RiskPositionModule(AnalysisModule):
    name = "risk_position"
    # Phase 2 will add ["druckenmiller", "burry"]
    supports_personas: list[str] = []

    def run(
        self,
        request: ResearchRequest,
        persona: str | None,
        shared_data: SharedData,
        *,
        prior_results: dict[str, ModuleResult] | None = None,
    ) -> ModuleResult:
        persona = self._coerce_persona(persona)
        prior_results = prior_results or {}

        valuation = prior_results.get("valuation")
        technical = prior_results.get("technical")
        if (valuation is None or valuation.skipped
                or technical is None or technical.skipped):
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason="risk_position needs valuation + technical outputs",
            )

        price = float(technical.key_metrics.get("current_price", 0))
        support = float(technical.key_metrics.get("support", 0))
        fv_high = float(valuation.key_metrics.get("fair_value_high", 0))
        if price <= 0 or support <= 0 or fv_high <= 0:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="Missing price / support / fair_value",
            )

        profile = _RISK_PROFILES[request.risk_tolerance]
        # Stop: scale gap below support by stop_mult
        stop_distance = (price - support) * profile["stop_mult"]
        stop_price = round(price - stop_distance, 2)
        # Target: scale upside to fair_value_high by target_mult, capped at fv_high
        upside = (fv_high - price) * profile["target_mult"]
        target_price = round(min(price + upside, fv_high * 1.10), 2)
        sizing = round(
            request.target_position_pct * profile["sizing_dampener"], 4,
        )
        sizing = min(sizing, request.target_position_pct)

        metrics = {
            "entry_price": round(price, 2),
            "stop_price": stop_price,
            "target_price": target_price,
            "sizing_pct": sizing,
            "risk_reward_ratio": round((target_price - price) / max(price - stop_price, 1e-6), 2),
            "horizon_days": 30.0,
        }
        prompt = (
            f"Suggested trade plan for {request.ticker} "
            f"(risk tolerance: {request.risk_tolerance}):\n"
            f"  Entry: ${price:.2f}\n"
            f"  Stop:  ${stop_price:.2f}\n"
            f"  Target: ${target_price:.2f}\n"
            f"  R:R   : {metrics['risk_reward_ratio']:.2f}\n"
            f"  Sizing: {sizing * 100:.2f}% of portfolio\n"
            f"\nWrite 2-4 sentences justifying this plan given the support\n"
            f"(${support:.2f}) and fair-value upper bound (${fv_high:.2f}).\n"
            f"Note the risk if stopped out."
        )
        narrative = call_research_llm(
            prompt, _RiskNarrative,
            default_factory=lambda: _RiskNarrative(
                narrative=(
                    f"Stop ${stop_price:.2f}, target ${target_price:.2f}, "
                    f"R:R {metrics['risk_reward_ratio']:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
