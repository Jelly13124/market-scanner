"""Phase 8: AShareClient implements the DataClient Protocol."""
from __future__ import annotations

import pytest
from v2.data.protocol import DataClient
from v2.data.ashare.client import AShareClient


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
