"""Scanner data adapters for the three shared daily momentum rules.

These daily conditions can fire on consecutive days. Inputs are bounded by
the requested date and the calendar lookback. The evidence identifies the
actual last bar used, including on weekends.
"""

from __future__ import annotations

import logging
from bisect import bisect_left

from v2.data.protocol import DataClient
from v2.rules import daily
from v2.rules.spec import DailyCondition, RangeBreakoutRule, RelativeStrengthRule, RelativeVolumeRule
from v2.scanner.detectors.base import EventDetector, EventTrigger, parse_date
from v2.scanner.models import ScanContext

logger = logging.getLogger(__name__)


def load_daily_bars(fd, ticker, end_date, window, *, observations=None):
    """Read one bounded series or slice the group's already-bounded observation."""
    end = parse_date(end_date)
    if end is None:
        return []
    start = daily.lookback_start(end, window).isoformat()
    if observations is not None:
        bars = observations[ticker]
        first = bisect_left(bars, start, key=lambda bar: bar.time[:10])
        return bars[first:]
    try:
        bars = fd.get_prices(ticker, start, end_date)
    except Exception as error:
        logger.debug("Daily bars unavailable for %s: %s", ticker, type(error).__name__)
        return []
    return sorted(
        (p for p in (bars or []) if start <= p.time[:10] <= end.isoformat()),
        key=lambda p: p.time[:10],
    )


class _DailyRuleAdapter:
    rule: DailyCondition

    @property
    def window(self) -> int:
        return self.rule.window

    def detect(self, ticker: str, end_date: str, fd: DataClient, *,
               ctx: ScanContext | None = None) -> EventTrigger | None:
        observations = ctx.daily_price_observations if ctx is not None else None
        bars = load_daily_bars(fd, ticker, end_date, self.window, observations=observations)
        benchmark = ()
        if isinstance(self.rule, RelativeStrengthRule):
            benchmark = load_daily_bars(fd, "SPY", end_date, self.window, observations=observations)
        return daily.evaluate_rule(self.rule, bars, benchmark)


class RelativeVolumeDetector(_DailyRuleAdapter, EventDetector):
    """Volume >= 2x preceding 20-bar mean, with direction from daily return."""

    name = "relative_volume"

    def __init__(self, *, window: int = 20, threshold: float = 2.0):
        self.rule = RelativeVolumeRule(window=window, threshold=threshold)

    @property
    def threshold(self) -> float:
        return self.rule.threshold


class RangeBreakoutDetector(_DailyRuleAdapter, EventDetector):
    """Close strictly outside preceding N adjusted closes, excluding today."""

    name = "range_breakout"

    def __init__(self, *, window: int = 20):
        self.rule = RangeBreakoutRule(window=window)


class RelativeStrengthDetector(_DailyRuleAdapter, EventDetector):
    """N-session return spread vs SPY, on identical trading dates."""

    name = "relative_strength"

    def __init__(self, *, window: int = 20, threshold: float = 0.05):
        self.rule = RelativeStrengthRule(window=window, threshold=threshold)

    @property
    def threshold(self) -> float:
        return self.rule.threshold
