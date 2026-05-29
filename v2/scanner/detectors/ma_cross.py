"""Golden/death cross detector (SMA50 × SMA200).

Fires on the day SMA(fast=50) crosses SMA(slow=200) — a classical
regime-change signal widely cited in technical analysis literature
(Murphy 1999; Lo, Mamaysky & Wang 2000).

**Golden cross (bullish):** SMA50 was ≤ SMA200 yesterday AND SMA50 > SMA200 today.
**Death cross (bearish):** SMA50 was ≥ SMA200 yesterday AND SMA50 < SMA200 today.
If neither condition holds → ``EventTrigger(triggered=False, ...)``.

**Severity:** Fixed at 2.0 — a cross is a binary regime event, not a
z-scored continuous quantity. There is NO z-score divisor here; no std is
computed at all. The fixed 2.0 is consistent with how BollingerSqueezeDetector
handles its categorical trigger (see bollinger_squeeze.py ``self._severity``).

**Minimum bars:** ``slow + 2 = 202``. We need at least 200 closes for
SMA200 and one extra bar each for "today" and "yesterday" SMA windows.
Below this threshold the detector returns ``None`` (no data, exclude ticker).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, close_of, parse_date as _parse_date
from v2.scanner.models import ScanContext

_FAST = 50
_SLOW = 200
_MIN_BARS = _SLOW + 2   # 202: 200 for SMA200 + today + yesterday
_LOOKBACK_DAYS = 400    # calendar-day buffer; yields ≥ 202 trading bars
_SEVERITY = 2.0         # fixed categorical magnitude — no z-divisor


class MaCrossDetector(EventDetector):
    """Trigger on the day SMA50 crosses above (golden) or below (death) SMA200."""

    name = "ma_cross"

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

        start = (today_date - timedelta(days=_LOOKBACK_DAYS)).isoformat()
        try:
            prices = fd.get_prices(ticker, start, end_date)
        except Exception:
            return None

        if not prices or len(prices) < _MIN_BARS:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        closes_list = [close_of(p) for p in prices_sorted]
        if any(c is None or c <= 0 for c in closes_list):
            return None
        closes = np.array(closes_list, dtype=float)

        # SMA windows:
        #   Today:     closes[-FAST:]   and closes[-SLOW:]
        #   Yesterday: closes[-FAST-1:-1] and closes[-SLOW-1:-1]
        sma_fast_today = float(closes[-_FAST:].mean())
        sma_slow_today = float(closes[-_SLOW:].mean())
        sma_fast_yest = float(closes[-_FAST - 1 : -1].mean())
        sma_slow_yest = float(closes[-_SLOW - 1 : -1].mean())

        components = {
            "sma_fast_today": sma_fast_today,
            "sma_slow_today": sma_slow_today,
            "sma_fast_yest": sma_fast_yest,
            "sma_slow_yest": sma_slow_yest,
        }

        golden = sma_fast_yest <= sma_slow_yest and sma_fast_today > sma_slow_today
        death = sma_fast_yest >= sma_slow_yest and sma_fast_today < sma_slow_today

        if golden:
            reason = (
                f"golden cross: SMA{_FAST} {sma_fast_today:.4f} > SMA{_SLOW} {sma_slow_today:.4f} "
                f"(yesterday SMA{_FAST} {sma_fast_yest:.4f} <= SMA{_SLOW} {sma_slow_yest:.4f})"
            )
            return EventTrigger(
                detector=self.name,
                triggered=True,
                severity_z=_SEVERITY,
                direction="bullish",
                reason=reason,
                components=components,
                asof_date=end_date,
            )

        if death:
            reason = (
                f"death cross: SMA{_FAST} {sma_fast_today:.4f} < SMA{_SLOW} {sma_slow_today:.4f} "
                f"(yesterday SMA{_FAST} {sma_fast_yest:.4f} >= SMA{_SLOW} {sma_slow_yest:.4f})"
            )
            return EventTrigger(
                detector=self.name,
                triggered=True,
                severity_z=_SEVERITY,
                direction="bearish",
                reason=reason,
                components=components,
                asof_date=end_date,
            )

        reason = (
            f"no cross: SMA{_FAST} {sma_fast_today:.4f} vs SMA{_SLOW} {sma_slow_today:.4f} "
            f"(yesterday {sma_fast_yest:.4f} vs {sma_slow_yest:.4f})"
        )
        return EventTrigger(
            detector=self.name,
            triggered=False,
            reason=reason,
            components=components,
            asof_date=end_date,
        )
