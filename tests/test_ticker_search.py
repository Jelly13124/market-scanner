"""Tests for the ticker autocomplete route (Phase 5B).

Directly invokes the rank function — no DB needed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_tickers_mod():
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "app" / "backend" / "routes" / "tickers.py"
    spec = importlib.util.spec_from_file_location("_tickers_routes_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


tickers_mod = _load_tickers_mod()


class TestTickerSearch:
    def test_empty_query_returns_up_to_20(self):
        results = tickers_mod.search_tickers(q="")
        assert isinstance(results, list)
        assert 0 < len(results) <= 20
        # All TickerSearchResult instances with non-empty ticker.
        for r in results:
            assert r.ticker.isupper()
            assert r.ticker.strip()

    def test_nvd_includes_nvda_near_top(self):
        results = tickers_mod.search_tickers(q="NVD")
        tickers = [r.ticker for r in results]
        assert "NVDA" in tickers
        # NVDA starts with "NVD" → must be in the startswith tier (first).
        # No exact-match "NVD" symbol exists, so NVDA should be #1.
        assert tickers[0] == "NVDA"

    def test_unknown_query_returns_empty(self):
        results = tickers_mod.search_tickers(q="ZZZZZZ")
        assert results == []
