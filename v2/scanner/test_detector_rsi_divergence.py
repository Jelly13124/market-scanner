"""Tests for RsiDivergenceDetector (price-vs-RSI divergence).

Pattern follows test_detector_high_breakout.py: MagicMock fd with crafted Price lists.

Test construction notes
-----------------------
Crafting a series that produces a known RSI is fiddly because Wilder smoothing
is recursive and the RSI at any bar depends on all prior deltas. The approach
here is to construct price series whose RSI behavior is unambiguous in direction
even if exact RSI values are not pinned:

*  Bearish divergence test: a two-phase series where:
   - Phase 1 (old half): price at moderate level, then a big up-move to a local
     high. The big move generates a large gain → high RSI.
   - Phase 2 (recent half): price drifts down from that high, then one final
     jump to a HIGHER price-high than phase 1, but the RSI at that new high is
     lower than the phase-1 RSI because the prior history now has many down-days
     dampening the Wilder gain average.
   → result: recent_price_high > old_price_high AND recent_rsi_at_high < old_rsi_at_high.

*  Bullish divergence test: mirror — price makes a lower low recently but RSI
   at that low is higher than at the older low (because prior history has many
   up-days dampening the Wilder loss average).

*  No-divergence test: clean uptrend where both price and RSI make higher highs
   in the recent half → triggered=False.

*  Edge cases: empty / < min bars → None; flat (degenerate) → no raise.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest

from v2.data.models import Price
from v2.scanner.detectors.rsi_divergence import RsiDivergenceDetector

END_DATE = "2026-05-13"
# Min bars: 14 (RSI warmup) + 40 (divergence window) + 1 extra = 55.
MIN_BARS = 55


def _price(time_iso: str, close: float, volume: int = 1_000_000) -> Price:
    return Price(
        open=close, close=close, high=close, low=close,
        volume=volume, time=time_iso,
    )


def _make_fd(prices: list[Price]) -> MagicMock:
    fd = MagicMock()
    fd.get_prices.return_value = prices
    return fd


def _dates(n: int, end: str = END_DATE) -> list[str]:
    """Generate n consecutive ISO date strings ending at end."""
    end_d = date.fromisoformat(end)
    return [(end_d - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _wilder_rsi(closes: list[float], period: int = 14) -> list[float]:
    """Reference Wilder RSI implementation for test construction validation.

    Returns a full list of RSI values (NaN for first ``period`` entries).
    """
    n = len(closes)
    rsi = [float("nan")] * n
    if n <= period:
        return rsi

    gains = []
    losses = []
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    # Seed: simple average of first ``period`` deltas.
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    rsi[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rsi[i] = _rsi_from(avg_gain, avg_loss)

    return rsi


# ---------------------------------------------------------------------------
# Series factories
# ---------------------------------------------------------------------------

def _series_bearish_divergence(n: int = 80) -> list[Price]:
    """Price makes a higher high in recent half; RSI makes a lower high.

    Construction:
    - Bars 0 … n//2-1 (old half): start at 100, drift slightly down then spike
      to 110 in one bar.  The spike is a fresh strong gain → high RSI.
    - Bars n//2 … n-1 (recent half): comes back down from 110 to ~102, then
      climbs to 115 (new higher price-high) via many small steps — many small
      gains → Wilder gain avg is lower than the single big spike, so RSI at 115
      is below RSI at 110.
    """
    closes: list[float] = []

    half = n // 2

    # Old half: flat at 100 for most of the period, then spike to 110 on the last bar.
    # Flat bars → RSI near 50. Spike → RSI shoots up (many prior neutral days → avg_loss
    # has accumulated some value; the single +10 pushes gain sharply).
    for i in range(half - 1):
        closes.append(100.0)
    closes.append(110.0)  # spike: old price high

    # Recent half: drop back from 110, then climb slowly to 115.
    # Drop first: creates losses that dilute future Wilder gain average.
    drop_bars = half // 3
    recover_bars = half - drop_bars
    for i in range(drop_bars):
        closes.append(110.0 - (i + 1) * (8.0 / drop_bars))  # falls to ~102

    # Gradual climb from ~102 to 115 over recover_bars bars.
    start_val = closes[-1]
    for i in range(recover_bars):
        closes.append(start_val + (i + 1) * ((115.0 - start_val) / recover_bars))

    assert len(closes) == n, f"Expected {n} bars, got {len(closes)}"

    # Verify the divergence holds in the reference RSI.
    rsi_vals = _wilder_rsi(closes)
    half_idx = half - 1  # index of old price high (closes[half-1] = 110)
    recent_high_idx = len(closes) - 1  # last bar = 115

    rsi_at_old = rsi_vals[half_idx]
    rsi_at_recent = rsi_vals[recent_high_idx]

    # Both RSI values must be valid (not NaN) for the divergence check to work.
    assert not (rsi_at_old != rsi_at_old), f"RSI at old high is NaN (half_idx={half_idx})"
    assert not (rsi_at_recent != rsi_at_recent), f"RSI at recent high is NaN"

    # The divergence condition: price higher, RSI lower.
    # If this assertion fails, the series construction needs tuning.
    assert closes[recent_high_idx] > closes[half_idx], (
        f"Price condition not met: {closes[recent_high_idx]:.2f} <= {closes[half_idx]:.2f}"
    )
    assert rsi_at_recent < rsi_at_old, (
        f"RSI divergence not met: recent RSI {rsi_at_recent:.1f} >= old RSI {rsi_at_old:.1f}"
    )

    dates = _dates(n)
    return [_price(d, c) for d, c in zip(dates, closes)]


def _series_bullish_divergence(n: int = 80) -> list[Price]:
    """Price makes a lower low in recent half; RSI makes a higher low.

    Construction (mirror of bearish):
    - Old half: flat at 100, then spike DOWN to 90 on last bar → big loss → low RSI.
    - Recent half: bounce back to ~98, then drop gradually to 85 (lower price low)
      via many small steps → Wilder loss avg is lower → RSI at 85 is higher than RSI at 90.
    """
    closes: list[float] = []
    half = n // 2

    # Old half: flat at 100, then drop to 90.
    for i in range(half - 1):
        closes.append(100.0)
    closes.append(90.0)  # spike down: old price low

    # Recent half: bounce back to ~98, then gradually fall to 85.
    bounce_bars = half // 3
    decline_bars = half - bounce_bars
    for i in range(bounce_bars):
        closes.append(90.0 + (i + 1) * (8.0 / bounce_bars))  # rises to ~98

    start_val = closes[-1]
    for i in range(decline_bars):
        closes.append(start_val - (i + 1) * ((start_val - 85.0) / decline_bars))

    assert len(closes) == n, f"Expected {n} bars, got {len(closes)}"

    rsi_vals = _wilder_rsi(closes)
    half_idx = half - 1
    recent_low_idx = len(closes) - 1

    rsi_at_old = rsi_vals[half_idx]
    rsi_at_recent = rsi_vals[recent_low_idx]

    assert not (rsi_at_old != rsi_at_old), "RSI at old low is NaN"
    assert not (rsi_at_recent != rsi_at_recent), "RSI at recent low is NaN"

    assert closes[recent_low_idx] < closes[half_idx], (
        f"Price condition not met: {closes[recent_low_idx]:.2f} >= {closes[half_idx]:.2f}"
    )
    assert rsi_at_recent > rsi_at_old, (
        f"RSI divergence not met: recent RSI {rsi_at_recent:.1f} <= old RSI {rsi_at_old:.1f}"
    )

    dates = _dates(n)
    return [_price(d, c) for d, c in zip(dates, closes)]


def _series_no_divergence(n: int = 80) -> list[Price]:
    """Clean uptrend — price AND RSI both higher in recent half. No divergence."""
    # Slow, steady climb: 100 → 130. Each step is uniform → RSI stays high.
    closes = [100.0 + i * (30.0 / (n - 1)) for i in range(n)]
    dates = _dates(n)
    return [_price(d, c) for d, c in zip(dates, closes)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRsiDivergenceDetector:

    def test_bearish_divergence_fires(self):
        """Crafted series: recent price-high > old, RSI lower → triggered=True, direction=bearish."""
        prices = _series_bearish_divergence(n=80)
        det = RsiDivergenceDetector()
        trig = det.detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None, "Expected EventTrigger, got None"
        assert trig.triggered is True, f"Expected triggered=True, reason: {trig.reason}"
        assert trig.direction == "bearish", f"Expected direction=bearish, got {trig.direction}"
        assert trig.severity_z > 0.0
        assert trig.severity_z <= 8.0
        # Components must include the extrema used.
        assert "old_price_high" in trig.components
        assert "recent_price_high" in trig.components
        assert "old_rsi_at_high" in trig.components
        assert "recent_rsi_at_high" in trig.components

    def test_bullish_divergence_fires(self):
        """Crafted series: recent price-low < old, RSI higher → triggered=True, direction=bullish."""
        prices = _series_bullish_divergence(n=80)
        det = RsiDivergenceDetector()
        trig = det.detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None, "Expected EventTrigger, got None"
        assert trig.triggered is True, f"Expected triggered=True, reason: {trig.reason}"
        assert trig.direction == "bullish", f"Expected direction=bullish, got {trig.direction}"
        assert trig.severity_z > 0.0
        assert trig.severity_z <= 8.0
        assert "old_price_low" in trig.components
        assert "recent_price_low" in trig.components
        assert "old_rsi_at_low" in trig.components
        assert "recent_rsi_at_low" in trig.components

    def test_no_divergence_returns_triggered_false(self):
        """Clean uptrend — price + RSI both make higher highs → triggered=False."""
        prices = _series_no_divergence(n=80)
        det = RsiDivergenceDetector()
        trig = det.detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None, "Expected EventTrigger (triggered=False), got None"
        assert trig.triggered is False, f"Expected triggered=False, reason: {trig.reason}"

    def test_empty_list_returns_none(self):
        """Empty price list → None (no data, exclude from stats)."""
        trig = RsiDivergenceDetector().detect("AAPL", END_DATE, _make_fd([]))
        assert trig is None

    def test_insufficient_bars_returns_none(self):
        """Fewer than MIN_BARS → None."""
        dates = _dates(10)
        prices = [_price(d, 100.0) for d in dates]
        trig = RsiDivergenceDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is None

    def test_degenerate_flat_does_not_raise(self):
        """All identical closes (flat) → no raise; returns None or triggered=False."""
        dates = _dates(MIN_BARS + 10)
        prices = [_price(d, 50.0) for d in dates]
        try:
            trig = RsiDivergenceDetector().detect("AAPL", END_DATE, _make_fd(prices))
            assert trig is None or isinstance(trig.triggered, bool)
        except Exception as exc:
            pytest.fail(f"detect() raised on degenerate flat input: {exc}")

    def test_registration_in_all_detectors(self):
        """rsi_divergence must appear in ALL_DETECTORS and DETECTOR_METADATA."""
        from v2.scanner.detectors import ALL_DETECTORS, DETECTOR_METADATA
        names = [c().name for c in ALL_DETECTORS]
        assert "rsi_divergence" in names
        assert "rsi_divergence" in DETECTOR_METADATA
