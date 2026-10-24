"""SharedData should fetch once per (ticker, scan_date) and reuse on
subsequent calls within the same Python process. Caching is just a
module-level dict — no Redis."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from src.research.shared_data import SharedData, fetch_shared_data, _CACHE


def _clear_cache():
    _CACHE.clear()


class TestSharedDataCache:
    def setup_method(self):
        _clear_cache()

    @patch("src.research.shared_data._fetch_raw")
    def test_cache_hit_avoids_refetch(self, mock_fetch):
        mock_fetch.return_value = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={}, sector_etf_prices=[],
            spy_prices=[],
        )
        d1 = fetch_shared_data("NVDA", "2026-05-22")
        d2 = fetch_shared_data("NVDA", "2026-05-22")
        assert d1 is d2  # exact object identity → cache hit
        assert mock_fetch.call_count == 1

    @patch("src.research.shared_data._fetch_raw")
    def test_different_date_different_fetch(self, mock_fetch):
        mock_fetch.side_effect = lambda t, d, market="us": SharedData(
            ticker=t, scan_date=d,
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={}, sector_etf_prices=[],
            spy_prices=[],
        )
        fetch_shared_data("NVDA", "2026-05-22")
        fetch_shared_data("NVDA", "2026-05-23")
        assert mock_fetch.call_count == 2


class TestSharedDataShape:
    def test_dataclass_fields(self):
        d = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={"sector": "Tech"},
            sector_etf_prices=[], spy_prices=[],
        )
        assert d.ticker == "NVDA"
        assert d.company_facts == {"sector": "Tech"}
