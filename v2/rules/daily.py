"""Daily conditions over ordered bars, already bounded to the decision session."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from fractions import Fraction
from math import isfinite
from typing import Protocol

from v2.rules.spec import (
    Combiner, DailyCondition, DailyRule, RangeBreakoutRule, RelativeStrengthRule, RelativeVolumeRule,
)
from v2.scanner.detectors.base import EventTrigger, close_of


class DailyBar(Protocol):
    time: str
    adjusted_close: float | None
    close: float | None
    volume: float | None


def lookback_days(window: int) -> int:
    """Calendar-day input horizon used by both adapters before session alignment."""
    return max(90, window * 3)


def lookback_start(as_of: date, window: int) -> date:
    """Earliest calendar date in the request, bounded to representable dates."""
    return date.fromordinal(max(1, as_of.toordinal() - lookback_days(window)))


def _closes(bars: Sequence[DailyBar]) -> list[float] | None:
    values = []
    for bar in bars:
        value = close_of(bar)
        if value is None or not isfinite(value) or value <= 0:
            return None
        values.append(value)
    return values


def _relative_volume(rule: RelativeVolumeRule, bars: Sequence[DailyBar]) -> EventTrigger | None:
    closes = _closes(bars[-2:])
    volumes = [p.volume for p in bars]
    if closes is None or any(v is None or not isfinite(v) or v < 0 for v in volumes):
        return None
    baseline = sum(volumes[:-1]) / rule.window
    if baseline <= 0:
        return None
    ratio = volumes[-1] / baseline
    daily_return = closes[-1] / closes[-2] - 1
    hit = ratio >= rule.threshold
    direction = "bullish" if daily_return > 0 else "bearish" if daily_return < 0 else "neutral"
    sign = 1 if daily_return > 0 else -1 if daily_return < 0 else 0
    return EventTrigger(
        detector=rule.type, triggered=hit,
        severity_z=sign * min(ratio, 5.0) if hit else 0.0,
        direction=direction if hit else "neutral",
        reason=f"Volume {ratio:.2f}x prior {rule.window}-bar mean (threshold {rule.threshold:g}x); daily return {daily_return:+.2%}",
        components={"relative_volume": ratio, "baseline_volume": baseline,
                    "today_volume": volumes[-1], "daily_return": daily_return},
        asof_date=bars[-1].time[:10], signal_session=bars[-1].time[:10],
    )


def _range_breakout(rule: RangeBreakoutRule, bars: Sequence[DailyBar]) -> EventTrigger | None:
    closes = _closes(bars)
    if closes is None:
        return None
    upper, lower = max(closes[:-1]), min(closes[:-1])
    up, down = closes[-1] > upper, closes[-1] < lower
    return EventTrigger(
        detector=rule.type, triggered=up or down,
        severity_z=2.0 if up else -2.0 if down else 0.0,
        direction="bullish" if up else "bearish" if down else "neutral",
        reason=f"Close {closes[-1]:.2f}; prior {rule.window}-bar closing range [{lower:.2f}, {upper:.2f}]",
        components={"close": closes[-1], "prior_high_close": upper,
                    "prior_low_close": lower, "window": float(rule.window)},
        asof_date=bars[-1].time[:10], signal_session=bars[-1].time[:10],
    )


def _period_return(closes: list[float]) -> Fraction:
    # Compare decimal quotes exactly at the inclusive spread threshold.
    return Fraction(str(closes[-1])) / Fraction(str(closes[0])) - 1


def _relative_strength(
    rule: RelativeStrengthRule, stock: Sequence[DailyBar], benchmark: Sequence[DailyBar],
) -> EventTrigger | None:
    benchmark = benchmark[-(rule.window + 1):]
    if len(benchmark) <= rule.window or stock[-1].time[:10] != benchmark[-1].time[:10]:
        return None
    # Every benchmark session, including the latest, must be present in the stock.
    by_date = {bar.time[:10]: bar for bar in stock}
    dates = [bar.time[:10] for bar in benchmark]
    if any(date not in by_date for date in dates):
        return None
    stock_closes = _closes([by_date[date] for date in dates])
    bench_closes = _closes(benchmark)
    if stock_closes is None or bench_closes is None:
        return None
    stock_return = _period_return(stock_closes)
    bench_return = _period_return(bench_closes)
    exact_spread = stock_return - bench_return
    hit = abs(exact_spread) >= Fraction(str(rule.threshold))
    spread = float(exact_spread)
    return EventTrigger(
        detector=rule.type, triggered=hit,
        severity_z=(1 if spread > 0 else -1) * min(abs(spread) / rule.threshold * 2, 5.0) if hit else 0.0,
        direction=("bullish" if spread > 0 else "bearish") if hit else "neutral",
        reason=f"{rule.window}-session return {float(stock_return):+.2%} vs SPY {float(bench_return):+.2%}; spread {spread * 100:+.2f} pp",
        components={"stock_return": float(stock_return), "benchmark_return": float(bench_return),
                    "return_spread": spread, "threshold": rule.threshold},
        asof_date=dates[-1], signal_session=dates[-1],
    )


def evaluate_rule(
    rule: DailyCondition, bars: Sequence[DailyBar], benchmark: Sequence[DailyBar] = (),
) -> EventTrigger | None:
    """Evaluate raw evidence on ordered input. Missing warm-up or values yield None."""
    if len(bars) <= rule.window:
        return None
    if isinstance(rule, RelativeStrengthRule):
        return _relative_strength(rule, bars, benchmark)
    window = bars[-(rule.window + 1):]
    if isinstance(rule, RelativeVolumeRule):
        return _relative_volume(rule, window)
    if isinstance(rule, RangeBreakoutRule):
        return _range_breakout(rule, window)
    raise ValueError(f"Unknown daily rule: {rule.type}")


def match_condition(rule: DailyRule, trigger: EventTrigger | None) -> bool | None:
    """Match the desired direction while retaining unavailable evidence."""
    if trigger is None:
        return None
    return trigger.triggered and (rule.direction == "any" or trigger.direction == rule.direction)


def combine_matches(combiner: Combiner, matches: Sequence[bool | None]) -> bool | None:
    """Apply three-valued AND/OR to the outcomes of a flat group."""
    decisive = combiner == "or"
    if decisive in matches:
        return decisive
    if None in matches:
        return None
    return not decisive
