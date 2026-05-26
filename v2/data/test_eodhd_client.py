"""Unit tests for EODHDClient (mocked HTTP, no wire traffic)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from v2.data.eodhd_client import EODHDClient, _classify_sentiment, _host_from_url


def _resp(status: int, json_body) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body
    r.text = ""
    return r


@pytest.fixture()
def client():
    c = EODHDClient(api_key="test")
    c._session = MagicMock()
    return c


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestClassifySentiment:
    @pytest.mark.parametrize("score,label", [
        (0.50, "positive"),
        (0.21, "positive"),
        (0.10, "neutral"),
        (0.00, "neutral"),
        (-0.10, "neutral"),
        (-0.21, "negative"),
        (-0.99, "negative"),
        (None, None),
    ])
    def test_buckets(self, score, label):
        assert _classify_sentiment(score) == label


class TestHostFromUrl:
    @pytest.mark.parametrize("url,expected", [
        ("https://www.example.com/path", "example.com"),
        ("http://example.com/", "example.com"),
        ("https://news.foo.io/a/b", "news.foo.io"),
        (None, None),
        ("", None),
        ("not a url", "not a url"),  # degenerate; not worth raising
    ])
    def test_extract(self, url, expected):
        assert _host_from_url(url) == expected


# ---------------------------------------------------------------------------
# Ticker formatting
# ---------------------------------------------------------------------------


class TestFmtTicker:
    def test_adds_us_suffix_when_missing(self, client):
        assert client._fmt_ticker("AAPL") == "AAPL.US"

    def test_preserves_existing_exchange(self, client):
        assert client._fmt_ticker("VOD.LSE") == "VOD.LSE"

    def test_uppercases_and_strips(self, client):
        assert client._fmt_ticker("  aapl  ") == "AAPL.US"


# ---------------------------------------------------------------------------
# get_prices
# ---------------------------------------------------------------------------


class TestGetPrices:
    def test_maps_full_response(self, client):
        client._session.get.return_value = _resp(200, [
            {"date": "2026-04-13", "open": 259.73, "high": 260.18, "low": 256.66,
             "close": 259.2, "adjusted_close": 258.96, "volume": 36234700},
            {"date": "2026-04-14", "open": 259.5, "high": 261.0, "low": 258.0,
             "close": 260.5, "adjusted_close": 260.26, "volume": 30000000},
        ])
        prices = client.get_prices("AAPL", "2026-04-13", "2026-04-14")
        assert len(prices) == 2
        assert prices[0].close == 259.2
        assert prices[0].volume == 36234700
        assert prices[0].time == "2026-04-13"

    def test_empty_when_not_a_list(self, client):
        client._session.get.return_value = _resp(200, {"error": "no data"})
        assert client.get_prices("AAPL", "2026-04-13", "2026-04-14") == []

    def test_403_returns_empty(self, client):
        client._session.get.return_value = _resp(403, "Forbidden")
        assert client.get_prices("AAPL", "2026-04-13", "2026-04-14") == []

    def test_passes_us_suffix_via_url(self, client):
        client._session.get.return_value = _resp(200, [])
        client.get_prices("MSFT", "2026-04-13", "2026-04-14")
        called_url = client._session.get.call_args[0][0]
        assert "/eod/MSFT.US" in called_url


# ---------------------------------------------------------------------------
# get_news (+ sentiment overlay)
# ---------------------------------------------------------------------------


class TestGetNewsWithSentimentOverlay:
    def _mock_two_endpoints(self, client, news_rows, sentiment_rows):
        """Set client._session.get to dispatch news/sentiments responses by URL."""
        def _dispatch(url, params=None, timeout=None):
            if "/news" in url:
                return _resp(200, news_rows)
            if "/sentiments" in url:
                return _resp(200, sentiment_rows)
            return _resp(404, {})

        client._session.get.side_effect = _dispatch

    def test_overlays_daily_sentiment_on_articles(self, client):
        news_rows = [
            {"date": "2026-05-13T10:00:00+00:00", "title": "h1",
             "link": "https://reuters.com/a", "content": "..."},
            {"date": "2026-05-12T14:00:00+00:00", "title": "h2",
             "link": "https://bloomberg.com/b", "content": "..."},
            {"date": "2026-04-01T08:00:00+00:00", "title": "h3",
             "link": "https://wsj.com/c", "content": "..."},
        ]
        sentiment_rows = {"AAPL.US": [
            {"date": "2026-05-13", "count": 92, "normalized": 0.70},   # positive
            {"date": "2026-05-12", "count": 73, "normalized": 0.05},   # neutral
            # No row for 2026-04-01 → that article gets sentiment=None
        ]}
        self._mock_two_endpoints(client, news_rows, sentiment_rows)

        articles = client.get_news("AAPL", "2026-05-13", "2026-04-01")
        assert len(articles) == 3
        assert articles[0].sentiment == "positive"
        assert articles[1].sentiment == "neutral"
        assert articles[2].sentiment is None
        # date extracted as YYYY-MM-DD from ISO timestamp
        assert articles[0].date == "2026-05-13"

    def test_falls_back_to_host_when_source_missing(self, client):
        self._mock_two_endpoints(client,
            news_rows=[{"date": "2026-05-13T00:00:00+00:00", "title": "x",
                        "link": "https://www.reuters.com/article/1"}],
            sentiment_rows={"AAPL.US": []},
        )
        articles = client.get_news("AAPL", "2026-05-13", "2026-05-12")
        assert articles[0].source == "reuters.com"

    def test_empty_when_news_not_a_list(self, client):
        self._mock_two_endpoints(client,
            news_rows={"error": "..."},
            sentiment_rows={"AAPL.US": []},
        )
        assert client.get_news("AAPL", "2026-05-13", "2026-05-12") == []


# ---------------------------------------------------------------------------
# Endpoints NOT included in the basic tier — graceful no-data
# ---------------------------------------------------------------------------


class TestBasicTierGracefulDegradation:
    def test_insider_returns_empty(self, client):
        assert client.get_insider_trades("AAPL", "2026-05-13") == []

    def test_financial_metrics_returns_empty(self, client):
        assert client.get_financial_metrics("AAPL", "2026-05-13") == []

    def test_company_facts_returns_none(self, client):
        assert client.get_company_facts("AAPL") is None

    def test_earnings_returns_none(self, client):
        assert client.get_earnings("AAPL") is None

    def test_earnings_history_returns_empty(self, client):
        assert client.get_earnings_history("AAPL") == []

    def test_market_cap_returns_none(self, client):
        assert client.get_market_cap("AAPL", "2026-05-13") is None


# ---------------------------------------------------------------------------
# Retry / error paths
# ---------------------------------------------------------------------------


class TestRetry:
    def test_429_then_200(self, client):
        client._session.get.side_effect = [
            _resp(429, "rate limit"),
            _resp(200, [{"date": "2026-05-13", "open": 1, "high": 1, "low": 1,
                         "close": 1, "adjusted_close": 1, "volume": 1}]),
        ]
        from unittest.mock import patch
        with patch("v2.data.eodhd_client.time.sleep"):
            prices = client.get_prices("AAPL", "2026-05-13", "2026-05-13")
        assert len(prices) == 1

    def test_500_returns_none_no_retry(self, client):
        client._session.get.return_value = _resp(500, "boom")
        assert client.get_prices("AAPL", "2026-05-13", "2026-05-13") == []
        assert client._session.get.call_count == 1
