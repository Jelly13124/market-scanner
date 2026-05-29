"""RSI/Price divergence detector (classic technical divergence).

Classic price-vs-RSI divergence: when price makes a new extreme but the
momentum indicator (RSI) fails to confirm, it suggests the trend is losing
steam and a reversal is more likely.

**Bearish divergence**: price makes a higher high in the recent half of the
window BUT RSI at that price high is lower than RSI at the older price high.
→ ``triggered=True``, ``direction="bearish"``

**Bullish divergence**: price makes a lower low in the recent half BUT RSI
at that price low is higher than RSI at the older price low.
→ ``triggered=True``, ``direction="bullish"``

**No divergence**: price and RSI agree (both higher highs or both lower lows),
or the extremes are inconclusive.
→ ``EventTrigger(triggered=False, ...)``

**Swing detection**: simple two-half approach. The window (≈40 bars) is split
into an older half and a recent half; the price max (or min) over each half is
taken as the representative swing high (or low). This is intentionally simpler
than pivot-based detection — it is appropriate for a pre-filter screener where
false negatives are acceptable and false positives are caught by later LLM
analysis. See findings.md (C4) for the rationale.

**Severity**: ``min(abs(rsi_old - rsi_recent) / 10.0, 8.0)`` — the RSI gap
as a fraction of 10 RSI points, capped at 8. This is a coefficient of the
RSI-gap magnitude, NOT a z-score divisor; there is no std computed here.
# noqa: std-floor (coefficient, not z-divisor)

**Minimum bars**: 14 (RSI warmup) + 40 (divergence window) + 1 = 55. We fetch
~200 calendar days to safely get ≥55 trading bars.

**RSI implementation**: Wilder smoothing (exponential with alpha=1/14). Seeded
by the simple mean of the first 14 gain/loss values, then smoothed forward.
This matches the de-facto standard (MetaStock, TradingView default). The
``BaseSignal._compute_rsi`` helper uses simple rolling mean (not Wilder) so it
is NOT reused here — we implement Wilder RSI inline.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import (
    EventDetector,
    EventTrigger,
    close_of,
    parse_date as _parse_date,
)
from v2.scanner.models import ScanContext

# RSI period (Wilder default).
_RSI_PERIOD = 14
# Divergence window (bars): split into two halves of ~20 bars each.
_DIV_WINDOW = 40
# Minimum bars needed: RSI warmup + divergence window + 1.
_MIN_BARS = _RSI_PERIOD + _DIV_WINDOW + 1   # = 55
# Calendar-day lookback to safely produce ≥ MIN_BARS trading bars.
_LOOKBACK_DAYS = 200


def _wilder_rsi(closes: np.ndarray, period: int = _RSI_PERIOD) -> np.ndarray:
    """Wilder RSI over a 1-D close array.

    Returns an array of the same length. Values at indices < ``period`` are
    NaN (insufficient history). Seeded by the simple mean of the first
    ``period`` up/down moves, then Wilder-smoothed forward.
    """
    n = len(closes)
    rsi = np.full(n, float("nan"))
    if n <= period:
        return rsi

    deltas = np.diff(closes)  # length n-1
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed: simple mean of first ``period`` values.
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())

    if avg_loss == 0.0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - 100.0 / (1.0 + rs)

    # Wilder smoothing: alpha = 1/period.
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0.0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)

    return rsi


class RsiDivergenceDetector(EventDetector):
    """Trigger on classic price-vs-RSI divergence over a recent window."""

    name = "rsi_divergence"

    def __init__(
        self,
        *,
        rsi_period: int = _RSI_PERIOD,
        div_window: int = _DIV_WINDOW,
        lookback_days: int = _LOOKBACK_DAYS,
    ) -> None:
        self._rsi_period = rsi_period
        self._div_window = div_window
        self._lookback = lookback_days
        self._min_bars = rsi_period + div_window + 1

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
        except Exception:
            return None

        if not prices or len(prices) < self._min_bars:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        closes_list = [close_of(p) for p in prices_sorted]
        if any(c is None or c <= 0 for c in closes_list):
            return None

        closes = np.array(closes_list, dtype=float)
        rsi = _wilder_rsi(closes, period=self._rsi_period)

        # Use only the most recent ``div_window`` bars for the divergence check.
        window_closes = closes[-self._div_window:]
        window_rsi = rsi[-self._div_window:]

        # If any RSI value in the window is NaN, we don't have enough valid RSI
        # history to make a clean comparison — exclude this ticker.
        if np.any(np.isnan(window_rsi)):
            return None

        # Split the window into two halves.
        half = self._div_window // 2
        old_closes = window_closes[:half]
        old_rsi = window_rsi[:half]
        recent_closes = window_closes[half:]
        recent_rsi = window_rsi[half:]

        # --- Bearish divergence (highs) ---
        old_high_idx = int(np.argmax(old_closes))
        recent_high_idx = int(np.argmax(recent_closes))
        old_price_high = float(old_closes[old_high_idx])
        recent_price_high = float(recent_closes[recent_high_idx])
        old_rsi_at_high = float(old_rsi[old_high_idx])
        recent_rsi_at_high = float(recent_rsi[recent_high_idx])

        bearish = (
            recent_price_high > old_price_high
            and recent_rsi_at_high < old_rsi_at_high
        )

        # --- Bullish divergence (lows) ---
        old_low_idx = int(np.argmin(old_closes))
        recent_low_idx = int(np.argmin(recent_closes))
        old_price_low = float(old_closes[old_low_idx])
        recent_price_low = float(recent_closes[recent_low_idx])
        old_rsi_at_low = float(old_rsi[old_low_idx])
        recent_rsi_at_low = float(recent_rsi[recent_low_idx])

        bullish = (
            recent_price_low < old_price_low
            and recent_rsi_at_low > old_rsi_at_low
        )

        if bearish:
            rsi_gap = old_rsi_at_high - recent_rsi_at_high  # positive
            # Severity: RSI gap as fraction of 10 RSI pts, capped at 8.
            # This is a coefficient of the RSI-gap magnitude, NOT a z-divisor.
            severity_z = float(min(rsi_gap / 10.0, 8.0))  # noqa: std-floor (coefficient, not z-divisor)
            components = {
                "old_price_high": old_price_high,
                "recent_price_high": recent_price_high,
                "old_rsi_at_high": old_rsi_at_high,
                "recent_rsi_at_high": recent_rsi_at_high,
                "rsi_gap": float(rsi_gap),
            }
            reason = (
                f"bearish divergence: price high {old_price_high:.2f} → {recent_price_high:.2f} "
                f"(higher) but RSI {old_rsi_at_high:.1f} → {recent_rsi_at_high:.1f} (lower); "
                f"rsi_gap={rsi_gap:.1f} severity={severity_z:.2f}"
            )
            return EventTrigger(
                detector=self.name,
                triggered=True,
                severity_z=severity_z,
                direction="bearish",
                reason=reason,
                components=components,
                asof_date=end_date,
            )

        if bullish:
            rsi_gap = recent_rsi_at_low - old_rsi_at_low  # positive
            severity_z = float(min(rsi_gap / 10.0, 8.0))  # noqa: std-floor (coefficient, not z-divisor)
            components = {
                "old_price_low": old_price_low,
                "recent_price_low": recent_price_low,
                "old_rsi_at_low": old_rsi_at_low,
                "recent_rsi_at_low": recent_rsi_at_low,
                "rsi_gap": float(rsi_gap),
            }
            reason = (
                f"bullish divergence: price low {old_price_low:.2f} → {recent_price_low:.2f} "
                f"(lower) but RSI {old_rsi_at_low:.1f} → {recent_rsi_at_low:.1f} (higher); "
                f"rsi_gap={rsi_gap:.1f} severity={severity_z:.2f}"
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

        # Ran cleanly, no divergence found.
        components = {
            "old_price_high": old_price_high,
            "recent_price_high": recent_price_high,
            "old_rsi_at_high": old_rsi_at_high,
            "recent_rsi_at_high": recent_rsi_at_high,
            "old_price_low": old_price_low,
            "recent_price_low": recent_price_low,
            "old_rsi_at_low": old_rsi_at_low,
            "recent_rsi_at_low": recent_rsi_at_low,
        }
        reason = (
            f"no divergence: price highs {old_price_high:.2f}/{recent_price_high:.2f} "
            f"RSI@high {old_rsi_at_high:.1f}/{recent_rsi_at_high:.1f}; "
            f"price lows {old_price_low:.2f}/{recent_price_low:.2f} "
            f"RSI@low {old_rsi_at_low:.1f}/{recent_rsi_at_low:.1f}"
        )
        return EventTrigger(
            detector=self.name,
            triggered=False,
            reason=reason,
            components=components,
            asof_date=end_date,
        )
