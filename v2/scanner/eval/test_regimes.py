"""Tests for the SPY-based market-regime classifier.

Synthetic SPY ``Price`` series are constructed by ``_mk`` — no network. Each
series shape exercises one branch of the BULL / BEAR / CHOPPY label rule, plus
the degenerate short-series guard and the three-window ``classify_regimes``
wrapper.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from v2.data.models import Price
from v2.scanner.eval.regimes import (
    DEFAULT_CANDIDATES,
    RegimeWindow,
    classify_regimes,
    classify_window,
)


def _mk(closes, start: str = "2023-01-02") -> list[Price]:
    """Build a SPY ``Price`` list with consecutive calendar-daily dates.

    Calendar (not trading) days are fine for tests — the classifier only
    orders by ``time`` and indexes bars 0..n-1, never reasoning about gaps.
    ``adjusted_close`` is set equal to ``close`` so the adjusted-preferred
    reader returns the same series.
    """
    d0 = date.fromisoformat(start)
    out: list[Price] = []
    for i, c in enumerate(closes):
        t = (d0 + timedelta(days=i)).isoformat()
        out.append(
            Price(
                open=c,
                high=c,
                low=c,
                close=c,
                volume=1000,
                time=t,
                adjusted_close=c,
            )
        )
    return out


def test_monotonic_up_is_bull():
    closes = [100 * 1.004**i for i in range(180)]
    prices = _mk(closes)
    w = classify_window(
        prices, name="up", start=prices[0].time[:10], end=prices[-1].time[:10]
    )
    assert w.label == "BULL"
    assert w.spy_return > 0.2
    assert w.trend_r2 > 0.9


def test_drawdown_is_bear():
    closes = [100 * 0.997**i for i in range(180)]
    prices = _mk(closes)
    w = classify_window(
        prices, name="down", start=prices[0].time[:10], end=prices[-1].time[:10]
    )
    assert w.label == "BEAR"
    assert w.spy_return < -0.1


def test_flat_is_choppy():
    closes = [100 + 3 * math.sin(i / 3) for i in range(180)]
    prices = _mk(closes)
    w = classify_window(
        prices, name="flat", start=prices[0].time[:10], end=prices[-1].time[:10]
    )
    assert w.label == "CHOPPY"
    assert abs(w.spy_return) < 0.05
    assert w.trend_r2 < 0.5


def test_short_series_degenerate():
    prices = _mk([100, 101, 102])
    w = classify_window(
        prices, name="tiny", start=prices[0].time[:10], end=prices[-1].time[:10]
    )
    assert w.label == "CHOPPY"
    assert w.n_bars == 3
    assert w.spy_return == 0.0
    assert w.max_drawdown == 0.0
    assert w.trend_r2 == 0.0


def test_classify_regimes_returns_three():
    # One long synthetic series spanning every candidate window's date range.
    # Shape is monotonic-up so labels are deterministic, but we only assert the
    # wrapper returns 3 windows carrying the right candidate names.
    start = DEFAULT_CANDIDATES[0]["start"]
    end = DEFAULT_CANDIDATES[-1]["end"]
    n = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    closes = [100 * 1.0005**i for i in range(n)]
    prices = _mk(closes, start=start)

    out = classify_regimes(prices)
    assert len(out) == 3
    assert [w.name for w in out] == [c["name"] for c in DEFAULT_CANDIDATES]
    assert all(isinstance(w, RegimeWindow) for w in out)
