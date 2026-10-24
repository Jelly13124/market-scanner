"""Quality signal — profitability and capital efficiency composite.

Combines ROE, ROIC, operating margin, and gross margin. Each is scored
on a piecewise-linear scale anchored at sector-agnostic "good"/"poor"
levels (ROIC: 5%/20%, ROE: 5%/20%, op margin: 5%/25%, gross margin: 20%/50%).
High quality = bullish (positive value).
"""

from __future__ import annotations

from v2.data.protocol import DataClient
from v2.models import SignalResult
from v2.signals.base import BaseSignal


def _band_score(value: float | None, *, poor: float, good: float) -> float | None:
    """Map a metric into [-1, +1] given a poor (→ -1) and good (→ +1) anchor."""
    if value is None:
        return None
    if value >= good:
        return 1.0
    if value <= poor:
        return -1.0
    span = good - poor
    return -1.0 + 2.0 * (value - poor) / span


class QualitySignal(BaseSignal):
    """Profitability + capital efficiency composite. Positive = bullish."""

    name = "quality"

    def compute(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
    ) -> SignalResult:
        try:
            metrics = fd.get_financial_metrics(ticker, end_date, limit=1)
        except Exception as e:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"error": str(e)},
            )

        if not metrics:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"reason": "no financial_metrics"},
            )
        m = metrics[0]

        scores: dict[str, float] = {}
        s = _band_score(m.return_on_invested_capital, poor=0.05, good=0.20)
        if s is not None:
            scores["roic"] = s
        s = _band_score(m.return_on_equity, poor=0.05, good=0.20)
        if s is not None:
            scores["roe"] = s
        s = _band_score(m.operating_margin, poor=0.05, good=0.25)
        if s is not None:
            scores["operating_margin"] = s
        s = _band_score(m.gross_margin, poor=0.20, good=0.50)
        if s is not None:
            scores["gross_margin"] = s

        if not scores:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"reason": "no profitability metrics available"},
            )

        value = sum(scores.values()) / len(scores)
        return SignalResult(
            signal_name=self.name,
            value=max(-1.0, min(1.0, value)),
            components={k: float(v) for k, v in scores.items()},
        )
