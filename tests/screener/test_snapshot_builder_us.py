"""SnapshotBuilder US path — yfinance .info / .history mocked."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.screener.snapshot_builder import SnapshotBuilder


_FAKE_INFO = {
    "regularMarketPrice": 210.50,
    "regularMarketPreviousClose": 208.00,
    "regularMarketVolume": 65_000_000,
    "averageDailyVolume10Day": 60_000_000,
    "marketCap": 3_200_000_000_000,
    "trailingPE": 32.5,
    "forwardPE": 28.0,
    "priceToBook": 50.0,
    "priceToSalesTrailing12Months": 9.0,
    "pegRatio": 2.8,
    "earningsGrowth": 0.12,
    "revenueGrowth": 0.08,
    "returnOnEquity": 1.45,
    "profitMargins": 0.25,
    "dividendYield": 0.0050,
    "beta": 1.24,
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "exchange": "NMS",
    "recommendationKey": "buy",
    "numberOfAnalystOpinions": 38,
    "targetMeanPrice": 235.00,
    "mostRecentQuarter": 1_714_867_200,  # 2024-05-05 unix
}


def _fake_ticker():
    t = MagicMock()
    t.info = _FAKE_INFO

    # .history(period='1y') used for perf windows + earnings dates
    import pandas as pd
    idx = pd.date_range(end="2026-05-27", periods=260, freq="B")
    closes = pd.Series([100 + i * 0.5 for i in range(260)], index=idx)
    t.history.return_value = pd.DataFrame({"Close": closes,
                                           "Volume": [50_000_000] * 260})
    # earnings_dates: next 2 + last 8 quarters
    t.earnings_dates = pd.DataFrame(
        index=pd.to_datetime(["2026-08-21", "2026-05-22", "2026-02-15"]),
        data={"EPS Estimate": [1.5, 1.4, 1.3]},
    )
    return t


def test_build_for_ticker_us_full_fields():
    builder = SnapshotBuilder()
    with patch("src.screener.snapshot_builder.yf.Ticker", return_value=_fake_ticker()):
        row = builder.build_for_ticker_us("AAPL", date(2026, 5, 27))

    assert row.ticker == "AAPL"
    assert row.market == "US"
    assert row.snapshot_date == date(2026, 5, 27)
    assert row.price == Decimal("210.5")
    assert row.market_cap == Decimal("3200000000000")
    assert row.pe_ttm == Decimal("32.5")
    assert row.eps_growth_yoy == Decimal("0.12")
    assert row.sector == "Technology"
    assert row.analyst_rating == "buy"
    assert row.analyst_count == 38
    assert row.data_source == "yfinance"
    assert row.perf_1d is not None
    assert row.perf_1y is not None


def test_build_for_ticker_us_handles_missing_fields():
    sparse_info = {"regularMarketPrice": 50.0, "marketCap": 1_000_000_000}
    t = MagicMock()
    t.info = sparse_info
    import pandas as pd
    t.history.return_value = pd.DataFrame()
    t.earnings_dates = pd.DataFrame()

    builder = SnapshotBuilder()
    with patch("src.screener.snapshot_builder.yf.Ticker", return_value=t):
        row = builder.build_for_ticker_us("XYZ", date(2026, 5, 27))

    assert row.ticker == "XYZ"
    assert row.price == Decimal("50.0")
    assert row.pe_ttm is None
    assert row.sector is None
    assert row.perf_1y is None


def test_build_for_universe_us_skips_failures(caplog):
    """If yf.Ticker raises for one ticker, the rest still succeed."""
    builder = SnapshotBuilder()

    def fake_ticker(symbol):
        if symbol == "BROKEN":
            raise RuntimeError("yfinance HTTP 500")
        return _fake_ticker()

    with patch("src.screener.snapshot_builder.yf.Ticker", side_effect=fake_ticker), \
         patch("src.screener.snapshot_builder.load_universe",
               return_value=["AAPL", "BROKEN", "MSFT"]):
        rows = builder.build_for_universe("US", "sp500", date(2026, 5, 27))

    assert {r.ticker for r in rows} == {"AAPL", "MSFT"}
    assert "BROKEN" in caplog.text


def test_build_for_universe_us_reports_progress():
    progress_calls = []

    def on_progress(done, total):
        progress_calls.append((done, total))

    builder = SnapshotBuilder()
    with patch("src.screener.snapshot_builder.yf.Ticker", return_value=_fake_ticker()), \
         patch("src.screener.snapshot_builder.load_universe",
               return_value=["AAPL", "MSFT", "NVDA"]):
        builder.build_for_universe("US", "sp500", date(2026, 5, 27),
                                   on_progress=on_progress)
    assert progress_calls[-1] == (3, 3)
