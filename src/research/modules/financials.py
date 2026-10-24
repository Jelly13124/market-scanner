"""Financials module — quarter-over-quarter trend in income / cash flow.

Reads from shared_data.earnings_history (list[EarningsRecord]) because
the absolute revenue / net_income / free_cash_flow live under
record.quarterly (EarningsData), NOT on FinancialMetrics which only
exposes ratios and growth percentages.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _FinancialsNarrative(BaseModel):
    narrative: str = Field(
        description="3-4 sentences on QoQ trend in revenue, net income, and FCF."
    )


def _f(getter, default=0.0):
    try:
        v = getter()
        return float(v) if v is not None else default
    except (AttributeError, TypeError, ValueError):
        return default


def _quarterly_field(record, attr: str, default: float = 0.0) -> float:
    """Read ``record.quarterly.<attr>`` defensively. EarningsRecord has
    ``quarterly: EarningsData | None``; access requires None guard before
    attribute lookup."""
    q = getattr(record, "quarterly", None)
    if q is None:
        return default
    return _f(lambda: getattr(q, attr), default)


class FinancialsModule(AnalysisModule):
    name = "financials"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        if not shared_data.earnings_history:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="No earnings history available",
            )

        # Filter records with a quarterly EarningsData payload (skip annual-only / blanks)
        series = [r for r in shared_data.earnings_history
                  if getattr(r, "quarterly", None) is not None][:4]

        if not series:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason="No quarterly earnings records in history",
            )

        rev = [_quarterly_field(r, "revenue") for r in series]
        ni = [_quarterly_field(r, "net_income") for r in series]
        fcf = [_quarterly_field(r, "free_cash_flow") for r in series]

        metrics = {
            "revenue_latest": rev[0] if rev else 0.0,
            "net_income_latest": ni[0] if ni else 0.0,
            "fcf_latest": fcf[0] if fcf else 0.0,
            "n_quarters": float(len(series)),
        }
        if len(series) >= 4 and rev[3] > 0:
            metrics["revenue_yoy_growth"] = round((rev[0] / rev[3]) - 1.0, 4)
        if len(series) >= 4 and ni[3] != 0:
            metrics["net_income_yoy_growth"] = round((ni[0] / ni[3]) - 1.0, 4)

        rows_md = "\n".join(
            f"  {getattr(record, 'report_period', '?')}: "
            f"revenue ${rev[i] / 1e9:.2f}B, "
            f"NI ${ni[i] / 1e9:.2f}B, FCF ${fcf[i] / 1e9:.2f}B"
            for i, record in enumerate(series)
        )
        prompt = (
            f"Recent quarterly financials for {request.ticker}:\n"
            f"{rows_md}\n"
            f"\nWrite 3-4 sentences objectively describing the QoQ trend\n"
            f"in revenue, net income, and free cash flow. Note any\n"
            f"acceleration or deceleration. Anchor every claim on a number\n"
            f"above. Do not predict."
        )
        narrative = call_research_llm(
            prompt, _FinancialsNarrative,
            default_factory=lambda: _FinancialsNarrative(
                narrative=(
                    f"Latest revenue ${rev[0] / 1e9:.2f}B, "
                    f"net income ${ni[0] / 1e9:.2f}B, FCF ${fcf[0] / 1e9:.2f}B."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
