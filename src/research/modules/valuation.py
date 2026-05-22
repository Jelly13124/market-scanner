"""Valuation module — simple DCF + multiple-based fair value range.

Reads per-share metrics from FinancialMetrics (earnings_per_share,
free_cash_flow_per_share) plus weighted_average_shares from
company_facts. PE multiple + DCF perpetuity blended into a fair value
range; LLM compares range to current price.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _ValuationNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences on fair value range vs current price."
    )


def _current_price(shared: SharedData) -> float | None:
    if not shared.prices:
        return None
    bars = sorted(shared.prices, key=lambda b: b.time[:10])
    last = bars[-1]
    return float(getattr(last, "adjusted_close", None) or last.close)


def _fair_value_range(
    eps_ttm: float, fcf_per_share: float,
    growth_rate: float = 0.10, discount_rate: float = 0.10,
) -> tuple[float, float] | None:
    """Two anchor methods on per-share basis:
      * PE multiple: low = eps * 15, high = eps * 25
      * DCF (perpetuity): per-share-FCF * (1+g) / (r-g), at g-2pp / g+2pp band
    Returns (low, high) blend.
    """
    pe_low = eps_ttm * 15 if eps_ttm > 0 else None
    pe_high = eps_ttm * 25 if eps_ttm > 0 else None

    dcf_low = dcf_high = None
    if fcf_per_share > 0:
        g_lo = max(growth_rate - 0.02, 0.0)
        g_hi = min(growth_rate + 0.02, discount_rate - 0.005)
        if discount_rate - g_lo > 0:
            dcf_low = fcf_per_share * (1 + g_lo) / (discount_rate - g_lo)
        if discount_rate - g_hi > 0:
            dcf_high = fcf_per_share * (1 + g_hi) / (discount_rate - g_hi)

    candidates_low = [v for v in (pe_low, dcf_low) if v is not None and v > 0]
    candidates_high = [v for v in (pe_high, dcf_high) if v is not None and v > 0]
    if not candidates_low or not candidates_high:
        return None
    return (min(candidates_low), max(candidates_high))


class ValuationModule(AnalysisModule):
    name = "valuation"
    # Phase 2 will add ["buffett", "graham", "munger", "fisher"]
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        if not shared_data.financials:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="No financials for valuation",
            )

        latest = shared_data.financials[0]
        eps = float(getattr(latest, "earnings_per_share", 0.0) or 0.0)
        fcf_per_share = float(getattr(latest, "free_cash_flow_per_share", 0.0) or 0.0)
        if eps <= 0 and fcf_per_share <= 0:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="Neither EPS nor FCF/share positive",
            )

        rng = _fair_value_range(eps, fcf_per_share)
        price = _current_price(shared_data) or 0.0
        if rng is None:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="Fair value range not computable",
            )

        metrics = {
            "current_price": round(price, 2),
            "fair_value_low": round(rng[0], 2),
            "fair_value_high": round(rng[1], 2),
            "eps_ttm": round(eps, 2),
            "fcf_per_share": round(fcf_per_share, 2),
        }
        prompt = (
            f"Valuation snapshot for {request.ticker}:\n"
            f"  Current price: ${price:.2f}\n"
            f"  Fair value range: ${rng[0]:.2f} - ${rng[1]:.2f}\n"
            f"  EPS (TTM): ${eps:.2f}\n"
            f"  FCF per share: ${fcf_per_share:.2f}\n"
            f"\nWrite 3-5 sentences objectively comparing the current price\n"
            f"to the fair value range. Identify whether the stock looks\n"
            f"cheap, fair, or stretched, and by how much. Do not predict\n"
            f"future price; describe the gap."
        )
        narrative = call_research_llm(
            prompt, _ValuationNarrative,
            default_factory=lambda: _ValuationNarrative(
                narrative=(
                    f"Price ${price:.2f}; fair value range "
                    f"${rng[0]:.2f}-${rng[1]:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
