"""Financials module — quarter-over-quarter trend in income / cash flow."""

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


class FinancialsModule(AnalysisModule):
    name = "financials"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        if not shared_data.financials:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="No financial_metrics history",
            )

        series = shared_data.financials[:4]  # most recent 4 quarters
        rev = [_f(lambda x=row: x.revenue) for row in series]
        ni = [_f(lambda x=row: x.net_income) for row in series]
        fcf = [_f(lambda x=row: x.free_cash_flow) for row in series]

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
            f"  {row.report_period}: revenue ${rev[i] / 1e9:.2f}B, "
            f"NI ${ni[i] / 1e9:.2f}B, FCF ${fcf[i] / 1e9:.2f}B"
            for i, row in enumerate(series)
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
