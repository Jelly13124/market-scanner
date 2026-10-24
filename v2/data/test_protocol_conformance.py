"""Protocol conformance for FDClient and FinnhubClient.

``@runtime_checkable`` only verifies method *names*; these tests verify the
*signatures* and basic shape so a future contributor renaming a parameter
breaks loudly here rather than silently in production.
"""

from __future__ import annotations

import inspect

import pytest

from v2.data.client import FDClient
from v2.data.eodhd_client import EODHDClient
from v2.data.finnhub_client import FinnhubClient
from v2.data.protocol import DataClient


# Methods that must exist on every DataClient.
_PROTOCOL_METHODS = [
    "get_prices",
    "get_financial_metrics",
    "get_news",
    "get_insider_trades",
    "get_company_facts",
    "get_earnings",
    "get_earnings_history",
    "get_market_cap",
]


@pytest.fixture(params=[FDClient, FinnhubClient, EODHDClient],
                ids=["fd", "finnhub", "eodhd"])
def client_cls(request):
    return request.param


class TestProtocolConformance:
    def test_instance_is_dataclient(self, client_cls):
        # @runtime_checkable inspection.
        if client_cls in (FinnhubClient, EODHDClient):
            instance = client_cls(api_key="test")
        else:
            instance = client_cls()
        assert isinstance(instance, DataClient)

    @pytest.mark.parametrize("name", _PROTOCOL_METHODS)
    def test_has_method(self, client_cls, name):
        assert hasattr(client_cls, name), f"{client_cls.__name__} missing {name}"
        attr = getattr(client_cls, name)
        assert callable(attr)

    @pytest.mark.parametrize("name", _PROTOCOL_METHODS)
    def test_method_is_not_abstract(self, client_cls, name):
        attr = getattr(client_cls, name)
        # Should be a real function, not abstractmethod.
        assert not getattr(attr, "__isabstractmethod__", False)


class TestSignatureCompatibility:
    """Method signatures should accept the params the Protocol declares."""

    def test_get_prices_signature(self, client_cls):
        sig = inspect.signature(client_cls.get_prices)
        # Required: ticker, start_date, end_date
        for needed in ("ticker", "start_date", "end_date"):
            assert needed in sig.parameters, f"{client_cls.__name__}.get_prices missing {needed}"

    def test_get_news_signature(self, client_cls):
        sig = inspect.signature(client_cls.get_news)
        for needed in ("ticker", "end_date", "start_date", "limit"):
            assert needed in sig.parameters

    def test_get_insider_trades_signature(self, client_cls):
        sig = inspect.signature(client_cls.get_insider_trades)
        for needed in ("ticker", "end_date", "start_date", "limit"):
            assert needed in sig.parameters

    def test_get_earnings_history_signature(self, client_cls):
        sig = inspect.signature(client_cls.get_earnings_history)
        for needed in ("ticker", "limit"):
            assert needed in sig.parameters

    def test_get_market_cap_signature(self, client_cls):
        sig = inspect.signature(client_cls.get_market_cap)
        for needed in ("ticker", "end_date"):
            assert needed in sig.parameters
