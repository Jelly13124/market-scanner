"""Phase 8 Task 13: A-share market routing in shared_data.

When ``fetch_shared_data`` is called with ``market="cn"``:
  - The benchmark series swaps from SPY to 000300.SH (沪深300).
  - The sector ETF lookup swaps from the SPDR _SECTOR_ETF table to
    SW1 indices via ``v2.data.ashare.sw_sector_map.sw1_index_code``.

Default ``market="us"`` preserves Phase 4-7 behavior (SPY + SPDR).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.research.shared_data import (
    SharedData,
    _CACHE,
    _fetch_raw,
    fetch_shared_data,
)


def _clear_cache() -> None:
    _CACHE.clear()


def _fake_facts(sector: str) -> MagicMock:
    facts = MagicMock()
    facts.model_dump.return_value = {"sector": sector, "industry": sector}
    return facts


def _build_mock_client(sector: str) -> MagicMock:
    """A fake DataClient that records every get_prices call so the test
    can assert on which benchmark ticker was requested."""
    client = MagicMock()
    client.get_prices.return_value = []
    client.get_financial_metrics.return_value = []
    client.get_insider_trades.return_value = []
    client.get_news.return_value = []
    client.get_earnings_history.return_value = []
    client.get_company_facts.return_value = _fake_facts(sector)
    # Optional methods — keep them off so hasattr() falls through cleanly.
    del client.get_analyst_actions
    del client.get_analyst_targets
    return client


class TestUSDefault:
    def setup_method(self) -> None:
        _clear_cache()

    @patch("v2.data.factory.get_provider_factory")
    def test_us_uses_spy_and_spdr(self, mock_factory) -> None:
        client = _build_mock_client(sector="Technology")
        mock_factory.return_value = lambda: client

        bundle = _fetch_raw("NVDA", "2026-05-26", market="us")

        # SPY benchmark was fetched
        spy_calls = [c for c in client.get_prices.call_args_list
                     if c.args and c.args[0] == "SPY"]
        assert len(spy_calls) == 1, "expected exactly one SPY fetch"

        # Sector ETF was the SPDR XLK
        xlk_calls = [c for c in client.get_prices.call_args_list
                     if c.args and c.args[0] == "XLK"]
        assert len(xlk_calls) == 1, "expected SPDR XLK lookup for Technology"

        assert bundle.ticker == "NVDA"


class TestCNRouting:
    def setup_method(self) -> None:
        _clear_cache()

    @patch("v2.data.factory.get_provider_factory")
    def test_cn_uses_csi300_and_sw1(self, mock_factory) -> None:
        # Eastmoney F10 SECTOR_NAME for 贵州茅台
        client = _build_mock_client(sector="食品饮料")
        mock_factory.return_value = lambda: client

        bundle = _fetch_raw("600519.SH", "2026-05-26", market="cn")

        # CSI 300 benchmark, not SPY
        csi_calls = [c for c in client.get_prices.call_args_list
                     if c.args and c.args[0] == "000300.SH"]
        assert len(csi_calls) == 1, "expected one 000300.SH (CSI 300) fetch"

        spy_calls = [c for c in client.get_prices.call_args_list
                     if c.args and c.args[0] == "SPY"]
        assert spy_calls == [], "SPY must not be fetched for cn market"

        # SW1 食品饮料 -> 801120.SH
        sw1_calls = [c for c in client.get_prices.call_args_list
                     if c.args and c.args[0] == "801120.SH"]
        assert len(sw1_calls) == 1, "expected SW1 801120.SH for 食品饮料"

        assert bundle.ticker == "600519.SH"

    @patch("v2.data.factory.get_provider_factory")
    def test_cn_unknown_sector_skips_sector_etf(self, mock_factory) -> None:
        client = _build_mock_client(sector="not-a-real-sw1-sector")
        mock_factory.return_value = lambda: client

        bundle = _fetch_raw("600519.SH", "2026-05-26", market="cn")

        # No SW1 fetch — only the CSI 300 benchmark
        non_ticker_calls = [
            c for c in client.get_prices.call_args_list
            if c.args and c.args[0] != "600519.SH"
        ]
        assert len(non_ticker_calls) == 1
        assert non_ticker_calls[0].args[0] == "000300.SH"
        assert bundle.sector_etf_prices == []


class TestCacheKeyIncludesMarket:
    """Same (ticker, scan_date) with different market must NOT collide
    in the module-level cache."""

    def setup_method(self) -> None:
        _clear_cache()

    @patch("src.research.shared_data._fetch_raw")
    def test_market_in_cache_key(self, mock_fetch) -> None:
        def make(ticker: str, scan_date: str, market: str = "us") -> SharedData:
            return SharedData(
                ticker=ticker, scan_date=scan_date,
                prices=[], financials=[], insider_trades=[],
                news=[], analyst_actions=[], analyst_targets=None,
                earnings_history=[], company_facts={"market": market},
                sector_etf_prices=[], spy_prices=[],
            )
        mock_fetch.side_effect = make

        d_us = fetch_shared_data("600519.SH", "2026-05-26", market="us")
        d_cn = fetch_shared_data("600519.SH", "2026-05-26", market="cn")

        assert d_us is not d_cn
        assert mock_fetch.call_count == 2
