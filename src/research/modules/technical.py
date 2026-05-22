"""Technical module — RSI(14), 50d/200d SMA, recent support/resistance."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _TechnicalNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences on trend, momentum, and proximity to S/R."
    )


def _rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    # Use the MOST RECENT 14 deltas — RSI is a current-momentum signal,
    # not a historical one.
    deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


class TechnicalModule(AnalysisModule):
    name = "technical"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        bars = sorted(shared_data.prices, key=lambda b: b.time[:10])
        if len(bars) < 60:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason=f"Need >=60 bars for technical analysis, got {len(bars)}",
            )

        closes = [float(getattr(b, "adjusted_close", None) or b.close) for b in bars]
        price = closes[-1]

        sma_50 = round(sum(closes[-50:]) / 50, 2)
        sma_200 = round(sum(closes[-200:]) / 200, 2) if len(closes) >= 200 else None
        rsi = _rsi14(closes)

        # Support / resistance: 60-day extremes
        recent = closes[-60:]
        support = round(min(recent), 2)
        resistance = round(max(recent), 2)

        metrics = {
            "current_price": round(price, 2),
            "sma_50": sma_50,
            "rsi_14": rsi if rsi is not None else 0.0,
            "support": support,
            "resistance": resistance,
        }
        if sma_200 is not None:
            metrics["sma_200"] = sma_200

        trend_bits = []
        if price > sma_50:
            trend_bits.append(f"above 50d SMA ({sma_50:.2f})")
        else:
            trend_bits.append(f"below 50d SMA ({sma_50:.2f})")
        if sma_200 is not None:
            trend_bits.append(f"vs 200d SMA ${sma_200:.2f}")

        prompt = (
            f"Technical snapshot for {request.ticker}:\n"
            f"  Price: ${price:.2f}\n"
            f"  RSI(14): {rsi}\n"
            f"  50d SMA: ${sma_50:.2f}\n"
            + (f"  200d SMA: ${sma_200:.2f}\n" if sma_200 is not None else "")
            + f"  60d support / resistance: ${support:.2f} / ${resistance:.2f}\n"
            f"\nWrite 3-5 sentences objectively describing the trend\n"
            f"({', '.join(trend_bits)}), momentum (RSI), and proximity to\n"
            f"support/resistance. Anchor on numbers. Do not predict."
        )
        narrative = call_research_llm(
            prompt, _TechnicalNarrative,
            default_factory=lambda: _TechnicalNarrative(
                narrative=(
                    f"Price ${price:.2f}, RSI {rsi}, "
                    f"S/R ${support:.2f}/${resistance:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
