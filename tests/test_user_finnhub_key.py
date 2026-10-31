"""Saved Finnhub credentials reach data clients without changing host env."""
from unittest.mock import Mock, patch
from types import SimpleNamespace


def test_shared_data_forwards_key_to_provider():
    from src.research.shared_data import fetch_shared_data
    client = Mock()
    client.evidence = []; client.quality = []
    client.store.status = 'unconfigured'
    client.get_prices.return_value = [Mock()]
    client.get_company_facts.return_value = None
    with patch('v2.data.factory.get_provider_factory', return_value=lambda: client) as factory:
        fetch_shared_data('AAPL', '2026-10-31', finnhub_api_key='test-user-key')
    factory.assert_called_once_with(finnhub_api_key='test-user-key')


def test_hybrid_factory_forwards_user_key():
    from v2.data.factory import get_provider_factory
    with patch('v2.data.composite_client.make_hybrid_client') as build:
        get_provider_factory('hybrid', finnhub_api_key='test-user-key')()
    build.assert_called_once_with(finnhub_api_key='test-user-key')


def test_quotes_do_not_share_user_credentials_or_cached_results():
    from app.backend.services.live_quotes import fetch_live_quotes, _QUOTE_CACHE
    _QUOTE_CACHE.clear()
    quote = SimpleNamespace(current_price=100, prev_close=99, percent_change=1, day_open=99,
                            day_high=101, day_low=98, asof_timestamp=None, received_at=None)
    with patch('app.backend.services.live_quotes.FinnhubClient') as client:
        client.return_value.__enter__.return_value.get_quote.return_value = quote
        fetch_live_quotes(['AAPL'], finnhub_api_key='test-user-a', user_id=101)
        fetch_live_quotes(['AAPL'], finnhub_api_key='test-user-b', user_id=102)
        assert client.call_count == 2
        assert [call.kwargs['api_key'] for call in client.call_args_list] == ['test-user-a', 'test-user-b']
    _QUOTE_CACHE.clear()


def test_explicit_empty_key_never_uses_host_key(monkeypatch):
    from v2.data.finnhub_client import FinnhubClient
    from v2.data.factory import get_provider_factory
    monkeypatch.setenv('FINNHUB_API_KEY', 'test-host-key')
    with FinnhubClient(api_key='') as client:
        assert client._api_key == ''
        with patch.object(client._session, 'get') as get:
            assert client.get_quote('AAPL') is None
            get.assert_not_called()
    with get_provider_factory('finnhub', finnhub_api_key='')() as client:
        assert client._api_key == ''
