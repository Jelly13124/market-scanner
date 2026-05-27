"""SnapshotBuilder CN path — mootdx + akshare mocked through AshareMetrics."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.screener.snapshot_builder import SnapshotBuilder


@pytest.fixture()
def fake_ashare():
    """AshareMetrics duck-typed mock."""
    m = MagicMock()
    m.get_quote.return_value = {
        "price": 1700.50,
        "prev_close": 1685.00,
        "volume": 2_500_000,
        "avg_volume_10d": 2_300_000,
    }
    m.get_fundamentals.return_value = {
        "market_cap": 2_120_000_000_000,
        "pe_ttm": 28.5,
        "pb": 8.2,
        "ps": 9.1,
        "peg": 1.4,
        "eps_growth_yoy": 0.18,
        "revenue_growth_yoy": 0.15,
        "roe": 0.32,
        "profit_margin": 0.35,
        "dividend_yield_pct": 0.012,
        "sector": "白酒",
        "industry": "食品饮料",
        "exchange": "SSE",
    }
    m.get_perf_windows.return_value = {
        "perf_1d": 0.0092, "perf_5d": 0.0210, "perf_1m": 0.0530,
        "perf_3m": 0.1110, "perf_ytd": 0.2200, "perf_1y": 0.4150,
    }
    m.get_earnings_dates.return_value = (date(2026, 4, 28), date(2026, 8, 25))
    return m


def test_build_for_ticker_cn_full(fake_ashare):
    builder = SnapshotBuilder(ashare_metrics=fake_ashare)
    row = builder.build_for_ticker_cn("600519.SH", date(2026, 5, 27))

    assert row.ticker == "600519.SH"
    assert row.market == "CN"
    assert row.snapshot_date == date(2026, 5, 27)
    assert row.price == Decimal("1700.5")
    assert row.market_cap == Decimal("2120000000000")
    assert row.sector == "白酒"
    assert row.exchange == "SSE"
    assert row.perf_ytd == Decimal("0.2200")
    assert row.recent_earnings_date == date(2026, 4, 28)
    assert row.upcoming_earnings_date == date(2026, 8, 25)
    assert row.data_source == "mootdx+akshare"


def test_build_for_ticker_cn_handles_missing(fake_ashare):
    fake_ashare.get_fundamentals.return_value = {}
    fake_ashare.get_perf_windows.return_value = {}
    fake_ashare.get_earnings_dates.return_value = (None, None)

    builder = SnapshotBuilder(ashare_metrics=fake_ashare)
    row = builder.build_for_ticker_cn("000001.SZ", date(2026, 5, 27))

    assert row.ticker == "000001.SZ"
    assert row.price == Decimal("1700.5")  # quote still present
    assert row.market_cap is None
    assert row.sector is None
    assert row.perf_1y is None


def test_build_for_universe_cn_dispatches_to_cn_path(fake_ashare):
    from unittest.mock import patch
    builder = SnapshotBuilder(ashare_metrics=fake_ashare)
    with patch("src.screener.snapshot_builder.load_universe",
               return_value=["600519.SH", "000001.SZ"]):
        rows = builder.build_for_universe("CN", "csi300", date(2026, 5, 27))
    assert {r.ticker for r in rows} == {"600519.SH", "000001.SZ"}
    assert all(r.market == "CN" for r in rows)


def test_build_for_ticker_cn_without_ashare_raises():
    builder = SnapshotBuilder()  # no ashare injected
    with pytest.raises(RuntimeError, match="ashare_metrics"):
        builder.build_for_ticker_cn("600519.SH", date(2026, 5, 27))
