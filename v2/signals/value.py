"""Value signal — composite of P/E, P/B, P/S, and FCF yield.

Each ratio is mapped to a per-factor score in [-1, +1] via a piecewise
linear scale anchored at "neutral" levels (P/E≈20, P/B≈3, P/S≈3, FCF
yield≈5%). The signal is the equal-weighted mean of the available factors.
Cheap = bullish (positive value).
"""

from __future__ import annotations

from v2.data.protocol import DataClient
from v2.models import SignalResult
from v2.signals.base import BaseSignal


def _inv_ratio_score(
    ratio: float | None,
    *,
    cheap: float,
    expensive: float,
) -> float | None:
    """Map an "earnings yield"-style ratio into [-1, +1].

    Lower ratio = cheaper = bullish (positive score). Linearly scaled
    between ``cheap`` (→ +1) and ``expensive`` (→ -1). Returns ``None``
    when ratio is missing or non-positive (negative-earnings P/E is
    uninformative — defer to other factors).
    """
    if ratio is None or ratio <= 0:
        return None
    if ratio <= cheap:
        return 1.0
    if ratio >= expensive:
        return -1.0
    # Linear interp from +1 at cheap to -1 at expensive.
    span = expensive - cheap
    return 1.0 - 2.0 * (ratio - cheap) / span


def _yield_score(
    value: float | None,
    *,
    low: float,
    high: float,
) -> float | None:
    """Map a "yield"-style value (higher = better) into [-1, +1]."""
    if value is None:
        return None
    if value >= high:
        return 1.0
    if value <= low:
        return -1.0
    span = high - low
    return -1.0 + 2.0 * (value - low) / span


class ValueSignal(BaseSignal):
    """Cheap-vs-expensive valuation composite. Positive = bullish."""

    name = "value"

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
        s = _inv_ratio_score(m.price_to_earnings_ratio, cheap=10.0, expensive=35.0)
        if s is not None:
            scores["pe"] = s
        s = _inv_ratio_score(m.price_to_book_ratio, cheap=1.0, expensive=6.0)
        if s is not None:
            scores["pb"] = s
        s = _inv_ratio_score(m.price_to_sales_ratio, cheap=1.0, expensive=8.0)
        if s is not None:
            scores["ps"] = s
        s = _yield_score(m.free_cash_flow_yield, low=0.0, high=0.08)
        if s is not None:
            scores["fcf_yield"] = s

        if not scores:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"reason": "no valuation ratios available"},
            )

        value = sum(scores.values()) / len(scores)
        return SignalResult(
            signal_name=self.name,
            value=max(-1.0, min(1.0, value)),
            components={k: float(v) for k, v in scores.items()},
        )
