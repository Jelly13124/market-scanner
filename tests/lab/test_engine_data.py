"""Phase 6B: DataLoader batches OHLCV via existing v2/data composite client."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd

from src.lab.engine.data import DataLoader, DataLoadResult


def _fake_bars(n=300):
    """Synthetic OHLCV: monotonic close from 100 to 100+n*0.1."""
    return [
        {
            "time": f"2020-01-{(i % 28) + 1:02d}",
            "open": 100 + i * 0.1, "high": 100 + i * 0.1 + 0.5,
            "low": 100 + i * 0.1 - 0.5, "close": 100 + i * 0.1,
            "volume": 1_000_000 + i * 100,
        }
        for i in range(n)
    ]


@patch("src.lab.engine.data.fetch_prices")
def test_batch_fetch_returns_dataframe(mock_fetch):
    mock_fetch.return_value = _fake_bars(300)
    loader = DataLoader()
    result = loader.load(
        tickers=["NVDA", "AAPL"],
        start_date=date(2020, 1, 1),
        end_date=date(2024, 1, 1),
    )
    assert isinstance(result, DataLoadResult)
    assert "NVDA" in result.bars and "AAPL" in result.bars
    assert isinstance(result.bars["NVDA"], pd.DataFrame)
    # Columns: open/high/low/close/volume + DatetimeIndex
    for col in ("open", "high", "low", "close", "volume"):
        assert col in result.bars["NVDA"].columns
    assert isinstance(result.bars["NVDA"].index, pd.DatetimeIndex)
    assert len(result.failed) == 0


@patch("src.lab.engine.data.fetch_prices")
def test_partial_failure_recorded_not_raised(mock_fetch):
    def side_effect(ticker, **kw):
        if ticker == "BROKEN":
            raise RuntimeError("no data")
        return _fake_bars(100)
    mock_fetch.side_effect = side_effect

    loader = DataLoader()
    result = loader.load(
        tickers=["NVDA", "BROKEN", "AAPL"],
        start_date=date(2020, 1, 1),
        end_date=date(2024, 1, 1),
    )
    assert set(result.bars.keys()) == {"NVDA", "AAPL"}
    assert "BROKEN" in result.failed
    # Engine should keep running with the 2 successful tickers


@patch("src.lab.engine.data.fetch_prices")
def test_empty_bars_skipped(mock_fetch):
    mock_fetch.return_value = []
    loader = DataLoader()
    result = loader.load(
        tickers=["EMPTY"], start_date=date(2020, 1, 1), end_date=date(2024, 1, 1),
    )
    assert "EMPTY" in result.failed
    assert "EMPTY" not in result.bars
