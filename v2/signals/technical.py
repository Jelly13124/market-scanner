"""Technical signal — RSI + price-vs-MA composite.

Two equal-weighted sub-scores:
  * RSI(14): oversold (< 30) → bullish, overbought (> 70) → bearish,
    linearly mapped through neutral at 50.
  * Trend: close vs 50-day SMA, scaled by ±10% bands.

Both use adjusted_close when available to avoid false reads on ex-div days.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from v2.data.protocol import DataClient
from v2.models import SignalResult
from v2.signals.base import BaseSignal


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _series(prices: list) -> pd.Series:
    """Adjusted-close series indexed by date string."""
    rows: dict[str, float] = {}
    for p in prices:
        c = p.adjusted_close if p.adjusted_close is not None else p.close
        rows[p.time] = float(c)
    return pd.Series(rows).sort_index()


class TechnicalSignal(BaseSignal):
    """RSI + trend composite. Positive = bullish."""

    name = "technical"

    def __init__(
        self,
        *,
        rsi_period: int = 14,
        ma_window: int = 50,
        lookback_days: int = 120,
        trend_band: float = 0.10,
    ) -> None:
        self._rsi_period = rsi_period
        self._ma_window = ma_window
        self._lookback_days = lookback_days
        self._trend_band = trend_band

    def compute(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
    ) -> SignalResult:
        end = _parse_date(end_date)
        start = (end - timedelta(days=self._lookback_days)).isoformat()
        try:
            prices = fd.get_prices(ticker, start_date=start, end_date=end_date)
        except Exception as e:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"error": str(e)},
            )
        # Need ma_window bars at minimum.
        min_bars = max(self._rsi_period + 5, self._ma_window + 5)
        if not prices or len(prices) < min_bars:
            return SignalResult(
                signal_name=self.name, value=0.0,
                metadata={"reason": f"insufficient prices ({len(prices) if prices else 0} bars)"},
            )

        series = _series(prices)
        # RSI
        rsi = self._compute_rsi(series, period=self._rsi_period)
        # RSI score: 30 → +1, 50 → 0, 70 → -1; linear inside [30, 70].
        if rsi <= 30:
            rsi_score = 1.0
        elif rsi >= 70:
            rsi_score = -1.0
        else:
            rsi_score = (50.0 - rsi) / 20.0

        # Trend: pct deviation of latest close from 50-day SMA.
        ma = series.rolling(window=self._ma_window).mean().iloc[-1]
        latest = series.iloc[-1]
        if pd.isna(ma) or ma <= 0:
            return SignalResult(
                signal_name=self.name,
                value=max(-1.0, min(1.0, rsi_score)),
                components={"rsi": float(rsi), "rsi_score": float(rsi_score)},
                metadata={"reason": "trend unavailable, RSI only"},
            )
        dev = (latest - ma) / ma
        if dev >= self._trend_band:
            trend_score = 1.0
        elif dev <= -self._trend_band:
            trend_score = -1.0
        else:
            trend_score = dev / self._trend_band

        value = (rsi_score + trend_score) / 2.0
        return SignalResult(
            signal_name=self.name,
            value=max(-1.0, min(1.0, value)),
            components={
                "rsi": float(rsi),
                "rsi_score": float(rsi_score),
                "ma_dev": float(dev),
                "trend_score": float(trend_score),
            },
        )
