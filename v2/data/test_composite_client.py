"""Tests for CompositeClient (per-method routing) and make_hybrid_client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from v2.data.composite_client import CompositeClient, make_hybrid_client
from v2.data.eodhd_client import EODHDClient
from v2.data.finnhub_client import FinnhubClient
from v2.data.protocol import DataClient


def _stub(name: str) -> MagicMock:
    """A MagicMock that ducks-types to DataClient with default-empty returns."""
    m = MagicMock(name=name)
    m.get_prices.return_value = []
    m.get_news.return_value = []
    m.get_insider_trades.return_value = []
    m.get_earnings.return_value = None
    m.get_earnings_history.return_value = []
    m.get_company_facts.return_value = None
    m.get_market_cap.return_value = None
    m.get_financial_metrics.return_value = []
    return m


@pytest.fixture()
def stubs():
    return {
        "prices": _stub("eodhd"),
        "news": _stub("eodhd"),
        "insider": _stub("finnhub"),
        "earnings": _stub("finnhub"),
        "facts": _stub("finnhub"),
        "metrics": _stub("finnhub"),
    }


@pytest.fixture()
def composite(stubs):
    return CompositeClient(
        prices_backend=stubs["prices"],
        news_backend=stubs["news"],
        insider_backend=stubs["insider"],
        earnings_backend=stubs["earnings"],
        facts_backend=stubs["facts"],
        metrics_backend=stubs["metrics"],
    )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestRouting:
    def test_prices_routed_to_prices_backend(self, composite, stubs):
        composite.get_prices("AAPL", "2026-05-01", "2026-05-13")
        stubs["prices"].get_prices.assert_called_once()
        stubs["insider"].get_prices.assert_not_called()
        stubs["earnings"].get_prices.assert_not_called()

    def test_news_routed_to_news_backend(self, composite, stubs):
        composite.get_news("AAPL", "2026-05-13", "2026-04-13", 100)
        stubs["news"].get_news.assert_called_once()
        stubs["insider"].get_news.assert_not_called()

    def test_insider_routed_to_insider_backend(self, composite, stubs):
        composite.get_insider_trades("AAPL", "2026-05-13", "2025-05-13", 100)
        stubs["insider"].get_insider_trades.assert_called_once()
        stubs["prices"].get_insider_trades.assert_not_called()

    def test_earnings_history_routed_to_earnings_backend(self, composite, stubs):
        composite.get_earnings_history("AAPL", limit=4)
        stubs["earnings"].get_earnings_history.assert_called_once()
        stubs["facts"].get_earnings_history.assert_not_called()

    def test_market_cap_routed_to_facts_backend(self, composite, stubs):
        composite.get_market_cap("AAPL", "2026-05-13")
        stubs["facts"].get_market_cap.assert_called_once()
        stubs["metrics"].get_market_cap.assert_not_called()

    def test_company_facts_routed_to_facts_backend(self, composite, stubs):
        composite.get_company_facts("AAPL")
        stubs["facts"].get_company_facts.assert_called_once()

    def test_financial_metrics_routed_to_metrics_backend(self, composite, stubs):
        composite.get_financial_metrics("AAPL", "2026-05-13")
        stubs["metrics"].get_financial_metrics.assert_called_once()


# ---------------------------------------------------------------------------
# Optional quotes_backend
# ---------------------------------------------------------------------------


class TestQuotesBackend:
    def test_returns_none_when_quotes_backend_absent(self, composite):
        # Default fixture has no quotes_backend.
        assert composite.get_quote("AAPL") is None

    def test_delegates_to_quotes_backend_when_present(self, stubs):
        from v2.data.models import Quote
        quote_stub = _stub("quotes")
        quote_stub.get_quote.return_value = Quote(
            ticker="AAPL", current_price=180.0, prev_close=178.0,
            percent_change=1.12, asof_timestamp=1778869464,
        )
        composite = CompositeClient(
            prices_backend=stubs["prices"],
            news_backend=stubs["news"],
            insider_backend=stubs["insider"],
            earnings_backend=stubs["earnings"],
            facts_backend=stubs["facts"],
            metrics_backend=stubs["metrics"],
            quotes_backend=quote_stub,
        )
        q = composite.get_quote("AAPL")
        assert q is not None
        assert q.current_price == 180.0
        quote_stub.get_quote.assert_called_once_with("AAPL")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_composite_satisfies_dataclient_protocol(self, composite):
        assert isinstance(composite, DataClient)


# ---------------------------------------------------------------------------
# close() idempotency — multiple slots can share an instance
# ---------------------------------------------------------------------------


class TestCloseIdempotent:
    def test_shared_backend_closed_once(self):
        shared = _stub("shared")
        comp = CompositeClient(
            prices_backend=shared,
            news_backend=shared,  # same instance reused
            insider_backend=shared,
            earnings_backend=shared,
            facts_backend=shared,
            metrics_backend=shared,
        )
        comp.close()
        # All 6 slots point at the same instance; close() should fire exactly once.
        assert shared.close.call_count == 1

    def test_two_distinct_backends_each_closed_once(self, stubs):
        # Build composite where prices/news share one, the rest share another.
        comp = CompositeClient(
            prices_backend=stubs["prices"],
            news_backend=stubs["prices"],     # same as prices
            insider_backend=stubs["insider"],
            earnings_backend=stubs["insider"],
            facts_backend=stubs["insider"],
            metrics_backend=stubs["insider"],
        )
        comp.close()
        assert stubs["prices"].close.call_count == 1
        assert stubs["insider"].close.call_count == 1


# ---------------------------------------------------------------------------
# make_hybrid_client
# ---------------------------------------------------------------------------


class TestMakeHybridClient:
    def test_builds_hybrid_with_eodhd_and_finnhub(self):
        client = make_hybrid_client()
        assert isinstance(client, CompositeClient)
        assert isinstance(client._prices, EODHDClient)
        assert isinstance(client._news, EODHDClient)
        assert isinstance(client._insider, FinnhubClient)
        assert isinstance(client._earnings, FinnhubClient)
        assert isinstance(client._facts, FinnhubClient)
        assert isinstance(client._metrics, FinnhubClient)

    def test_prices_and_news_share_eodhd_instance(self):
        client = make_hybrid_client()
        # Same EODHD client object backs both prices and news (saves a session).
        assert client._prices is client._news

    def test_insider_earnings_facts_metrics_share_finnhub_instance(self):
        client = make_hybrid_client()
        finnhub = client._insider
        assert client._earnings is finnhub
        assert client._facts is finnhub
        assert client._metrics is finnhub
