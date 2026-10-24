"""Phase 8: AShareClient implements the DataClient Protocol."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from v2.data.ashare.client import AShareClient
from v2.data.models import CompanyFacts, Price


def test_implements_protocol():
    c = AShareClient()
    # Pydantic Protocol - duck-type check
    assert hasattr(c, "get_prices")
    assert hasattr(c, "get_financial_metrics")
    assert hasattr(c, "get_news")
    assert hasattr(c, "get_company_facts")
    assert hasattr(c, "get_earnings_history")
    assert hasattr(c, "get_market_cap")
    assert callable(c.get_prices)


def test_returns_empty_on_unknown_ticker():
    """Per Protocol invariant - never raise; return empty list on missing data."""
    c = AShareClient()
    prices = c.get_prices("999999", "2025-01-01", "2026-05-26")
    assert prices == []


# ---------------------------------------------------------------------------
# Task 10: delegation tests -- mock the Wave 2 helpers and confirm the
# client routes to them with the canonicalized ticker.
# ---------------------------------------------------------------------------


@patch("v2.data.ashare.mootdx_prices.fetch_daily_ohlcv")
def test_get_prices_delegates(mock_fetch):
    mock_fetch.return_value = [
        Price(open=1, high=1, low=1, close=1, volume=1, time="2025-01-02", adjusted_close=1),
    ]
    c = AShareClient()
    prices = c.get_prices("600519", "2025-01-01", "2025-12-31")
    assert len(prices) == 1
    # Confirms canonical normalization happened before delegation
    mock_fetch.assert_called_once_with("600519.SH", "2025-01-01", "2025-12-31")


@patch("v2.data.ashare.eastmoney_fundamentals.fetch_company_facts")
def test_get_company_facts_delegates(mock_fetch):
    mock_fetch.return_value = CompanyFacts(
        ticker="600519.SH",
        name="贵州茅台",  # Moutai
        sector="食品饮料",  # Food & beverage
        industry="白酒",  # Baijiu
        cik=None,
        market_cap=None,
        number_of_employees=30000,
    )
    c = AShareClient()
    facts = c.get_company_facts("sh600519")
    assert facts is not None
    assert facts.name == "贵州茅台"
    # Confirms canonical normalization happened before delegation
    mock_fetch.assert_called_once()
    call_kwargs = mock_fetch.call_args
    assert call_kwargs.args[0] == "600519.SH"


def test_us_ticker_returns_empty():
    c = AShareClient()
    assert c.get_prices("NVDA", "2025-01-01", "2025-12-31") == []
    assert c.get_company_facts("AAPL") is None
    assert c.get_market_cap("NVDA", "2025-12-31") is None
