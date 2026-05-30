"""Tests for src.research.charts.intraday_fetch.fetch_intraday_prices.

yfinance is never hit for real — we monkeypatch ``yfinance.Ticker`` to
return a fake object whose ``.history`` yields a small DataFrame (or
raises), and assert the best-effort contract:
  - happy path -> list[Price] with correct OHLCV
  - exception / empty frame -> [] (never raises)
"""

from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

from src.research.charts.intraday_fetch import fetch_intraday_prices
from v2.data.models import Price


def _fake_yf_module(history_fn):
    """Build a stand-in ``yfinance`` module whose Ticker(...).history
    delegates to ``history_fn(period, interval)``."""

    class _FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, period="5d", interval="5m"):
            return history_fn(period, interval)

    mod = types.ModuleType("yfinance")
    mod.Ticker = _FakeTicker
    return mod


def _small_frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2026-05-29 09:30:00", "2026-05-29 09:35:00"])
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.0, 102.5],
            "Volume": [1000, 2000],
        },
        index=idx,
    )


def test_fetch_intraday_returns_prices(monkeypatch):
    fake = _fake_yf_module(lambda period, interval: _small_frame())
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    out = fetch_intraday_prices("NVDA", period="5d", interval="5m")

    assert isinstance(out, list)
    assert len(out) == 2
    assert all(isinstance(p, Price) for p in out)
    first = out[0]
    assert first.open == 100.0
    assert first.high == 102.0
    assert first.low == 99.0
    assert first.close == 101.0
    assert first.volume == 1000
    # time is the index timestamp's ISO form
    assert first.time.startswith("2026-05-29T09:30:00")


def test_fetch_intraday_passes_period_and_interval(monkeypatch):
    seen = {}

    def _hist(period, interval):
        seen["period"] = period
        seen["interval"] = interval
        return _small_frame()

    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_module(_hist))

    fetch_intraday_prices("AAPL", period="1mo", interval="15m")
    assert seen == {"period": "1mo", "interval": "15m"}


def test_fetch_intraday_empty_frame_returns_empty_list(monkeypatch):
    fake = _fake_yf_module(lambda period, interval: pd.DataFrame())
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    assert fetch_intraday_prices("ZZZZ") == []


def test_fetch_intraday_history_raises_returns_empty_list(monkeypatch):
    def _boom(period, interval):
        raise RuntimeError("rate limited")

    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_module(_boom))

    # Best-effort: a raise inside yfinance must be swallowed.
    assert fetch_intraday_prices("NVDA") == []


def test_fetch_intraday_skips_malformed_rows(monkeypatch):
    """A NaN/non-castable Volume row is dropped, not fatal."""
    idx = pd.to_datetime(["2026-05-29 09:30:00", "2026-05-29 09:35:00"])
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.0, 102.5],
            "Volume": [1000, float("nan")],
        },
        index=idx,
    )
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_module(lambda p, i: frame))

    out = fetch_intraday_prices("NVDA")
    assert len(out) == 1
    assert out[0].volume == 1000
