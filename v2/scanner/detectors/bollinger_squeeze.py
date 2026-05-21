"""Bollinger squeeze detector (M9.f).

Detects volatility COMPRESSION — when 20-day Bollinger bandwidth falls
into the bottom decile of its own trailing-126-day distribution, the
stock is statistically primed for a directional move. Bollinger's own
empirical work: ~80% of squeezes break out within 20 trading days
(direction unpredictable from the squeeze alone).

This is a **setup detector**, not an event detector — the 7 other
detectors all fire on something that already happened; squeeze fires
on a state that signals something is about to happen.

**First-day-entry gate** (critical): without this, a stock that enters
squeeze and stays there for 15 days would fire 15 days in a row,
turning a one-time event into chronic noise. Gate:

    percentile_yesterday > threshold  AND  percentile_today ≤ threshold

So we only fire the FIRST day the bandwidth drops into the squeeze
zone. Same pattern as the multi-horizon breakout's first-day rule.

Direction is always **neutral** — squeeze predicts magnitude, not sign.
The composite-score direction logic treats neutral severities as zero,
so a SQZ-only ticker appears in the watchlist without a bullish/bearish
stance for downstream LLM/user to assess.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, close_of, parse_date as _parse_date
from v2.scanner.models import ScanContext


def _bandwidth(closes: np.ndarray, window: int, std_mult: float) -> float | None:
    """20-day Bollinger bandwidth = (upper - lower) / mid, computed on the
    last ``window`` closes. Returns None when there's not enough history or
    the rolling mean is non-positive."""
    if len(closes) < window:
        return None
    tail = closes[-window:]
    mid = float(tail.mean())
    if mid <= 0:
        return None
    sigma = float(tail.std(ddof=1))  # noqa: std-floor (sigma is numerator coefficient, not z-divisor)
    return (2.0 * std_mult * sigma) / mid


class BollingerSqueezeDetector(EventDetector):
    """Trigger on first-day entry into the bandwidth bottom decile."""

    name = "bollinger_squeeze"

    def __init__(
        self,
        *,
        lookback_days: int = 220,           # ≈ 150 trading days, covers 126 + 20 + buffer
        bb_window: int = 20,
        bb_std_mult: float = 2.0,
        percentile_window: int = 126,
        percentile_threshold: float = 0.10,  # bottom decile = squeeze
        severity: float = 2.0,
    ) -> None:
        self._lookback = lookback_days
        self._bb_window = bb_window
        self._bb_std_mult = bb_std_mult
        self._pct_window = percentile_window
        self._pct_thresh = percentile_threshold
        self._severity = severity

    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        today = _parse_date(end_date)
        if today is None:
            return None

        start = (today - timedelta(days=self._lookback)).isoformat()
        prices = fd.get_prices(ticker, start, end_date)
        # We need ``percentile_window + bb_window + 2`` bars: the bb_window
        # for today's rolling band, the percentile_window of historical
        # bandwidths to rank against, and +2 for today vs yesterday's
        # first-day comparison.
        min_bars = self._pct_window + self._bb_window + 2
        if not prices or len(prices) < min_bars:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        closes_list = [close_of(p) for p in prices_sorted]
        if any(c is None or c <= 0 for c in closes_list):
            return None
        closes = np.array(closes_list, dtype=float)

        # Build the rolling bandwidth series up to and including TODAY.
        # We need percentile_window + 1 bandwidths so we can compare today
        # to yesterday and compute each percentile against its own trailing
        # window. Cheap: O(percentile_window) iterations per ticker.
        n_bw = self._pct_window + 1
        bandwidths: list[float] = []
        # The earliest bandwidth uses closes ending bb_window back from the
        # bandwidth we want. So we iterate from the most-recent end and walk
        # back, then reverse to get oldest→newest.
        for offset in range(n_bw):
            end_idx = len(closes) - offset
            window_slice = closes[end_idx - self._bb_window : end_idx]
            if len(window_slice) < self._bb_window:
                return None
            mid = float(window_slice.mean())
            if mid <= 0:
                return None
            sigma = float(window_slice.std(ddof=1))  # noqa: std-floor (sigma is numerator coefficient, not z-divisor)
            bandwidths.append((2.0 * self._bb_std_mult * sigma) / mid)
        bandwidths.reverse()  # oldest → newest, last entry = today

        bw_today = bandwidths[-1]
        bw_yesterday = bandwidths[-2]

        # Percentile rank against the trailing ``percentile_window`` history
        # ENDING at that bandwidth (exclusive of the bandwidth itself). For
        # today, that's the prior 126 days; for yesterday, the prior 126
        # ending one day earlier.
        def _percentile(value: float, history: list[float]) -> float:
            """Fraction of ``history`` strictly less than or equal to ``value``."""
            if not history:
                return 1.0
            arr = np.array(history)
            return float(np.sum(arr <= value)) / float(len(arr))

        pct_today = _percentile(bw_today, bandwidths[:-1])         # vs prior 126
        pct_yesterday = _percentile(bw_yesterday, bandwidths[:-2]) # vs prior 125

        components = {
            "bandwidth_today": float(bw_today),
            "bandwidth_yesterday": float(bw_yesterday),
            "percentile_today": float(pct_today),
            "percentile_yesterday": float(pct_yesterday),
            "percentile_threshold": float(self._pct_thresh),
        }

        # First-day-entry gate.
        in_squeeze_today = pct_today <= self._pct_thresh
        was_outside_yesterday = pct_yesterday > self._pct_thresh

        if not (in_squeeze_today and was_outside_yesterday):
            if in_squeeze_today:
                reason = (
                    f"already in squeeze (pctl yesterday={pct_yesterday:.3f}, "
                    f"today={pct_today:.3f}) — not first-day entry"
                )
            else:
                reason = f"bandwidth pctl {pct_today:.3f} > {self._pct_thresh:.2f}"
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=reason,
                components=components,
                asof_date=end_date,
            )

        reason = (
            f"first-day squeeze entry: bandwidth {bw_today*100:.2f}% "
            f"(pctl {pct_today:.3f}, was {pct_yesterday:.3f} yesterday)"
        )
        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=self._severity,
            direction="neutral",
            reason=reason,
            components=components,
            asof_date=end_date,
        )
