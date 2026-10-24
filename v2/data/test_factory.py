"""Tests for the data provider factory (env-driven selection)."""

from __future__ import annotations

import pytest

from v2.data.client import FDClient
from v2.data.composite_client import CompositeClient
from v2.data.eodhd_client import EODHDClient
from v2.data.factory import (
    get_default_provider,
    get_provider_factory,
    make_data_client,
    recommend_max_workers,
)
from v2.data.finnhub_client import FinnhubClient


class TestDefaultProvider:
    def test_default_is_hybrid_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("SCANNER_DATA_PROVIDER", raising=False)
        assert get_default_provider() == "hybrid"

    def test_env_var_selects_finnhub(self, monkeypatch):
        monkeypatch.setenv("SCANNER_DATA_PROVIDER", "finnhub")
        assert get_default_provider() == "finnhub"

    def test_env_var_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("SCANNER_DATA_PROVIDER", "FINNHUB")
        assert get_default_provider() == "finnhub"


class TestMakeDataClient:
    def test_explicit_fd(self):
        client = make_data_client("fd")
        assert isinstance(client, FDClient)

    def test_explicit_finnhub(self):
        client = make_data_client("finnhub")
        assert isinstance(client, FinnhubClient)

    def test_explicit_eodhd(self):
        client = make_data_client("eodhd")
        assert isinstance(client, EODHDClient)

    def test_explicit_hybrid(self):
        client = make_data_client("hybrid")
        assert isinstance(client, CompositeClient)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown data provider"):
            make_data_client("yahoo")

    def test_uses_env_when_provider_none(self, monkeypatch):
        monkeypatch.setenv("SCANNER_DATA_PROVIDER", "finnhub")
        client = make_data_client()
        assert isinstance(client, FinnhubClient)


class TestProviderFactory:
    def test_returns_callable_for_fd(self):
        factory = get_provider_factory("fd")
        assert factory is FDClient
        assert isinstance(factory(), FDClient)

    def test_returns_callable_for_finnhub(self):
        factory = get_provider_factory("finnhub")
        assert factory is FinnhubClient

    def test_returns_callable_for_eodhd(self):
        factory = get_provider_factory("eodhd")
        assert factory is EODHDClient

    def test_returns_callable_for_hybrid(self):
        factory = get_provider_factory("hybrid")
        # Hybrid returns a builder function, not a class.
        assert callable(factory)
        assert isinstance(factory(), CompositeClient)


class TestRecommendMaxWorkers:
    def test_hybrid_default_caps_at_4(self, monkeypatch):
        # Default provider is hybrid → throttled by Finnhub's 60/min cap.
        monkeypatch.delenv("SCANNER_DATA_PROVIDER", raising=False)
        assert recommend_max_workers() == 4

    def test_fd_explicit_at_16(self):
        assert recommend_max_workers("fd") == 16

    def test_finnhub_caps_at_4(self):
        assert recommend_max_workers("finnhub") == 4

    def test_eodhd_at_16(self):
        # EODHD on its own has plenty of headroom.
        assert recommend_max_workers("eodhd") == 16

    def test_hybrid_capped_by_finnhub_bottleneck(self):
        # Bottleneck dominates: hybrid uses Finnhub for half the calls.
        assert recommend_max_workers("hybrid") == 4

    def test_explicit_fd(self):
        assert recommend_max_workers("fd") == 16
