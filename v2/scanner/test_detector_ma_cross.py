"""Tests for MaCrossDetector (golden/death cross, SMA50 × SMA200).

Pattern follows test_detector_high_breakout.py: MagicMock fd with crafted
Price lists.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from v2.data.models import Price
from v2.scanner.detectors.ma_cross import MaCrossDetector

END_DATE = "2026-05-13"
FAST = 50
SLOW = 200
MIN_BARS = SLOW + 2  # 202


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
    """Return n consecutive ISO date strings ending at ``end``."""
    last = date.fromisoformat(end)
    return [(last - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


# ---------------------------------------------------------------------------
# Series builders
# ---------------------------------------------------------------------------

def _golden_cross_series() -> list[Price]:
    """Engineer a golden cross (SMA50 crosses ABOVE SMA200) on the last bar.

    Strategy:
    - Bars 0 .. N-FAST-2: close = 100  (long flat base — both SMAs track ~100)
    - Bars N-FAST-1 .. N-2 (yesterday): close = 100  (yesterday SMA50 ≈ 100, SMA200 ≈ 100)
    - Bar N-1 (today): close = 200

    With a large spike on today only, SMA50_today includes that spike
    (one bar of 200 out of 50 bars → SMA50 = (49*100 + 200)/50 = 102)
    while SMA200_today = (199*100 + 200)/200 = 100.5.

    But yesterday both SMAs are ~100 and equal, so we need SMA50_yest ≤ SMA200_yest
    and SMA50_today > SMA200_today.

    Better strategy: use a long declining base to push SMA200 above SMA50,
    then a sharp rally on the last bars brings SMA50 above SMA200.

    Construction:
    - Bars 0 .. N-FAST-2 (i.e., first N-FAST-1 bars): close = 80 (depressed)
    - Bars N-FAST-1 .. N-2 (next FAST-1 bars, ending yesterday): close = 120 (rally)
    - Bar N-1 (today): close = 120

    Yesterday:
      SMA50_yest  = mean(closes[-FAST-1:-1]) = mean(FAST-1 bars of 120, 1 bar of 80)
                  = (49*120 + 80) / 50 = (5880 + 80) / 50 = 5960/50 = 119.2
      SMA200_yest = mean(closes[-SLOW-1:-1]) = mean(200 bars):
                  last (FAST-1)=49 bars of 120 + (200-49)=151 bars of 80
                  = (49*120 + 151*80) / 200 = (5880 + 12080) / 200 = 17960/200 = 89.8
    → SMA50_yest (119.2) > SMA200_yest (89.8) — already crossed, NOT what we want.

    We need SMA50_yest ≤ SMA200_yest. Let's reverse: the slow MA is elevated
    due to a past high, and the fast MA is depressed due to recent lows, then
    today's fast MA jumps above the slow.

    Construction (N = MIN_BARS = 202):
    - Bars 0 .. 151 (152 bars): close = 150  ← historical high that weights SMA200
    - Bars 152 .. 199 (48 bars): close = 50   ← recent depression that drags SMA50 down
    - Bar 200 (yesterday, index 200): close = 50
    - Bar 201 (today, index 201): close = 50

    SMA50_yest  = mean(closes[201-50-1:201-1]) = mean(closes[150:200])
               = mean of bars 150..199 = bar150=150, bars 151..199=50 (49 bars of 50)
               Wait, bar 150 is close=150, bars 151..199 are 49 bars of 50.
               = (150 + 49*50) / 50 = (150 + 2450) / 50 = 2600/50 = 52.0
    SMA200_yest = mean(closes[201-200-1:201-1]) = mean(closes[0:200])
               = mean of bars 0..199 = 152 bars of 150 + 48 bars of 50
               = (152*150 + 48*50) / 200 = (22800 + 2400) / 200 = 25200/200 = 126.0
    → SMA50_yest=52 < SMA200_yest=126  ✓ (SMA50 below SMA200 yesterday)

    Now we need today to flip: SMA50_today > SMA200_today.
    Today's close must pull SMA50_today above SMA200_today.

    SMA50_today = mean(closes[152:202]) = mean of bars 152..200=50, bar201=X
              = (49*50 + X) / 50
    SMA200_today = mean(closes[2:202]) = mean of bars 2..201
               = (152-2)*150 ... actually let's recalculate from bar indices.

    bars:  0..151 = 150 (152 bars)
           152..199 = 50 (48 bars)
           200 = 50 (yesterday)
           201 = X (today)

    SMA50_today = mean(closes[202-50:202]) = mean(closes[152:202])
               = mean(bars 152..200 [50 bars of 50] + bar 201 [X])
               No: closes[152:202] is bars 152..201 inclusive (50 bars):
               48 bars of 50 (bars 152..199) + bar 200 (50) + bar 201 (X) = 49 bars of 50 + X
               = (49*50 + X) / 50

    SMA200_today = mean(closes[202-200:202]) = mean(closes[2:202])
               = bars 2..201 (200 bars):
                 bars 2..151 = 150 bars of 150
                 bars 152..199 = 48 bars of 50
                 bar 200 = 50
                 bar 201 = X
               = (150*150 + 49*50 + X) / 200
               = (22500 + 2450 + X) / 200
               = (24950 + X) / 200

    For golden cross: SMA50_today > SMA200_today
    (49*50 + X) / 50 > (24950 + X) / 200
    200 * (2450 + X) > 50 * (24950 + X)
    490000 + 200X > 1247500 + 50X
    150X > 757500
    X > 5050

    So today's close of 5050+ triggers a golden cross. Use X=6000.
    """
    n = MIN_BARS  # 202
    ds = _dates(n)
    bars: list[Price] = []
    for i, d in enumerate(ds):
        if i <= 151:
            close = 150.0
        elif i <= 200:   # bars 152..200 (yesterday)
            close = 50.0
        else:            # bar 201 (today)
            close = 6000.0
    bars = [
        _price(ds[i], 150.0 if i <= 151 else (50.0 if i <= 200 else 6000.0))
        for i in range(n)
    ]
    return bars


def _death_cross_series() -> list[Price]:
    """Engineer a death cross (SMA50 crosses BELOW SMA200) on the last bar.

    Symmetric to golden cross: start with a high fast MA, then crash it.

    bars:  0..151 = 50   (152 bars of depressed history)
           152..200 = 150 (49 bars of 150, ending at yesterday)
           201 = X today (crash)

    SMA50_yest  = mean(closes[150:200]) = bars 150..199
               bar 150 = 50, bars 151..199 = 49 bars of 150 (wait, bar 152 starts 150)
    Let me be precise:
    bars 0..151 = 50 (152 bars, indices 0 to 151)
    bars 152..200 = 150 (49 bars, indices 152 to 200 = yesterday)
    bar 201 = X (today)

    SMA50_yest  = mean(closes[201-50-1:201-1]) = mean(closes[150:200])
               = bars 150, 151 (=50) + bars 152..199 (=150, 48 bars)
               = (2*50 + 48*150) / 50 = (100 + 7200) / 50 = 7300/50 = 146.0
    SMA200_yest = mean(closes[201-200-1:201-1]) = mean(closes[0:200])
               = 152 bars of 50 + 48 bars of 150
               = (152*50 + 48*150) / 200 = (7600 + 7200) / 200 = 14800/200 = 74.0
    → SMA50_yest=146 > SMA200_yest=74  ✓ (SMA50 above SMA200 yesterday)

    Need today's SMA50 < SMA200_today.
    SMA50_today = mean(closes[152:202]) = bars 152..200 (150, 49 bars) + bar 201 (X)
               = (49*150 + X) / 50 = (7350 + X) / 50
    SMA200_today = mean(closes[2:202]) = bars 2..201
               = bars 2..151 (150 bars of 50) + bars 152..200 (49 bars of 150) + bar201 (X)
               = (150*50 + 49*150 + X) / 200 = (7500 + 7350 + X) / 200 = (14850 + X) / 200

    For death cross: SMA50_today < SMA200_today
    (7350 + X) / 50 < (14850 + X) / 200
    200*(7350 + X) < 50*(14850 + X)
    1470000 + 200X < 742500 + 50X
    150X < -727500
    X < -4850

    Prices can't be negative. This construction doesn't work for death cross.

    Alternative: start with HIGH history, then depress recently.
    bars 0..151 = 200 (152 bars of 200)
    bars 152..200 = 100 (49 bars, ending yesterday)
    bar 201 = X (today, crash)

    SMA50_yest = mean(closes[150:200]) = bars 150, 151 (=200) + bars 152..199 (=100, 48 bars)
              = (2*200 + 48*100) / 50 = (400 + 4800) / 50 = 5200/50 = 104.0
    SMA200_yest = mean(closes[0:200]) = 152*200 + 48*100 / 200 = (30400+4800)/200 = 176.0
    → SMA50_yest=104 < SMA200_yest=176  ← SMA50 already below! Wrong direction.

    We need SMA50_yest > SMA200_yest (above), then today it crosses below.

    For death cross we need a fast MA that was ABOVE the slow MA yesterday
    but drops BELOW today.

    Construction: high recent bars (pulling SMA50 up), long low history (keeping SMA200 low),
    then today's bar is extremely low, pulling SMA50 down fast.

    bars 0..151 = 50 (long depressed history, 152 bars)
    bars 152..200 = 200 (elevated recent bars, 49 bars ending yesterday)
    bar 201 = X (crash today)

    SMA50_yest = mean(closes[150:200]):
       bar 150 = 50, bar 151 = 50, bars 152..199 = 200 (48 bars)
       = (2*50 + 48*200) / 50 = (100 + 9600) / 50 = 9700/50 = 194.0
    SMA200_yest = mean(closes[0:200]):
       bars 0..151 = 50 (152 bars), bars 152..199 = 200 (48 bars)
       = (152*50 + 48*200) / 200 = (7600 + 9600) / 200 = 17200/200 = 86.0
    → SMA50_yest=194 > SMA200_yest=86  ✓

    SMA50_today = mean(closes[152:202]):
       bars 152..200 = 200 (49 bars) + bar 201 = X
       = (49*200 + X) / 50 = (9800 + X) / 50
    SMA200_today = mean(closes[2:202]):
       bars 2..151 = 50 (150 bars) + bars 152..200 = 200 (49 bars) + bar 201 = X
       = (150*50 + 49*200 + X) / 200 = (7500 + 9800 + X) / 200 = (17300 + X) / 200

    For death cross: SMA50_today < SMA200_today
    (9800 + X) / 50 < (17300 + X) / 200
    200*(9800 + X) < 50*(17300 + X)
    1960000 + 200X < 865000 + 50X
    150X < -1095000
    X < -7300  ← still negative. Prices can't be negative.

    The issue: when SMA50_yest > SMA200_yest by a wide margin, pulling SMA50
    below SMA200 in one day requires a very negative price.

    Solution: use a narrower spread so the cross happens with a valid low price.

    Smaller spread construction for death cross:
    bars 0..151 = 95   (depressed history, 152 bars)
    bars 152..200 = 105 (modest elevation, 49 bars)
    bar 201 = X today

    SMA50_yest = (2*95 + 48*105) / 50 = (190 + 5040) / 50 = 5230/50 = 104.6
    SMA200_yest = (152*95 + 48*105) / 200 = (14440 + 5040) / 200 = 19480/200 = 97.4
    → SMA50_yest=104.6 > SMA200_yest=97.4 ✓

    SMA50_today = (49*105 + X) / 50 = (5145 + X) / 50
    SMA200_today = (150*95 + 49*105 + X) / 200 = (14250 + 5145 + X) / 200 = (19395 + X) / 200

    Death cross: (5145 + X)/50 < (19395 + X)/200
    200*(5145+X) < 50*(19395+X)
    1029000 + 200X < 969750 + 50X
    150X < -59250
    X < -395 ← still negative.

    The math: for death cross via a one-day crash, we need X < 0. That means
    prices must go negative, which is impossible.

    Alternative: use more bars in the "elevated recent" window to give SMA50
    more 200-level bars it can lose quickly.

    Actually the clean approach: mirror the golden-cross construction but flip.
    For golden cross we had a large POSITIVE spike. For death cross, use a
    long high history (which SMA200 captures) and a recent dive (SMA50 tracks
    the dive and is already below SMA200 yesterday), then today we need SMA50
    to have been ABOVE SMA200 yesterday and cross below today.

    The root issue: for death cross via a single-day crash, we need to move
    SMA50 down dramatically, but that requires negative prices.

    Alternative: use multiple days of declining prices ending in a cross.
    But we only control the last bar (today).

    REAL SOLUTION: Pre-arrange so that yesterday's SMA50 is only SLIGHTLY above
    SMA200, so a modest price decline today crosses them.

    bars 0..151 = 100.0 (152 bars)
    bars 152..199 = 101.0 (48 bars — yesterday is bar 200)
    bar 200 = 101.0 (yesterday)
    bar 201 = X (today)

    SMA50_yest = mean(closes[150:200]):
       bars 150, 151 = 100 (2 bars), bars 152..199 = 101 (48 bars)
       = (2*100 + 48*101) / 50 = (200 + 4848) / 50 = 5048/50 = 100.96
    SMA200_yest = mean(closes[0:200]):
       bars 0..151 = 100 (152 bars), bars 152..199 = 101 (48 bars)
       = (152*100 + 48*101) / 200 = (15200 + 4848) / 200 = 20048/200 = 100.24
    → SMA50_yest=100.96 > SMA200_yest=100.24 ✓ (narrow margin)

    SMA50_today = mean(closes[152:202]):
       bars 152..200 = 101 (49 bars) + bar 201 = X
       = (49*101 + X) / 50 = (4949 + X) / 50
    SMA200_today = mean(closes[2:202]):
       bars 2..151 = 100 (150 bars), bars 152..200 = 101 (49 bars), bar 201 = X
       = (150*100 + 49*101 + X) / 200 = (15000 + 4949 + X) / 200 = (19949 + X) / 200

    Death cross: SMA50_today < SMA200_today
    (4949+X)/50 < (19949+X)/200
    200*(4949+X) < 50*(19949+X)
    989800+200X < 997450+50X
    150X < 7650
    X < 51.0

    So today's close of < 51 causes a death cross! Use X=1.0 (extreme crash).
    Let's verify: X=1.0
    SMA50_today = (4949+1)/50 = 4950/50 = 99.0
    SMA200_today = (19949+1)/200 = 19950/200 = 99.75
    SMA50_today=99.0 < SMA200_today=99.75 ✓  DEATH CROSS!
    """
    n = MIN_BARS  # 202
    ds = _dates(n)
    bars = [
        _price(
            ds[i],
            100.0 if i <= 151 else (101.0 if i <= 200 else 1.0)
        )
        for i in range(n)
    ]
    return bars


def _no_cross_series() -> list[Price]:
    """Steadily uptrending series with no MA cross at the boundary.

    SMA50 consistently above SMA200 throughout, and both yesterday and
    today show SMA50 > SMA200, so no cross.

    bars 0..151: linearly rising from 100 to 150 (fast MA well above slow)
    bars 152..201: continue rising ~151..160

    With SMA50 > SMA200 at both yesterday and today and no direction change,
    no cross fires. Just use a simple ascending series.
    """
    n = MIN_BARS  # 202
    ds = _dates(n)
    bars = [_price(ds[i], float(100 + i)) for i in range(n)]
    return bars


def _insufficient_bars_series(n: int = 10) -> list[Price]:
    """Only n bars — far below MIN_BARS=202."""
    ds = _dates(n)
    return [_price(ds[i], 100.0) for i in range(n)]


def _degenerate_identical_series() -> list[Price]:
    """All identical closes — SMA50 == SMA200 always, no strict cross."""
    n = MIN_BARS
    ds = _dates(n)
    return [_price(ds[i], 100.0) for i in range(n)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMaCrossDetector:

    def test_golden_cross_fires_bullish(self):
        """SMA50 crosses ABOVE SMA200 on today's bar → triggered True, bullish."""
        prices = _golden_cross_series()
        trig = MaCrossDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z == 2.0
        assert "sma_fast_today" in trig.components
        assert "sma_slow_today" in trig.components
        assert "sma_fast_yest" in trig.components
        assert "sma_slow_yest" in trig.components

    def test_death_cross_fires_bearish(self):
        """SMA50 crosses BELOW SMA200 on today's bar → triggered True, bearish."""
        prices = _death_cross_series()
        trig = MaCrossDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is True
        assert trig.direction == "bearish"
        assert trig.severity_z == 2.0

    def test_no_cross_returns_triggered_false(self):
        """Steadily trending series with no cross at boundary → triggered False."""
        prices = _no_cross_series()
        trig = MaCrossDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is False

    def test_insufficient_bars_returns_none(self):
        """Fewer than 202 bars → None (no data, exclude from stats)."""
        prices = _insufficient_bars_series(10)
        trig = MaCrossDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is None

    def test_empty_list_returns_none(self):
        """Empty price list → None."""
        trig = MaCrossDetector().detect("AAPL", END_DATE, _make_fd([]))
        assert trig is None

    def test_degenerate_identical_does_not_raise(self):
        """All identical closes (SMA50 == SMA200 always) must NOT raise.

        No strict cross → triggered False or None; just must not raise.
        """
        prices = _degenerate_identical_series()
        try:
            trig = MaCrossDetector().detect("AAPL", END_DATE, _make_fd(prices))
            assert trig is None or isinstance(trig.triggered, bool)
        except Exception as exc:
            pytest.fail(f"detect() raised on degenerate input: {exc}")

    def test_registration_in_all_detectors(self):
        """ma_cross must appear in ALL_DETECTORS and DETECTOR_METADATA."""
        from v2.scanner.detectors import ALL_DETECTORS, DETECTOR_METADATA
        names = [c().name for c in ALL_DETECTORS]
        assert "ma_cross" in names
        assert "ma_cross" in DETECTOR_METADATA

    def test_components_keys_present_on_triggered_false(self):
        """triggered=False result still carries all four SMA components."""
        prices = _no_cross_series()
        trig = MaCrossDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        for key in ("sma_fast_today", "sma_slow_today", "sma_fast_yest", "sma_slow_yest"):
            assert key in trig.components, f"Missing component: {key}"
