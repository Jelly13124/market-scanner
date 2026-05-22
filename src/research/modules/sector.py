"""Sector module — relative strength vs sector ETF."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _SectorNarrative(BaseModel):
    narrative: str = Field(
        description="2-3 sentences on the ticker's sector and relative strength."
    )


def _ret_20d(bars) -> float | None:
    bars = sorted(bars, key=lambda b: b.time[:10])
    if len(bars) < 21:
        return None
    closes = [float(getattr(b, "adjusted_close", None) or b.close) for b in bars[-21:]]
    return (closes[-1] / closes[0]) - 1.0


class SectorModule(AnalysisModule):
    name = "sector"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        ticker_ret = _ret_20d(shared_data.prices)
        etf_ret = _ret_20d(shared_data.sector_etf_prices)
        if ticker_ret is None or etf_ret is None:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason="Insufficient ticker or sector-ETF price history",
            )

        rs_pp = round((ticker_ret - etf_ret) * 100, 2)
        sector = shared_data.company_facts.get("sector") or "Unknown"
        prompt = (
            f"Sector context for {request.ticker} (sector: {sector}):\n"
            f"  Ticker 20d return: {ticker_ret * 100:+.2f}%\n"
            f"  Sector ETF 20d return: {etf_ret * 100:+.2f}%\n"
            f"  Relative strength: {rs_pp:+.2f}pp\n"
            f"\nWrite 2-3 sentences summarizing whether the ticker is\n"
            f"leading, lagging, or in line with its sector. Describe,\n"
            f"do not predict."
        )
        narrative = call_research_llm(
            prompt, _SectorNarrative,
            default_factory=lambda: _SectorNarrative(
                narrative=f"{request.ticker} {rs_pp:+.2f}pp vs sector over 20d."
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative,
            key_metrics={
                "ticker_return_20d": round(ticker_ret, 4),
                "etf_return_20d": round(etf_ret, 4),
                "relative_strength_pp": rs_pp,
            },
        )
