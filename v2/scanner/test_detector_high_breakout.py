"""Tests for HighBreakoutDetector (52-week-high breakout).

Pattern follows test_detectors.py: MagicMock fd with crafted Price lists.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from v2.data.models import Price
from v2.scanner.detectors.high_breakout import HighBreakoutDetector

END_DATE = "2026-05-13"
WINDOW = 252


def _price(time_iso: str, close: float, volume: int = 1_000_000) -> Price:
    return Price(
        open=close, close=close, high=close, low=close,
        volume=volume, time=time_iso,
    )


def _prices_rising_to_new_high(*, n_bars: int = WINDOW + 5) -> list[Price]:
    """Rising series — last bar is a fresh all-time high NOT seen yesterday.

    Bars 0 … n_bars-2 go from 90 → 99 (strictly increasing).
    Bar n_bars-1 (today) goes to 101 — above the prior window max of 99.
    Bar n_bars-2 (yesterday) = 99, which is *equal* to the prior-window max
    up to yesterday, so yesterday was already AT the high; we need to ensure
    yesterday's prior-window max (bars 0 … n_bars-3) is < 99 so the gate
    treats yesterday as NOT having broken.

    Simpler construction: bars are 90, 91, …, 98, 99 (yesterday), 101 (today).
    Prior window max up to yesterday (bars [0..-2]) = 99 (the bar two positions
    back from today is actually yesterday … let's be explicit):

    bar index: 0  1  2  ... n-3   n-2(yesterday)  n-1(today)
    close:     90 90 90 ...  98          99           101

    prior_max_today  = max(bars[n-1-WINDOW : n-1]) = max(90..99) = 99
    close_today = 101 >= 99 → gate 1 passes
    prior_max_yest   = max(bars[n-2-WINDOW : n-2]) = max(90..98) = 98
    close_yesterday = 99 < 98? NO! 99 >= 98, so yesterday would ALSO fire.

    We need a construction where close_yesterday < prior_max_yesterday.
    Set all bars except the last to 100, then today = 101. Yesterday = 100.
    Prior window max (excluding today) = 100. close_yesterday (100) NOT < 100.
    Still doesn't work.

    The correct construction:
    - All bars = 100 except today = 101.
    - prior_max_today   = max of 252 closes [yesterday and before] = 100
    - close_today = 101 >= 100 → gate 1 passes
    - prior_max_yest    = max of 252 closes [two-days-ago and before] = 100
    - close_yesterday = 100, which is NOT < 100 → first-day gate fails (already at high).

    So the only clean construction for "first-day break" is a flat history
    followed by a jump that skips over the previous max:

    bars 0 … n-2: close = 100  (all flat)
    bar n-1 (today): close = 101

    prior_max_today = max(bars[n-1-WINDOW : n-1]) = 100; 101 >= 100 ✓
    prior_max_yest  = max(bars[n-2-WINDOW : n-2]) = 100; close_yest = 100 NOT < 100 ✗

    Still fails. We need yesterday's close to be BELOW the prior-window max.
    That means yesterday's close must be strictly less than the prior-window
    max INCLUDING yesterday, but that's impossible if yesterday is flat and
    all bars are 100.

    The real pattern: the prior-window max as of yesterday must be set by some
    bar BEFORE yesterday, and yesterday's close must be below that bar.
    Then today breaks it.

    Construction:
    - bars 0 … n-3: close = 105 (historic high, well in the 252-bar window)
    - bar n-2 (yesterday): close = 99 (recent pullback)
    - bar n-1 (today): close = 106 (breaks above the 105 high)

    prior_max_today = max(105…105, 99) = 105; close_today=106 >= 105 ✓
    prior_max_yest  = max(105…105) = 105; close_yesterday=99 < 105 ✓  FIRES!
    """
    end = date.fromisoformat(END_DATE)
    bars: list[Price] = []
    # Total bars: window + 5 (some buffer)
    total = n_bars
    for i in range(total):
        d = end - timedelta(days=total - 1 - i)
        if i < total - 2:
            close = 105.0  # historic plateau
        elif i == total - 2:
            close = 99.0   # pullback yesterday
        else:
            close = 106.0  # breaks above 105 today
        bars.append(_price(d.isoformat(), close=close))
    return bars


def _prices_already_at_high_yesterday(*, n_bars: int = WINDOW + 5) -> list[Price]:
    """Series where BOTH today and yesterday are above the prior-window max.
    The first-day gate blocks re-fire.

    bars 0 … n-4: close=100 (historic)
    bar n-3: close=110 (prior high set here — before yesterday)
    bar n-2 (yesterday): close=111 (already broke above 110)
    bar n-1 (today):    close=112 (another new high — but not the FIRST day)

    prior_max_today = max(100..100, 110, 111) = 111; close_today=112 >= 111 ✓
    prior_max_yest  = max(100..100, 110) = 110; close_yesterday=111 >= 110 ✓
    So yesterday ALSO would have fired → first-day gate blocks today.
    """
    end = date.fromisoformat(END_DATE)
    bars: list[Price] = []
    total = n_bars
    for i in range(total):
        d = end - timedelta(days=total - 1 - i)
        if i < total - 3:
            close = 100.0
        elif i == total - 3:
            close = 110.0   # a prior high
        elif i == total - 2:
            close = 111.0   # yesterday already broke above it
        else:
            close = 112.0   # today also above — not first day
        bars.append(_price(d.isoformat(), close=close))
    return bars


def _prices_mid_range_flat(*, n_bars: int = WINDOW + 5) -> list[Price]:
    """Flat price series — close never approaches the window max."""
    end = date.fromisoformat(END_DATE)
    bars: list[Price] = []
    total = n_bars
    for i in range(total):
        d = end - timedelta(days=total - 1 - i)
        bars.append(_price(d.isoformat(), close=100.0))
    return bars


def _make_fd(prices: list[Price]) -> MagicMock:
    fd = MagicMock()
    fd.get_prices.return_value = prices
    return fd


class TestHighBreakoutDetector:

    def test_fires_on_fresh_new_high(self):
        """Rising series hits all-time high on the last bar → triggered True, bullish."""
        prices = _prices_rising_to_new_high()
        trig = HighBreakoutDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z >= 0.0
        assert "prior_max" in trig.components
        assert "close_today" in trig.components
        assert "ret_std" in trig.components

    def test_not_first_day_does_not_fire(self):
        """Yesterday also broke above prior max → not the first day → triggered False."""
        prices = _prices_already_at_high_yesterday()
        trig = HighBreakoutDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is False

    def test_mid_range_flat_does_not_fire(self):
        """Flat series — today's close equals the prior-window max (not strictly greater)
        → triggered False."""
        prices = _prices_mid_range_flat()
        trig = HighBreakoutDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is False

    def test_empty_list_returns_none(self):
        """Empty price list → None (no data, exclude ticker from stats)."""
        trig = HighBreakoutDetector().detect("AAPL", END_DATE, _make_fd([]))
        assert trig is None

    def test_insufficient_bars_returns_none(self):
        """Fewer than window+2 bars → None."""
        # Only 10 bars — way below window+2=254
        end = date.fromisoformat(END_DATE)
        prices = [_price((end - timedelta(days=10 - i)).isoformat(), 100.0) for i in range(10)]
        trig = HighBreakoutDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is None

    def test_degenerate_identical_prices_does_not_raise(self):
        """All identical closes (std=0) must NOT raise — returns None or triggered=False."""
        end = date.fromisoformat(END_DATE)
        prices = [
            _price((end - timedelta(days=WINDOW + 5 - i)).isoformat(), 50.0)
            for i in range(WINDOW + 5)
        ]
        try:
            trig = HighBreakoutDetector().detect("AAPL", END_DATE, _make_fd(prices))
            # Must be either None or a non-raising EventTrigger
            assert trig is None or isinstance(trig.triggered, bool)
        except Exception as exc:
            pytest.fail(f"detect() raised on degenerate input: {exc}")

    def test_severity_z_clamped_to_8(self):
        """Extreme breakout → severity_z capped at 8.0."""
        end = date.fromisoformat(END_DATE)
        # All bars at 100, today at 10000 (massive jump; ret_std will use floor)
        bars: list[Price] = []
        for i in range(WINDOW + 5):
            d = end - timedelta(days=WINDOW + 5 - i)
            close = 100.0 if i < WINDOW + 4 else 10000.0
            bars.append(_price(d.isoformat(), close=close))
        # Make yesterday's close lower than prior max so the gate fires
        # All bars before today: 100. Yesterday also at 100 (< max? max of prior window
        # is 100 = yesterday, so yesterday NOT < prior_max → gate might not fire).
        # Let's build it differently: bars 0..n-3 = 100, bar n-2 (yesterday)=90, today=10000
        bars2: list[Price] = []
        total = WINDOW + 5
        for i in range(total):
            d = end - timedelta(days=total - 1 - i)
            if i < total - 2:
                close = 100.0
            elif i == total - 2:
                close = 90.0  # yesterday pulled back
            else:
                close = 10000.0  # today massive breakout
            bars2.append(_price(d.isoformat(), close=close))
        trig = HighBreakoutDetector().detect("AAPL", END_DATE, _make_fd(bars2))
        assert trig is not None
        assert trig.triggered is True
        assert trig.severity_z <= 8.0

    def test_registration_in_all_detectors(self):
        """high_breakout must appear in ALL_DETECTORS and DETECTOR_METADATA."""
        from v2.scanner.detectors import ALL_DETECTORS, DETECTOR_METADATA
        names = [c().name for c in ALL_DETECTORS]
        assert "high_breakout" in names
        assert "high_breakout" in DETECTOR_METADATA
