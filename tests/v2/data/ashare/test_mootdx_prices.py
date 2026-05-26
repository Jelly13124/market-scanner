"""Phase 8: mootdx-backed OHLCV fetcher."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from v2.data.ashare.mootdx_prices import fetch_daily_ohlcv, _split_canonical


def test_split_canonical():
    code, exch = _split_canonical("600519.SH")
    assert code == "600519"
    assert exch == "SH"


@patch("v2.data.ashare.mootdx_prices.Quotes")
def test_fetch_daily_returns_typed_prices(MockQuotes):
    # mootdx returns a DataFrame with columns:
    # ['open', 'high', 'low', 'close', 'vol', 'amount', 'date']
    fake_df = pd.DataFrame({
        'open':   [100.0, 101.0, 102.0],
        'high':   [101.0, 103.0, 104.0],
        'low':    [99.0,  100.0, 101.0],
        'close':  [100.5, 102.0, 103.5],
        'vol':    [1e7,   1.2e7, 1.5e7],
        'amount': [1e9,   1.2e9, 1.5e9],
        'date':   pd.to_datetime(['2025-01-02', '2025-01-03', '2025-01-06']),
    })
    instance = MagicMock()
    instance.bars.return_value = fake_df
    MockQuotes.factory.return_value = instance

    prices = fetch_daily_ohlcv('600519.SH', '2025-01-01', '2025-01-10')

    assert len(prices) == 3
    assert prices[0].close == 100.5
    assert prices[0].open == 100.0
    assert prices[0].high == 101.0
    assert prices[0].low == 99.0
    assert prices[0].volume == 1e7
    # canonicalize date as ISO string in 'time' field
    assert prices[0].time == '2025-01-02'


@patch("v2.data.ashare.mootdx_prices.Quotes")
def test_fetch_daily_empty_when_mootdx_returns_none(MockQuotes):
    instance = MagicMock()
    instance.bars.return_value = None
    MockQuotes.factory.return_value = instance

    prices = fetch_daily_ohlcv('600519.SH', '2025-01-01', '2025-01-10')
    assert prices == []


@patch("v2.data.ashare.mootdx_prices.Quotes")
def test_fetch_daily_filters_to_window(MockQuotes):
    fake_df = pd.DataFrame({
        'open': [1.0] * 5, 'high': [1.0] * 5, 'low': [1.0] * 5,
        'close': [1.0] * 5, 'vol': [0] * 5, 'amount': [0] * 5,
        'date': pd.to_datetime([
            '2024-12-30', '2024-12-31', '2025-01-02', '2025-01-03', '2025-01-06',
        ]),
    })
    instance = MagicMock()
    instance.bars.return_value = fake_df
    MockQuotes.factory.return_value = instance

    prices = fetch_daily_ohlcv('600519.SH', '2025-01-01', '2025-01-31')
    # First 2 rows out of window
    assert len(prices) == 3
    assert prices[0].time == '2025-01-02'
