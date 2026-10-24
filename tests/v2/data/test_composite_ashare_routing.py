"""Tests for CompositeClient A-share routing (Wave 4, Task 12).

When an A-share ticker is passed to a ticker-keyed method, the composite
must dispatch to ``ashare_backend`` if one was configured. US tickers and
methods without a ticker arg keep their existing routing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from v2.data.composite_client import CompositeClient, make_hybrid_client


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
        "prices": _stub("us-prices"),
        "news": _stub("us-news"),
        "insider": _stub("us-insider"),
        "earnings": _stub("us-earnings"),
        "facts": _stub("us-facts"),
        "metrics": _stub("us-metrics"),
        "ashare": _stub("ashare"),
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
        ashare_backend=stubs["ashare"],
    )


# ---------------------------------------------------------------------------
# A-share routing — ticker-keyed methods dispatch to ashare_backend
# ---------------------------------------------------------------------------


class TestAShareRouting:
    @pytest.mark.parametrize("ticker", [
        "600519",        # bare 6-digit (SH)
        "600519.SH",     # canonical
        "000001.SZ",     # SZSE canonical
        "SH.600519",     # prefixed
        "300750",        # ChiNext (SZ)
        "688981",        # STAR (SH)
    ])
    def test_prices_a_share_routed_to_ashare(self, composite, stubs, ticker):
        composite.get_prices(ticker, "2026-05-01", "2026-05-13")
        stubs["ashare"].get_prices.assert_called_once()
        stubs["prices"].get_prices.assert_not_called()

    def test_prices_us_ticker_routed_to_prices_backend(self, composite, stubs):
        composite.get_prices("AAPL", "2026-05-01", "2026-05-13")
        stubs["prices"].get_prices.assert_called_once()
        stubs["ashare"].get_prices.assert_not_called()

    def test_news_a_share_routed_to_ashare(self, composite, stubs):
        composite.get_news("600519.SH", "2026-05-13", "2026-04-13", 100)
        stubs["ashare"].get_news.assert_called_once()
        stubs["news"].get_news.assert_not_called()

    def test_news_us_ticker_routed_to_news_backend(self, composite, stubs):
        composite.get_news("AAPL", "2026-05-13", "2026-04-13", 100)
        stubs["news"].get_news.assert_called_once()
        stubs["ashare"].get_news.assert_not_called()

    def test_insider_a_share_routed_to_ashare(self, composite, stubs):
        composite.get_insider_trades("600519", "2026-05-13", "2025-05-13", 100)
        stubs["ashare"].get_insider_trades.assert_called_once()
        stubs["insider"].get_insider_trades.assert_not_called()

    def test_earnings_history_a_share_routed_to_ashare(self, composite, stubs):
        composite.get_earnings_history("600519.SH", limit=4)
        stubs["ashare"].get_earnings_history.assert_called_once()
        stubs["earnings"].get_earnings_history.assert_not_called()

    def test_earnings_a_share_routed_to_ashare(self, composite, stubs):
        composite.get_earnings("600519.SH")
        stubs["ashare"].get_earnings.assert_called_once()
        stubs["earnings"].get_earnings.assert_not_called()

    def test_company_facts_a_share_routed_to_ashare(self, composite, stubs):
        composite.get_company_facts("600519.SH")
        stubs["ashare"].get_company_facts.assert_called_once()
        stubs["facts"].get_company_facts.assert_not_called()

    def test_market_cap_a_share_routed_to_ashare(self, composite, stubs):
        composite.get_market_cap("600519.SH", "2026-05-13")
        stubs["ashare"].get_market_cap.assert_called_once()
        stubs["facts"].get_market_cap.assert_not_called()

    def test_financial_metrics_a_share_routed_to_ashare(self, composite, stubs):
        composite.get_financial_metrics("600519.SH", "2026-05-13")
        stubs["ashare"].get_financial_metrics.assert_called_once()
        stubs["metrics"].get_financial_metrics.assert_not_called()


# ---------------------------------------------------------------------------
# Non-ticker-keyed methods are unaffected
# ---------------------------------------------------------------------------


class TestNonTickerMethodsUnaffected:
    def test_earnings_calendar_does_not_use_ashare(self, composite, stubs):
        # No ticker arg — earnings calendar is bulk-by-date.
        composite.get_earnings_calendar(start_date="2026-05-01", end_date="2026-05-13")
        stubs["ashare"].get_earnings_calendar.assert_not_called()


# ---------------------------------------------------------------------------
# Backward compatibility — ashare_backend defaults to None
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_no_ashare_backend_routes_a_share_to_us_backend(self, stubs):
        # No ashare_backend supplied — falls back to existing behavior.
        composite = CompositeClient(
            prices_backend=stubs["prices"],
            news_backend=stubs["news"],
            insider_backend=stubs["insider"],
            earnings_backend=stubs["earnings"],
            facts_backend=stubs["facts"],
            metrics_backend=stubs["metrics"],
        )
        composite.get_prices("600519", "2026-05-01", "2026-05-13")
        # Without an ashare backend, the call falls through to prices_backend.
        stubs["prices"].get_prices.assert_called_once()


# ---------------------------------------------------------------------------
# make_hybrid_client(include_ashare=...) — factory wiring
# ---------------------------------------------------------------------------


class TestMakeHybridClientAShare:
    def test_default_includes_ashare_backend(self):
        client = make_hybrid_client()
        # When the optional deps are installed, the AShareClient is wired in.
        # When not installed, the slot is None — both are acceptable defaults.
        from v2.data.ashare.client import AShareClient
        assert client._ashare is None or isinstance(client._ashare, AShareClient)

    def test_include_ashare_false_disables_ashare_backend(self):
        client = make_hybrid_client(include_ashare=False)
        assert client._ashare is None

    def test_include_ashare_true_wires_ashare_backend(self):
        client = make_hybrid_client(include_ashare=True)
        from v2.data.ashare.client import AShareClient
        # AShareClient has no hard third-party requirement at import (uses
        # requests + lazy imports), so this should succeed.
        assert isinstance(client._ashare, AShareClient)
