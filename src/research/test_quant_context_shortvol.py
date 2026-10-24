"""Offline tests for the FINRA short-volume injection into QUANT CONTEXT.

No network: ``fetch_short_volume`` is patched with a stub everywhere it is
consulted (``src.research.quant_context.fetch_short_volume``). requests is never
imported or called. Gamma is forced OFF-data (fetch returns None) so these tests
isolate the short-volume block. Module state (enable flag + caches) is reset
around every test.
"""

from __future__ import annotations

import pytest

from src.research import quant_context as qc
from src.research.quant_context import (
    build_quant_context,
    clear_gamma_cache,
    flow_enabled,
    set_flow_enabled,
)
from src.research.shared_data import SharedData


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_flow_state(monkeypatch):
    """Reset flag + caches around each test; neutralise gamma so the
    short-volume block is tested in isolation."""
    set_flow_enabled(True)
    clear_gamma_cache()
    # Keep the gamma block out of the way unless a test wants it.
    monkeypatch.setattr(qc, "fetch_gamma_exposure", lambda t: None)
    yield
    set_flow_enabled(True)
    clear_gamma_cache()


def _shared() -> SharedData:
    """A minimal SharedData with enough price history to render a body."""
    prices = [{"close": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "volume": 1_000 + i} for i in range(30)]
    return SharedData(
        ticker="TST",
        scan_date="2026-06-05",
        prices=prices,
        financials=[],
        insider_trades=[],
        news=[],
        analyst_actions=[],
        analyst_targets=None,
        earnings_history=[],
        company_facts={"name": "Test Co"},
        sector_etf_prices=[],
        spy_prices=[],
    )


def _shortvol_dict() -> dict:
    """A rising short-pressure snapshot over 10 collected days."""
    return {
        "ticker": "TST",
        "date": "2026-06-05",
        "short_pct": 0.482,
        "short_volume": 4_820_000.0,
        "total_volume": 10_000_000.0,
        "avg_short_pct": 0.441,
        "trend": "rising",
        "n_days": 10,
    }


# --------------------------------------------------------------------------- #
# 1. Enabled + data present → block rendered with the label + %s + trend
# --------------------------------------------------------------------------- #


def test_short_volume_block_rendered(monkeypatch):
    monkeypatch.setattr(qc, "fetch_short_volume", lambda t: _shortvol_dict())

    out = build_quant_context(_shared(), "TST")

    assert "OFF-EXCHANGE SHORT PRESSURE" in out
    assert "SHORT PRESSURE" in out
    # Honest proxy labelling (NOT true dark-pool/ATS).
    assert "proxy" in out
    assert "NOT true dark-pool" in out
    # Latest % and avg % rendered (one-decimal percent).
    assert "48.2%" in out
    assert "44.1%" in out
    assert "2026-06-05" in out
    assert "10-day avg" in out
    assert "RISING" in out
    # Sits inside the QUANT CONTEXT (before the close marker).
    assert out.index("SHORT PRESSURE") < out.index("=== END QUANT CONTEXT ===")


def test_short_volume_block_after_gamma(monkeypatch):
    # When BOTH signals have data, short-volume is rendered AFTER dealer gamma.
    gamma = {
        "ticker": "TST",
        "spot": 107.0,
        "total_gex": -3.51e9,
        "regime": "negative",
        "call_gex": 1.0e9,
        "put_gex": 4.51e9,
        "walls": [{"strike": 740.0, "gamma_dollars": 0.94e9}],
        "gamma_flip": 107.0,
    }
    monkeypatch.setattr(qc, "fetch_gamma_exposure", lambda t: gamma)
    monkeypatch.setattr(qc, "fetch_short_volume", lambda t: _shortvol_dict())

    out = build_quant_context(_shared(), "TST")

    assert "DEALER GAMMA" in out
    assert "OFF-EXCHANGE SHORT PRESSURE" in out
    # Both in the same institutional area; gamma first, short-vol second.
    assert out.index("DEALER GAMMA") < out.index("OFF-EXCHANGE SHORT PRESSURE")


# --------------------------------------------------------------------------- #
# 2. Flag OFF → block absent, rest still renders
# --------------------------------------------------------------------------- #


def test_flag_off_omits_short_volume_block(monkeypatch):
    monkeypatch.setattr(qc, "fetch_short_volume", lambda t: _shortvol_dict())

    set_flow_enabled(False)
    try:
        out = build_quant_context(_shared(), "TST")
    finally:
        set_flow_enabled(True)

    assert "SHORT PRESSURE" not in out
    assert "=== QUANT CONTEXT" in out
    assert "=== END QUANT CONTEXT ===" in out
    assert flow_enabled() is True  # restored


# --------------------------------------------------------------------------- #
# 3. No FINRA data (None) → no block, no crash, context still renders
# --------------------------------------------------------------------------- #


def test_none_short_volume_omits_block(monkeypatch):
    monkeypatch.setattr(qc, "fetch_short_volume", lambda t: None)

    out = build_quant_context(_shared(), "TST")

    assert "SHORT PRESSURE" not in out
    assert "=== END QUANT CONTEXT ===" in out
    assert "TECHNICAL INDICATORS" in out  # body still rendered


# --------------------------------------------------------------------------- #
# 4. Cache: underlying fetch called once per ticker; clear resets
# --------------------------------------------------------------------------- #


def test_short_volume_cache_fetches_once_per_ticker(monkeypatch):
    calls = {"n": 0}

    def _counting_fetch(t):
        calls["n"] += 1
        return _shortvol_dict()

    monkeypatch.setattr(qc, "fetch_short_volume", _counting_fetch)

    for _ in range(5):
        build_quant_context(_shared(), "TST")
    assert calls["n"] == 1

    qc._get_short_volume("TST")
    assert calls["n"] == 1

    clear_gamma_cache()  # clears BOTH flow caches
    qc._get_short_volume("TST")
    assert calls["n"] == 2


def test_get_short_volume_caches_none_on_exception(monkeypatch):
    calls = {"n": 0}

    def _boom(t):
        calls["n"] += 1
        raise RuntimeError("FINRA exploded")

    monkeypatch.setattr(qc, "fetch_short_volume", _boom)

    assert qc._get_short_volume("TST") is None
    assert qc._get_short_volume("TST") is None  # cached None, not re-raised
    assert calls["n"] == 1
