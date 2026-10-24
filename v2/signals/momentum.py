"""Momentum signal — 12-1 month price return.

Classic Jegadeesh & Titman (1993) signal: skip the most recent month
(to dodge short-term reversal) and rank on the prior 11 months. Value
is mapped to [-1, +1] via ``tanh`` so that ~50% momentum saturates.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.models import SignalResult
from v2.signals.base import BaseSignal


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _pick_close(prices: list, idx: int) -> float | None:
    """Index-safe close picker. Accepts negative (Python-style) indices."""
    n = len(prices)
    if n == 0:
        return None
    if idx < 0:
        idx = n + idx
    if idx < 0 or idx >= n:
        return None
    p = prices[idx]
    return p.adjusted_close if p.adjusted_close is not None else p.close


class MomentumSignal(BaseSignal):
    """12-month minus 1-month return, scaled into [-1, +1]."""

    name = "momentum"

    def __init__(
        self,
        *,
        lookback_days: int = 365,
        skip_days: int = 21,
        saturation: float = 0.50,
    ) -> None:
        self._lookback_days = lookback_days
        self._skip_days = skip_days
        self._saturation = saturation

    def compute(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
    ) -> SignalResult:
        end = _parse_date(end_date)
        # Pull enough calendar days that we definitely have ~250 trading days
        # plus a buffer for weekends/holidays.
        start = (end - timedelta(days=self._lookback_days + 60)).isoformat()
        try:
            prices = fd.get_prices(ticker, start_date=start, end_date=end_date)
        except Exception as e:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"error": str(e)},
            )

        # Need at least lookback + skip trading bars to compute the signal.
        min_bars = max(60, int((self._lookback_days + self._skip_days) * 0.5))
        if not prices or len(prices) < min_bars:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"reason": f"insufficient prices ({len(prices) if prices else 0} bars)"},
            )

        prices = sorted(prices, key=lambda p: p.time)
        latest_close = _pick_close(prices, -1)
        # Skip the last ~21 trading bars (1 month).
        skip_idx = -1 - self._skip_days
        skip_close = _pick_close(prices, skip_idx)
        # Anchor ~252 trading bars back (1 year).
        anchor_idx = max(0, len(prices) - self._lookback_days // 2 * 2 - self._skip_days)
        # Simpler: use a calendar-day anchor — the first bar whose time >= start_anchor.
        start_anchor = (end - timedelta(days=self._lookback_days)).isoformat()
        anchor_close = None
        for p in prices:
            if p.time >= start_anchor:
                anchor_close = p.adjusted_close if p.adjusted_close is not None else p.close
                break

        if latest_close is None or skip_close is None or anchor_close is None or anchor_close <= 0:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"reason": "missing anchor/latest/skip price"},
            )

        # 12-1 momentum: return from anchor to skip-bar (drops the trailing month).
        twelve_one = (skip_close - anchor_close) / anchor_close
        # tanh saturates at ±1 around the saturation point.
        value = float(np.tanh(twelve_one / self._saturation))

        return SignalResult(
            signal_name=self.name,
            value=max(-1.0, min(1.0, value)),
            components={
                "twelve_one_return": float(twelve_one),
                "anchor_close": float(anchor_close),
                "skip_close": float(skip_close),
                "latest_close": float(latest_close),
            },
        )
