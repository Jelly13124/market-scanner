"""Gap up/down detector.

Fires when today's OPEN gaps significantly from yesterday's CLOSE, as measured
by the gap size z-scored against a trailing ~60-bar distribution of daily gaps.

**No first-day gate needed** — a gap is inherently a one-day event. The close
of yesterday either produced a gap today or it didn't; there's no multi-day
state to guard against re-firing.

**Std floor** (invariant #1):

    gap_std = max(float(np.std(gaps, ddof=1)), 0.003)   ← REAL FLOOR, not ``or 1e-6``

0.003 (30 bps) is a meaningful daily-gap std: even the calmest large-caps
gap at least a few bps overnight on average. Using ``or 1e-6`` only catches
exactly 0.0 and misses the "collapsed but nonzero" case that produced the
GEHC z=+55 trillion blowup documented in findings.md.

**Direction**: bullish when gap_today > 0 (opening above prior close),
bearish when gap_today < 0.

**Severity**: gap_z clamped to [0, 8]. The raw z can be enormous on earnings
morning gaps; clamping prevents a single extreme event from washing out all
other tickers in composite scoring.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, close_of, parse_date as _parse_date
from v2.scanner.models import ScanContext

logger = logging.getLogger(__name__)


class GapDetector(EventDetector):
    """Trigger when today's open gaps significantly from yesterday's close."""

    name = "gap"

    def __init__(
        self,
        *,
        lookback_days: int = 120,   # calendar days; yields ≥ 80 trading bars
        min_bars: int = 62,         # need gap_window+2 price bars to build gap_window gap observations
        gap_window: int = 60,       # trailing bars for gap distribution
        threshold: float = 3.0,     # |gap_z| must exceed this to fire
    ) -> None:
        self._lookback = lookback_days
        self._min_bars = min_bars
        self._gap_window = gap_window
        self._threshold = threshold

    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        today_date = _parse_date(end_date)
        if today_date is None:
            return None

        start = (today_date - timedelta(days=self._lookback)).isoformat()
        try:
            prices = fd.get_prices(ticker, start, end_date)
        except Exception as e:
            logger.debug("gap: get_prices(%s) failed: %s", ticker, e)
            return None

        # Need ≥ min_bars price bars: min_bars - 1 gap observations from the
        # trailing window plus today's open/yesterday's close.
        if not prices or len(prices) < self._min_bars:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])

        # Build gap series: gap_i = open_i / close_{i-1} - 1.
        # Skip any bar where open is missing or close_{i-1} is missing/zero.
        opens: list[float] = []
        closes: list[float] = []
        for p in prices_sorted:
            c = close_of(p)
            o = p.open if p.open is not None else None
            opens.append(o)      # type: ignore[arg-type]
            closes.append(c)     # type: ignore[arg-type]

        # Today's bar: last element.
        open_today = opens[-1]
        close_yesterday = closes[-2]  # safe: len ≥ min_bars ≥ 2

        if open_today is None or open_today <= 0:
            return None
        if close_yesterday is None or close_yesterday <= 0:
            return None

        gap_today = open_today / close_yesterday - 1.0

        # Build the trailing gap series over the last gap_window bars.
        # Use the portion of prices ending at yesterday (prices_sorted[:-1])
        # so today's gap is not included in the distribution it's being compared to.
        history = prices_sorted[-self._gap_window - 2 : -1]  # gap_window + 1 bars → gap_window gaps
        gaps: list[float] = []
        for i in range(1, len(history)):
            c_prev = close_of(history[i - 1])
            o_curr = history[i].open
            if c_prev is None or c_prev <= 0 or o_curr is None or o_curr <= 0:
                continue
            gaps.append(o_curr / c_prev - 1.0)

        if len(gaps) < self._gap_window:
            # Not enough clean gap observations.
            return None

        gaps_arr = np.array(gaps, dtype=float)
        # Invariant #1: real std floor — never `or 1e-6`.
        gap_std = max(float(np.std(gaps_arr, ddof=1)), 0.003)
        gap_z = gap_today / gap_std
        severity_z = float(min(abs(gap_z), 8.0))

        direction = "bullish" if gap_today > 0 else "bearish"

        components: dict[str, float] = {
            "gap": gap_today,
            "gap_z": gap_z,
            "gap_std": gap_std,
            "open_today": open_today,
            "close_yesterday": close_yesterday,
        }

        if abs(gap_z) < self._threshold:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=(
                    f"gap {gap_today*100:.2f}% (z={gap_z:.2f}) below threshold "
                    f"|z| < {self._threshold}"
                ),
                components=components,
                asof_date=end_date,
            )

        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=severity_z,
            direction=direction,
            reason=(
                f"{direction} gap: open {open_today:.2f} vs prev close {close_yesterday:.2f} "
                f"→ gap {gap_today*100:.2f}% (z={gap_z:.2f}, std={gap_std:.4f})"
            ),
            components=components,
            asof_date=end_date,
        )
