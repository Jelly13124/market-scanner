"""Phase 6B: universe loader for backtest engine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.lab.engine.universe import load_universe_tickers, UniverseError
from src.lab.spec.strategy import UniverseSpec


def test_sp500_loads_from_static_list():
    spec = UniverseSpec(kind="sp500")
    tickers = load_universe_tickers(spec, db=None)
    assert "NVDA" in tickers or "AAPL" in tickers
    assert len(tickers) > 100  # SP500 has ~500


def test_nasdaq100_loads():
    spec = UniverseSpec(kind="nasdaq100")
    tickers = load_universe_tickers(spec, db=None)
    assert 50 < len(tickers) < 150


def test_watchlist_resolves_from_db():
    spec = UniverseSpec(kind="watchlist", watchlist_id=42)
    fake_row = type("W", (), {"tickers": ["NVDA", "AVGO", "AMD"]})()
    with patch("src.lab.engine.universe.UserWatchlistRepository") as mock_repo_cls:
        mock_repo_cls.return_value.get.return_value = fake_row
        tickers = load_universe_tickers(spec, db=object())
    assert tickers == ["NVDA", "AVGO", "AMD"]


def test_watchlist_missing_raises():
    spec = UniverseSpec(kind="watchlist", watchlist_id=999)
    with patch("src.lab.engine.universe.UserWatchlistRepository") as mock_repo_cls:
        mock_repo_cls.return_value.get.return_value = None
        with pytest.raises(UniverseError):
            load_universe_tickers(spec, db=object())


def test_watchlist_empty_raises():
    spec = UniverseSpec(kind="watchlist", watchlist_id=42)
    fake_row = type("W", (), {"tickers": []})()
    with patch("src.lab.engine.universe.UserWatchlistRepository") as mock_repo_cls:
        mock_repo_cls.return_value.get.return_value = fake_row
        with pytest.raises(UniverseError):
            load_universe_tickers(spec, db=object())
