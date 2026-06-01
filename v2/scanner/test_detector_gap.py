"""Tests for GapDetector (gap up/down).

Pattern follows test_detector_high_breakout.py: MagicMock fd with crafted Price lists.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from v2.data.models import Price
from v2.scanner.detectors.gap import GapDetector

END_DATE = "2026-05-13"
MIN_BARS = 62  # detector requires gap_window+2 = 62 price bars to build 60 gap observations


def _price(time_iso: str, open_: float, close: float, volume: int = 1_000_000) -> Price:
    return Price(
        open=open_, close=close, high=max(open_, close), low=min(open_, close),
        volume=volume, time=time_iso,
    )


def _make_prices(
    n: int,
    *,
    end: date | None = None,
    base_open: float = 100.0,
    base_close: float = 100.0,
    last_open: float | None = None,
) -> list[Price]:
    """Build a series of n bars with small identical gaps, optionally overriding today's open."""
    if end is None:
        end = date.fromisoformat(END_DATE)
    bars: list[Price] = []
    for i in range(n):
        d = end - timedelta(days=n - 1 - i)
        if i == n - 1 and last_open is not None:
            open_ = last_open
        else:
            open_ = base_open
        bars.append(_price(d.isoformat(), open_=open_, close=base_close))
    return bars


def _make_fd(prices: list[Price]) -> MagicMock:
    fd = MagicMock()
    fd.get_prices.return_value = prices
    return fd


class TestGapDetector:

    def test_big_up_gap_fires_bullish(self):
        """Last bar opens far above prior close → triggered True, bullish."""
        # 61 bars: bars 0..59 open=100, close=100 (no gap).
        # Bar 60 (today): open=115, close=100. gap_today = 115/100 - 1 = 0.15.
        # Trailing gaps for bars 1..59 are all 0.0 → gap_std = max(0.0, 0.003) = 0.003.
        # gap_z = 0.15 / 0.003 = 50 → well above default threshold of 3.0.
        n = MIN_BARS + 1  # 62 bars so we have ≥60 gap observations
        prices = _make_prices(n, last_open=115.0)
        trig = GapDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is True
        assert trig.direction == "bullish"
        assert trig.severity_z > 0.0
        assert trig.severity_z <= 8.0
        assert "gap" in trig.components
        assert "gap_z" in trig.components
        assert "gap_std" in trig.components
        assert "open_today" in trig.components
        assert "close_yesterday" in trig.components

    def test_big_down_gap_fires_bearish(self):
        """Last bar opens far below prior close → triggered True, bearish."""
        n = MIN_BARS + 1
        prices = _make_prices(n, last_open=82.0)  # gap = 82/100 - 1 = -0.18
        trig = GapDetector().detect("TSLA", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is True
        assert trig.direction == "bearish"

    def test_small_gap_does_not_fire(self):
        """Normal open (= prior close) → triggered False."""
        n = MIN_BARS + 1
        prices = _make_prices(n, base_open=100.0, base_close=100.0)
        trig = GapDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is False

    def test_empty_list_returns_none(self):
        """Empty price list → None (no data, exclude ticker)."""
        trig = GapDetector().detect("AAPL", END_DATE, _make_fd([]))
        assert trig is None

    def test_fewer_than_60_bars_returns_none(self):
        """Only 30 bars → not enough history → None."""
        n = 30
        prices = _make_prices(n)
        trig = GapDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is None

    def test_below_min_bars_returns_none(self):
        """61 bars (one below min_bars=62): cannot build 60 clean gap observations → None."""
        n = 61
        prices = _make_prices(n)
        trig = GapDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is None

    def test_degenerate_all_identical_does_not_raise(self):
        """All bars with identical open=close → gap_std hits floor; must not raise."""
        n = MIN_BARS + 1
        prices = _make_prices(n, base_open=50.0, base_close=50.0)
        try:
            trig = GapDetector().detect("AAPL", END_DATE, _make_fd(prices))
            # Must be None or an EventTrigger — never a raise.
            assert trig is None or isinstance(trig.triggered, bool)
        except Exception as exc:
            pytest.fail(f"detect() raised on degenerate input: {exc}")

    def test_fd_exception_returns_none(self):
        """fd.get_prices raising an exception → None (invariant: never re-raises)."""
        fd = MagicMock()
        fd.get_prices.side_effect = RuntimeError("network error")
        trig = GapDetector().detect("AAPL", END_DATE, fd)
        assert trig is None

    def test_severity_z_clamped_to_8(self):
        """Extreme gap → severity_z capped at 8.0."""
        n = MIN_BARS + 1
        # Massively overpriced open relative to prior close (gap = 900%).
        prices = _make_prices(n, base_open=100.0, base_close=100.0, last_open=1000.0)
        trig = GapDetector().detect("AAPL", END_DATE, _make_fd(prices))
        assert trig is not None
        assert trig.triggered is True
        assert trig.severity_z <= 8.0

    def test_retired_from_all_detectors(self):
        """gap was RETIRED 2026-06-01 (round-2): its z-scoring is broken (a 5σ
        threshold still fires ~49% of bear ticker-days) and interestingness is
        negative at every swept threshold — see findings_scanner_round2.md.
        Unregistered from ALL_DETECTORS + DETECTOR_METADATA, but the class stays
        importable and the name is accepted by config validators (RETIRED_DETECTORS)
        so old saved configs still load."""
        from v2.scanner.detectors import (
            ALL_DETECTORS,
            DETECTOR_METADATA,
            RETIRED_DETECTORS,
            GapDetector,
        )
        names = [c().name for c in ALL_DETECTORS]
        assert "gap" not in names
        assert "gap" not in DETECTOR_METADATA
        assert "gap" in RETIRED_DETECTORS
        assert GapDetector().name == "gap"  # still importable
