"""Daily-bar volume, closing-range breakout and SPY-relative momentum.

These are daily conditions, not first-occurrence alerts. Bars after the
requested date are excluded; asof_date identifies the actual last bar used.
Severity uses explicit ratio/percentage scales, not statistical z-scores.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from math import isfinite

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, close_of, parse_date
from v2.scanner.models import ScanContext

logger = logging.getLogger(__name__)


def _daily_bars(fd, ticker, end_date, window):
    end = parse_date(end_date)
    if end is None:
        return []
    start = (end - timedelta(days=max(90, window * 3))).isoformat()
    try:
        bars = fd.get_prices(ticker, start, end_date)
    except Exception as error:
        logger.debug("Daily bars unavailable for %s: %s", ticker, type(error).__name__)
        return []
    return sorted(
        (p for p in (bars or []) if start <= p.time[:10] <= end.isoformat()),
        key=lambda p: p.time[:10],
    )


def _closes(bars):
    values = [close_of(p) for p in bars]
    if any(c is None or not isfinite(c) or c <= 0 for c in values):
        return None
    return values


class RelativeVolumeDetector(EventDetector):
    """Volume >= 2x preceding 20-bar mean, with direction from daily return."""

    name = "relative_volume"

    def __init__(self, *, window: int = 20, threshold: float = 2.0):
        if window < 1 or not isfinite(threshold) or threshold <= 1:
            raise ValueError("window must be positive and threshold must exceed 1")
        self.window = window
        self.threshold = threshold

    def detect(self, ticker: str, end_date: str, fd: DataClient, *,
               ctx: ScanContext | None = None) -> EventTrigger | None:
        bars = _daily_bars(fd, ticker, end_date, self.window)[-(self.window + 1):]
        if len(bars) < self.window + 1:
            return None
        closes = _closes(bars[-2:])
        volumes = [float(p.volume) for p in bars]
        if closes is None or any(not isfinite(v) or v < 0 for v in volumes):
            return None
        baseline = sum(volumes[:-1]) / self.window
        if baseline <= 0:
            return None
        ratio = volumes[-1] / baseline
        daily_return = closes[-1] / closes[-2] - 1
        hit = ratio >= self.threshold
        direction = "bullish" if daily_return > 0 else "bearish" if daily_return < 0 else "neutral"
        # A flat-price volume event has no directional vote in composite scoring.
        sign = 1 if daily_return > 0 else -1 if daily_return < 0 else 0
        return EventTrigger(
            detector=self.name, triggered=hit,
            severity_z=sign * min(ratio, 5.0) if hit else 0.0,
            direction=direction if hit else "neutral",
            reason=f"Volume {ratio:.2f}x prior {self.window}-bar mean (threshold {self.threshold:g}x); daily return {daily_return:+.2%}",
            components={"relative_volume": ratio, "baseline_volume": baseline,
                        "today_volume": volumes[-1], "daily_return": daily_return},
            asof_date=bars[-1].time[:10],
        )


class RangeBreakoutDetector(EventDetector):
    """Close strictly outside preceding N adjusted closes, excluding today."""

    name = "range_breakout"

    def __init__(self, *, window: int = 20):
        if window < 1:
            raise ValueError("window must be positive")
        self.window = window

    def detect(self, ticker: str, end_date: str, fd: DataClient, *,
               ctx: ScanContext | None = None) -> EventTrigger | None:
        bars = _daily_bars(fd, ticker, end_date, self.window)[-(self.window + 1):]
        if len(bars) < self.window + 1:
            return None
        closes = _closes(bars)
        if closes is None:
            return None
        upper, lower = max(closes[:-1]), min(closes[:-1])
        up, down = closes[-1] > upper, closes[-1] < lower
        return EventTrigger(
            detector=self.name, triggered=up or down,
            severity_z=2.0 if up else -2.0 if down else 0.0,
            direction="bullish" if up else "bearish" if down else "neutral",
            reason=f"Close {closes[-1]:.2f}; prior {self.window}-bar closing range [{lower:.2f}, {upper:.2f}]",
            components={"close": closes[-1], "prior_high_close": upper,
                        "prior_low_close": lower, "window": float(self.window)},
            asof_date=bars[-1].time[:10],
        )


class RelativeStrengthDetector(EventDetector):
    """N-session return spread vs SPY, on identical trading dates."""

    name = "relative_strength"

    def __init__(self, *, window: int = 20, threshold: float = 0.05):
        if window < 1 or not isfinite(threshold) or threshold <= 0:
            raise ValueError("window and threshold must be positive")
        self.window = window
        self.threshold = threshold

    def detect(self, ticker: str, end_date: str, fd: DataClient, *,
               ctx: ScanContext | None = None) -> EventTrigger | None:
        stock = _daily_bars(fd, ticker, end_date, self.window)
        benchmark = _daily_bars(fd, "SPY", end_date, self.window)[-(self.window + 1):]
        if not stock or len(benchmark) < self.window + 1:
            return None
        # Require the same latest bar and every benchmark session; do not
        # silently compare different periods when a stock is missing days.
        by_date = {p.time[:10]: p for p in stock}
        if stock[-1].time[:10] != benchmark[-1].time[:10]:
            return None
        if any(p.time[:10] not in by_date for p in benchmark):
            return None
        stock_closes = _closes([by_date[p.time[:10]] for p in benchmark])
        bench_closes = _closes(benchmark)
        if stock_closes is None or bench_closes is None:
            return None
        stock_return = stock_closes[-1] / stock_closes[0] - 1
        bench_return = bench_closes[-1] / bench_closes[0] - 1
        spread = stock_return - bench_return
        hit = abs(spread) >= self.threshold
        return EventTrigger(
            detector=self.name, triggered=hit,
            severity_z=(1 if spread > 0 else -1) * min(abs(spread) / self.threshold * 2, 5.0) if hit else 0.0,
            direction=("bullish" if spread > 0 else "bearish") if hit else "neutral",
            reason=f"{self.window}-session return {stock_return:+.2%} vs SPY {bench_return:+.2%}; spread {spread * 100:+.2f} pp",
            components={"stock_return": stock_return, "benchmark_return": bench_return,
                        "return_spread": spread, "threshold": self.threshold},
            asof_date=benchmark[-1].time[:10],
        )
