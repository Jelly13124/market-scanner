"""Earnings quality signal — growth + FCF backing.

Captures both growth rate and the *quality* of that growth (is reported
income converting to cash?). Combines revenue_growth, earnings_growth,
and FCF growth, each scored on a piecewise-linear scale anchored at
"shrinking" (→ -1) and "fast-growing" (→ +1) levels.
"""

from __future__ import annotations

from v2.data.protocol import DataClient
from v2.models import SignalResult
from v2.signals.base import BaseSignal


def _growth_score(value: float | None, *, weak: float, strong: float) -> float | None:
    """Map a growth rate into [-1, +1]."""
    if value is None:
        return None
    if value >= strong:
        return 1.0
    if value <= weak:
        return -1.0
    span = strong - weak
    return -1.0 + 2.0 * (value - weak) / span


class EarningsQualitySignal(BaseSignal):
    """Growth + FCF conversion composite. Positive = bullish."""

    name = "earnings_quality"

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
        # Revenue: -5% → -1, +25% → +1
        s = _growth_score(m.revenue_growth, weak=-0.05, strong=0.25)
        if s is not None:
            scores["revenue_growth"] = s
        # Earnings: more volatile, wider band
        s = _growth_score(m.earnings_growth, weak=-0.20, strong=0.40)
        if s is not None:
            scores["earnings_growth"] = s
        # FCF growth: backs the earnings — same band as earnings
        s = _growth_score(m.free_cash_flow_growth, weak=-0.20, strong=0.40)
        if s is not None:
            scores["fcf_growth"] = s
        # EPS growth — slightly tighter band than absolute earnings.
        s = _growth_score(m.earnings_per_share_growth, weak=-0.15, strong=0.35)
        if s is not None:
            scores["eps_growth"] = s

        if not scores:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"reason": "no growth metrics available"},
            )

        value = sum(scores.values()) / len(scores)
        return SignalResult(
            signal_name=self.name,
            value=max(-1.0, min(1.0, value)),
            components={k: float(v) for k, v in scores.items()},
        )
