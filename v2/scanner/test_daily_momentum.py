"""Deterministic daily-bar detector coverage; no provider/network calls."""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from v2.data.models import Price
from v2.scanner.detectors import ALL_DETECTORS, DETECTOR_METADATA
from v2.scanner.detectors.daily_momentum import (
    RelativeVolumeDetector, RangeBreakoutDetector, RelativeStrengthDetector,
)
from v2.scanner.models import ScannerWeights
from v2.scanner.runner import run_scan

END = "2026-10-30"
CLASSES = [RelativeVolumeDetector, RangeBreakoutDetector, RelativeStrengthDetector]


def bars(last=110, volume=200, n=21):
    start = date.fromisoformat(END) - timedelta(days=n - 1)
    return [Price(time=(start + timedelta(days=i)).isoformat(), open=100,
                  high=120, low=80, close=last if i == n - 1 else 100,
                  volume=volume if i == n - 1 else 100) for i in range(n)]


def client(stock=None, spy=None):
    fd = MagicMock()
    stock = bars() if stock is None else stock
    spy = bars(last=100) if spy is None else spy
    fd.get_prices.side_effect = lambda ticker, *_: spy if ticker == "SPY" else stock
    fd.evidence = []
    fd.quality = []
    return fd


@pytest.mark.parametrize("cls", CLASSES)
def test_registered_and_validated(cls):
    assert cls in ALL_DETECTORS
    assert cls.name in DETECTOR_METADATA
    assert ScannerWeights(enabled_detectors=[cls.name]).enabled_detectors == [cls.name]


@pytest.mark.parametrize("cls", CLASSES)
@pytest.mark.parametrize("failure", ["empty", "short", "error", "invalid"])
def test_missing_data(cls, failure):
    stock = [] if failure == "empty" else bars(n=5) if failure == "short" else bars()
    if failure == "invalid":
        stock[-1].adjusted_close = float("nan")
    fd = client(stock)
    if failure == "error":
        fd.get_prices.side_effect = RuntimeError("provider unavailable")
    assert cls().detect("AAPL", END, fd) is None


@pytest.mark.parametrize("cls", CLASSES)
@pytest.mark.parametrize("last,direction", [(110, "bullish"), (90, "bearish")])
def test_direction_and_signed_severity(cls, last, direction):
    result = cls().detect("AAPL", END, client(bars(last=last)))
    assert result.triggered
    assert result.direction == direction
    assert (result.severity_z > 0) == (direction == "bullish")


@pytest.mark.parametrize("cls", CLASSES)
def test_no_event_is_distinct_from_no_data(cls):
    result = cls().detect("AAPL", END, client(bars(last=100, volume=100)))
    assert result is not None and not result.triggered


def test_volume_baseline_excludes_current_and_does_not_exclude_price_moves():
    result = RelativeVolumeDetector().detect("AAPL", END, client())
    assert result.triggered
    assert result.components["relative_volume"] == 2
    assert result.components["baseline_volume"] == 100


def test_flat_volume_is_neutral_and_zero_baseline_is_missing():
    result = RelativeVolumeDetector().detect("AAPL", END, client(bars(last=100)))
    assert result.triggered and result.direction == "neutral"
    assert result.severity_z == 0
    stock = bars()
    for p in stock[:-1]:
        p.volume = 0
    assert RelativeVolumeDetector().detect("AAPL", END, client(stock)) is None


def test_breakout_uses_adjusted_closes_not_raw_highs():
    stock = bars(last=50)
    for p in stock[:-1]:
        p.adjusted_close = 50
    result = RangeBreakoutDetector().detect("AAPL", END, client(stock))
    assert not result.triggered  # split is not a bearish breakout
    stock[-1].adjusted_close = 51
    result = RangeBreakoutDetector().detect("AAPL", END, client(stock))
    assert result.triggered and result.direction == "bullish"
    assert result.components["prior_high_close"] == 50


@pytest.mark.parametrize("cls", CLASSES)
def test_future_bars_excluded_and_unsorted_input_supported(cls):
    stock = bars()
    future = stock[-1].model_copy(update={"time": "2026-11-02", "close": 1, "volume": 0})
    result = cls().detect("AAPL", END, client(list(reversed(stock + [future]))))
    assert result.triggered and result.direction == "bullish"
    assert result.asof_date == END


def test_asof_is_actual_bar_date_on_weekend():
    result = RangeBreakoutDetector().detect("AAPL", "2026-10-31", client())
    assert result.asof_date == END


@pytest.mark.parametrize("spy", [[], bars()[:-1], bars(n=5)])
def test_relative_strength_requires_current_benchmark(spy):
    assert RelativeStrengthDetector().detect("AAPL", END, client(spy=spy)) is None


def test_relative_strength_requires_same_sessions():
    stock = bars(n=22)
    del stock[-5]
    assert RelativeStrengthDetector().detect("AAPL", END, client(stock)) is None


def test_relative_strength_measures_spread_not_absolute_return():
    result = RelativeStrengthDetector().detect("AAPL", END, client(spy=bars(last=108)))
    assert not result.triggered
    assert result.components["return_spread"] == pytest.approx(.02)
    result = RelativeStrengthDetector().detect("AAPL", END, client(bars(last=95), bars(last=85)))
    assert result.triggered and result.direction == "bullish"


def test_custom_windows_and_thresholds():
    fd = client(bars(n=6, volume=150), bars(n=6, last=100))
    assert RelativeVolumeDetector(window=5, threshold=1.5).detect("AAPL", END, fd).triggered
    assert RangeBreakoutDetector(window=5).detect("AAPL", END, fd).triggered
    assert not RelativeStrengthDetector(window=5, threshold=.2).detect("AAPL", END, fd).triggered


def test_scan_runner_scores_and_serializes_new_detectors():
    results = run_scan(
        tickers=["AAPL"], end_date=END, detectors=[cls() for cls in CLASSES],
        provider_factory=client, benchmark_ticker=None, max_workers=1,
    )
    assert len(results) == 1
    assert results[0].direction == "bullish"
    assert results[0].composite_score > 0
    assert {t["detector"] for t in results[0].triggers} == {cls.name for cls in CLASSES}
