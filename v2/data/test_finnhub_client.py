"""Unit tests for FinnhubClient.

Mocks the session-level HTTP layer so nothing hits the wire. Covers the seven
endpoint mappings, transaction-code → buy/sell sign, market-cap millions→dollars
conversion, EPS surprise labeling, 429 retry, and per-instance throttling.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from v2.data.finnhub_client import (
    FinnhubClient,
    _label_eps_surprise,
    _safe_float,
)


def _resp(status: int, json_body) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body
    return r


@pytest.fixture()
def client():
    c = FinnhubClient(api_key="test", min_call_interval=0.0)
    c._session = MagicMock()
    return c


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize("actual,estimate,expected", [
        (1.20, 1.10, "BEAT"),
        (1.05, 1.10, "MISS"),
        (1.10, 1.10, "MEET"),
        (None, 1.10, None),
        (1.10, None, None),
    ])
    def test_label_eps_surprise(self, actual, estimate, expected):
        assert _label_eps_surprise(actual, estimate) == expected

    def test_safe_float_with_scale(self):
        assert _safe_float(3000, scale=1_000_000.0) == 3_000_000_000.0
        assert _safe_float(None) is None
        assert _safe_float("not a number") is None
        assert _safe_float(float("nan")) is None


# ---------------------------------------------------------------------------
# get_prices
# ---------------------------------------------------------------------------


class TestGetPrices:
    def test_maps_parallel_arrays(self, client):
        client._session.get.return_value = _resp(200, {
            "s": "ok",
            "o": [100.0, 101.0, 102.0],
            "h": [105.0, 106.0, 107.0],
            "l": [99.0, 100.0, 101.0],
            "c": [103.0, 104.0, 105.0],
            "v": [1_000_000, 1_100_000, 1_050_000],
            "t": [1726531200, 1726617600, 1726704000],
        })
        prices = client.get_prices("AAPL", "2024-09-01", "2024-09-30")
        assert len(prices) == 3
        assert prices[0].close == 103.0
        assert prices[0].volume == 1_000_000
        assert prices[0].time.startswith("2024-09-")

    def test_returns_empty_on_no_data_status(self, client):
        client._session.get.return_value = _resp(200, {"s": "no_data"})
        assert client.get_prices("AAPL", "2024-09-01", "2024-09-30") == []

    def test_returns_empty_on_malformed_body(self, client):
        client._session.get.return_value = _resp(200, {"s": "ok"})
        # Missing 'o', 'h', etc.
        assert client.get_prices("AAPL", "2024-09-01", "2024-09-30") == []


# ---------------------------------------------------------------------------
# get_news
# ---------------------------------------------------------------------------


class TestGetNews:
    def test_sentiment_is_always_none(self, client):
        client._session.get.return_value = _resp(200, [
            {"datetime": 1726531200, "headline": "h1", "source": "s1", "url": "u1"},
            {"datetime": 1726617600, "headline": "h2", "source": "s2", "url": "u2"},
        ])
        articles = client.get_news("AAPL", "2024-09-30", "2024-09-01")
        assert len(articles) == 2
        assert all(a.sentiment is None for a in articles)

    def test_returns_empty_when_finnhub_returns_dict_instead_of_list(self, client):
        client._session.get.return_value = _resp(200, {"error": "no data"})
        assert client.get_news("AAPL", "2024-09-30", "2024-09-01") == []

    def test_respects_limit(self, client):
        client._session.get.return_value = _resp(200, [
            {"datetime": 1726531200 + i, "headline": f"h{i}", "source": "s", "url": "u"}
            for i in range(30)
        ])
        articles = client.get_news("AAPL", "2024-09-30", "2024-09-01", limit=5)
        assert len(articles) == 5


# ---------------------------------------------------------------------------
# get_insider_trades
# ---------------------------------------------------------------------------


class TestGetInsiderTrades:
    def test_buy_code_maps_to_positive_shares(self, client):
        client._session.get.return_value = _resp(200, {
            "data": [
                {"name": "CEO", "change": 1000, "transactionPrice": 200.0,
                 "transactionCode": "P", "transactionDate": "2024-09-15",
                 "filingDate": "2024-09-17"},
            ],
        })
        trades = client.get_insider_trades("AAPL", "2024-09-30")
        assert len(trades) == 1
        assert trades[0].transaction_shares == 1000.0
        assert trades[0].transaction_value == 200_000.0
        assert trades[0].transaction_type == "P"

    def test_sell_code_maps_to_negative_shares(self, client):
        client._session.get.return_value = _resp(200, {
            "data": [
                {"name": "CFO", "change": 500, "transactionPrice": 200.0,
                 "transactionCode": "S", "transactionDate": "2024-09-15",
                 "filingDate": "2024-09-17"},
            ],
        })
        trades = client.get_insider_trades("AAPL", "2024-09-30")
        assert trades[0].transaction_shares == -500.0
        assert trades[0].transaction_value == -100_000.0

    def test_option_exercise_M_is_neutral_not_buy(self, client):
        """Regression: M = derivative conversion (option exercise). Used to be
        treated as a 'buy' which inflated insider clusters with non-discretionary
        flow. Now it's zero shares — informational only."""
        client._session.get.return_value = _resp(200, {
            "data": [
                {"name": "CEO", "change": 1000, "transactionPrice": 200.0,
                 "transactionCode": "M", "transactionDate": "2024-09-15",
                 "filingDate": "2024-09-17"},
            ],
        })
        trades = client.get_insider_trades("AAPL", "2024-09-30")
        assert trades[0].transaction_shares == 0.0
        assert trades[0].transaction_value is None

    def test_grant_A_is_neutral_not_buy(self, client):
        """A = grant/award. Not a discretionary purchase."""
        client._session.get.return_value = _resp(200, {
            "data": [
                {"name": "Director", "change": 500, "transactionPrice": 200.0,
                 "transactionCode": "A", "transactionDate": "2024-09-15",
                 "filingDate": "2024-09-17"},
            ],
        })
        trades = client.get_insider_trades("AAPL", "2024-09-30")
        assert trades[0].transaction_shares == 0.0

    def test_tax_withholding_F_is_neutral_not_sell(self, client):
        """F = tax withholding sale. Mechanical, not a conviction sale."""
        client._session.get.return_value = _resp(200, {
            "data": [
                {"name": "Exec", "change": 200, "transactionPrice": 200.0,
                 "transactionCode": "F", "transactionDate": "2024-09-15",
                 "filingDate": "2024-09-17"},
            ],
        })
        trades = client.get_insider_trades("AAPL", "2024-09-30")
        assert trades[0].transaction_shares == 0.0

    def test_unknown_code_maps_to_zero(self, client):
        client._session.get.return_value = _resp(200, {
            "data": [
                {"name": "Gift", "change": 100, "transactionPrice": 150.0,
                 "transactionCode": "G", "transactionDate": "2024-09-15",
                 "filingDate": "2024-09-17"},
            ],
        })
        trades = client.get_insider_trades("AAPL", "2024-09-30")
        assert trades[0].transaction_shares == 0.0
        assert trades[0].transaction_value is None


# ---------------------------------------------------------------------------
# get_company_facts + get_market_cap
# ---------------------------------------------------------------------------


class TestCompanyFactsAndMarketCap:
    def test_market_cap_converts_millions_to_dollars(self, client):
        client._session.get.return_value = _resp(200, {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "marketCapitalization": 3000,  # Finnhub returns in millions
            "finnhubIndustry": "Technology",
            "exchange": "NASDAQ",
            "country": "US",
        })
        mc = client.get_market_cap("AAPL", "2024-09-30")
        assert mc == 3_000_000_000.0

    def test_facts_populates_basic_metadata(self, client):
        client._session.get.return_value = _resp(200, {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "marketCapitalization": 3000,
            "finnhubIndustry": "Technology",
            "exchange": "NASDAQ",
            "country": "US",
        })
        facts = client.get_company_facts("AAPL")
        assert facts is not None
        assert facts.ticker == "AAPL"
        assert facts.name == "Apple Inc."
        assert facts.market_cap == 3_000_000_000.0
        assert facts.industry == "Technology"
        assert facts.is_active is True

    def test_facts_returns_none_on_empty_response(self, client):
        client._session.get.return_value = _resp(200, {})
        assert client.get_company_facts("AAPL") is None


# ---------------------------------------------------------------------------
# get_earnings_history
# ---------------------------------------------------------------------------


class TestGetQuote:
    def test_happy_path(self, client):
        client._session.get.return_value = _resp(200, {
            "c": 178.50, "h": 180.10, "l": 176.20, "o": 177.00,
            "pc": 175.00, "t": 1778869464, "d": 3.50, "dp": 2.0,
        })
        q = client.get_quote("AAPL")
        assert q is not None
        assert q.ticker == "AAPL"
        assert q.current_price == 178.50
        assert q.prev_close == 175.00
        assert q.percent_change == 2.0
        assert q.asof_timestamp == 1778869464

    def test_returns_none_when_zero_payload(self, client):
        # Finnhub returns all-zeros for unknown symbols.
        client._session.get.return_value = _resp(200, {
            "c": 0, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0,
        })
        assert client.get_quote("BOGUS") is None

    def test_returns_none_when_current_missing(self, client):
        client._session.get.return_value = _resp(200, {"pc": 100.0})
        assert client.get_quote("AAPL") is None

    def test_handles_missing_timestamp(self, client):
        client._session.get.return_value = _resp(200, {
            "c": 100.0, "pc": 99.0, "dp": 1.01,
        })
        q = client.get_quote("AAPL")
        assert q is not None
        assert q.asof_timestamp is None

    def test_returns_none_on_non_dict(self, client):
        client._session.get.return_value = _resp(200, "string response")
        assert client.get_quote("AAPL") is None


# ---------------------------------------------------------------------------
# get_earnings_history
# ---------------------------------------------------------------------------


class TestGetEarningsHistory:
    def test_synthesizes_records_with_beat_miss_meet(self, client):
        # /calendar/earnings returns {"earningsCalendar": [...]} with the
        # REAL announcement date in `date` (not the fiscal-period end).
        client._session.get.return_value = _resp(200, {"earningsCalendar": [
            {"date": "2024-10-31", "epsActual": 1.20, "epsEstimate": 1.10,
             "quarter": 3, "year": 2024, "symbol": "AAPL"},
            {"date": "2024-07-30", "epsActual": 1.00, "epsEstimate": 1.15,
             "quarter": 2, "year": 2024, "symbol": "AAPL"},
            {"date": "2024-05-02", "epsActual": 1.10, "epsEstimate": 1.10,
             "quarter": 1, "year": 2024, "symbol": "AAPL"},
        ]})
        records = client.get_earnings_history("AAPL", limit=3)
        assert len(records) == 3
        # Sorted newest-first by filing_date.
        assert records[0].filing_date == "2024-10-31"
        assert records[1].filing_date == "2024-07-30"
        assert records[2].filing_date == "2024-05-02"
        assert records[0].quarterly.eps_surprise == "BEAT"
        assert records[1].quarterly.eps_surprise == "MISS"
        assert records[2].quarterly.eps_surprise == "MEET"
        assert records[0].source_type == "finnhub"

    def test_empty_when_not_a_dict(self, client):
        client._session.get.return_value = _resp(200, [])
        assert client.get_earnings_history("AAPL") == []

    def test_empty_when_calendar_missing(self, client):
        client._session.get.return_value = _resp(200, {"error": "..."})
        assert client.get_earnings_history("AAPL") == []


# ---------------------------------------------------------------------------
# get_financial_metrics
# ---------------------------------------------------------------------------


class TestGetFinancialMetrics:
    def test_returns_single_snapshot(self, client):
        # Finnhub returns percentage fields in percent form (45 = 45%); the
        # client divides by 100 so downstream agents see decimal form.
        client._session.get.return_value = _resp(200, {
            "metric": {
                "marketCapitalization": 3000,
                "peTTM": 30.5,
                "roeTTM": 45.0,           # 45% in Finnhub's wire format
                "grossMarginTTM": 42.0,   # 42%
                "netProfitMarginTTM": 25.0,
                "revenueGrowthTTMYoy": 8.5,
                "epsTTM": 6.50,
            },
        })
        metrics = client.get_financial_metrics("AAPL", "2024-09-30")
        assert len(metrics) == 1
        assert metrics[0].ticker == "AAPL"
        assert metrics[0].market_cap == 3_000_000_000.0
        assert metrics[0].price_to_earnings_ratio == 30.5  # ratios stay as-is
        assert metrics[0].return_on_equity == 0.45         # 45 → 0.45
        assert metrics[0].gross_margin == 0.42
        assert metrics[0].net_margin == 0.25
        assert abs(metrics[0].revenue_growth - 0.085) < 1e-9
        assert metrics[0].earnings_per_share == 6.50       # dollar amount stays

    def test_empty_when_no_metric(self, client):
        client._session.get.return_value = _resp(200, {"metric": {}})
        assert client.get_financial_metrics("AAPL", "2024-09-30") == []


# ---------------------------------------------------------------------------
# Retry / error paths
# ---------------------------------------------------------------------------


class TestRetry:
    def test_429_then_200_succeeds(self, client):
        client._session.get.side_effect = [
            _resp(429, {}),
            _resp(429, {}),
            _resp(200, {"s": "ok", "o": [1.0], "h": [1.0], "l": [1.0],
                       "c": [1.0], "v": [10], "t": [1726531200]}),
        ]
        with patch("v2.data.finnhub_client.time.sleep"):  # don't actually sleep
            prices = client.get_prices("AAPL", "2024-09-01", "2024-09-02")
        assert len(prices) == 1

    def test_400_returns_empty_no_retry(self, client):
        client._session.get.return_value = _resp(400, {})
        assert client.get_prices("AAPL", "2024-09-01", "2024-09-02") == []
        # 400 doesn't trigger retry — exactly one call.
        assert client._session.get.call_count == 1


# ---------------------------------------------------------------------------
# Per-instance throttle
# ---------------------------------------------------------------------------


class TestThrottle:
    def test_min_call_interval_delays_successive_calls(self):
        c = FinnhubClient(api_key="test", min_call_interval=0.05)
        c._session = MagicMock()
        c._session.get.return_value = _resp(200, {})
        start = time.monotonic()
        c._get("/x", {})
        c._get("/x", {})
        c._get("/x", {})
        elapsed = time.monotonic() - start
        # Three calls with ~50ms gap → elapsed should be ≥ 100ms (two gaps).
        assert elapsed >= 0.08, f"throttle did not delay: elapsed={elapsed:.3f}s"
