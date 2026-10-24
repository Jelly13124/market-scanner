"""Fundamentals module — moat / margins / capital efficiency."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _FundamentalsNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences on revenue growth, margin profile, "
                    "capital efficiency, and apparent moat."
    )


def _safe(getter, default=None):
    try:
        v = getter()
        return v if v is not None else default
    except (AttributeError, IndexError, TypeError):
        return default


class FundamentalsModule(AnalysisModule):
    name = "fundamentals"
    supports_personas: list[str] = ["buffett", "munger", "fisher"]

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        if not shared_data.financials:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="No financial_metrics available",
            )
        latest = shared_data.financials[0]

        metrics = {
            "revenue_growth": _safe(lambda: float(latest.revenue_growth), 0.0) or 0.0,
            "gross_margin": _safe(lambda: float(latest.gross_margin), 0.0) or 0.0,
            "operating_margin": _safe(lambda: float(latest.operating_margin), 0.0) or 0.0,
            "net_margin": _safe(lambda: float(latest.net_margin), 0.0) or 0.0,
            "roic": _safe(lambda: float(latest.return_on_invested_capital), 0.0) or 0.0,
            "fcf_margin": _safe(lambda: float(latest.free_cash_flow_margin), 0.0) or 0.0,
            "debt_to_equity": _safe(lambda: float(latest.debt_to_equity), 0.0) or 0.0,
        }

        objective_prompt = (
            f"Company fundamentals for {request.ticker} "
            f"(latest period: {_safe(lambda: latest.report_period, 'recent')}):\n"
            f"  Revenue growth (YoY): {metrics['revenue_growth'] * 100:+.1f}%\n"
            f"  Gross margin: {metrics['gross_margin'] * 100:.1f}%\n"
            f"  Operating margin: {metrics['operating_margin'] * 100:.1f}%\n"
            f"  Net margin: {metrics['net_margin'] * 100:.1f}%\n"
            f"  ROIC: {metrics['roic'] * 100:.1f}%\n"
            f"  FCF margin: {metrics['fcf_margin'] * 100:.1f}%\n"
            f"  Debt/Equity: {metrics['debt_to_equity']:.2f}\n"
            f"\nWrite 3-5 sentences objectively describing the company's\n"
            f"profitability, capital efficiency, and apparent moat strength.\n"
            f"Anchor every claim on a number above. Do not predict price."
        )

        prompt = objective_prompt
        if persona is not None:
            from src.research.personas import PERSONA_REGISTRY
            persona_obj = PERSONA_REGISTRY.get(persona)
            if persona_obj is not None:
                prompt = (
                    persona_obj.system_addition()
                    + "\n\n"
                    + persona_obj.module_lens(self.name)
                    + "\n\n"
                    + objective_prompt
                )

        narrative = call_research_llm(
            prompt, _FundamentalsNarrative,
            default_factory=lambda: _FundamentalsNarrative(
                narrative=(
                    f"Revenue growth {metrics['revenue_growth'] * 100:+.1f}%, "
                    f"net margin {metrics['net_margin'] * 100:.1f}%, "
                    f"ROIC {metrics['roic'] * 100:.1f}%."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=persona,
            markdown=narrative.narrative, key_metrics=metrics,
        )
