"""52-week-high breakout detector.

Fires on the FIRST day a stock's adjusted close breaks above its trailing
252-bar (≈52-week) high. Bullish only — the symmetric 52w-low bearish variant
was excluded from scope (see findings.md: 52w-low produces excessive noise
in trending markets and its short-side alpha is weaker on the CSI-300 + US
universe mixture; logged 2026-05-29).

**First-day-entry gate** (critical, same pattern as BollingerSqueezeDetector):

    close_today >= prior_max_today   AND   close_yesterday < prior_max_yesterday

where:
    prior_max_today     = max(closes[-window-1 : -1])   (the ``window`` bars
                          ending at yesterday)
    prior_max_yesterday = max(closes[-window-2 : -2])   (the ``window`` bars
                          ending at two days ago)

This fires exactly once — the first day the close clears the 252-bar high.
A stock that sits at a new high for 5 consecutive days would only trigger on
day 1.

**Severity z-score**:

    returns = np.diff(closes) / closes[:-1]
    ret_std  = max(returns.std(ddof=1), 0.005)   ← real floor, see invariant #1
    severity_z = (close_today / prior_max_today - 1.0) / ret_std
               clamped to [0.0, 8.0]

The 0.005 floor (50 bps) is a meaningful daily-return std: stocks rarely have
trailing daily std < 0.5% even for the calmest large-caps.  Using ``or 1e-6``
would only catch exactly 0.0 and miss the collapsed-but-nonzero case that
produced GEHC z=+55 trillion.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, close_of, parse_date as _parse_date
from v2.scanner.models import ScanContext

logger = logging.getLogger(__name__)


class HighBreakoutDetector(EventDetector):
    """Trigger on the first day a ticker closes above its 252-bar trailing high."""

    name = "high_breakout"

    def __init__(
        self,
        *,
        lookback_days: int = 400,   # calendar days; yields ≥ 252 trading bars
        window: int = 252,          # trading bars for the 52-week high
    ) -> None:
        self._lookback = lookback_days
        self._window = window

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
            logger.debug("high_breakout: get_prices(%s) failed: %s", ticker, e)
            return None

        # Need window + 2 bars: window closes for prior_max, plus today and yesterday.
        min_bars = self._window + 2
        if not prices or len(prices) < min_bars:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        closes_list = [close_of(p) for p in prices_sorted]
        if any(c is None or c <= 0 for c in closes_list):
            return None
        closes = np.array(closes_list, dtype=float)

        n = len(closes)
        # Indices (0-based, closes[-1] = today, closes[-2] = yesterday):
        #   close_today     = closes[-1]
        #   close_yesterday = closes[-2]
        #   prior_max_today = max over closes[-window-1 : -1]  (window bars ending yesterday)
        #   prior_max_yest  = max over closes[-window-2 : -2]  (window bars ending two days ago)
        close_today = float(closes[-1])
        close_yesterday = float(closes[-2])

        # Slice for prior_max_today: window bars immediately before today.
        start_idx_today = max(0, n - self._window - 1)
        prior_max_today = float(closes[start_idx_today : n - 1].max())

        # Slice for prior_max_yesterday: window bars ending two days ago.
        start_idx_yest = max(0, n - self._window - 2)
        prior_max_yesterday = float(closes[start_idx_yest : n - 2].max())

        # Severity z-score (invariant #1: real std floor, not `or 1e-6`).
        returns = np.diff(closes) / closes[:-1]
        ret_std = max(float(returns.std(ddof=1)), 0.005)  # real floor: 50 bps daily
        raw_z = (close_today / prior_max_today - 1.0) / ret_std
        severity_z = float(np.clip(raw_z, 0.0, 8.0))

        components: dict[str, float] = {
            "prior_max": prior_max_today,
            "close_today": close_today,
            "close_yesterday": close_yesterday,
            "prior_max_yesterday": prior_max_yesterday,
            "ret_std": ret_std,
        }

        # First-day gate.
        breaks_today = close_today >= prior_max_today
        was_below_yesterday = close_yesterday < prior_max_yesterday

        if not (breaks_today and was_below_yesterday):
            if breaks_today:
                reason = (
                    f"52w-high break already in progress "
                    f"(yesterday {close_yesterday:.2f} >= prior_max {prior_max_yesterday:.2f}) "
                    f"— not first-day entry"
                )
            else:
                reason = (
                    f"no 52w-high break: close {close_today:.2f} < prior_max {prior_max_today:.2f}"
                )
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=reason,
                components=components,
                asof_date=end_date,
            )

        reason = (
            f"first-day 52w-high breakout: close {close_today:.2f} >= "
            f"prior_max {prior_max_today:.2f} (yesterday {close_yesterday:.2f} < "
            f"prior_max_yesterday {prior_max_yesterday:.2f}); "
            f"z={severity_z:.2f} (ret_std={ret_std:.4f})"
        )
        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=severity_z,
            direction="bullish",
            reason=reason,
            components=components,
            asof_date=end_date,
        )
