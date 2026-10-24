"""Offline tests for the dealer-gamma (GEX) injection into QUANT CONTEXT.

No network: ``fetch_gamma_exposure`` is patched with a stub everywhere it is
consulted (``src.research.quant_context.fetch_gamma_exposure``). yfinance is
never imported or called. Module state (enable flag + per-ticker cache) is
reset around every test so cases don't leak into one another.
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
def _reset_flow_state():
    """Reset the flag + cache before and after each test (no cross-leak)."""
    set_flow_enabled(True)
    clear_gamma_cache()
    yield
    set_flow_enabled(True)
    clear_gamma_cache()


def _shared() -> SharedData:
    """A minimal SharedData with enough price history to render a body."""
    prices = [{"close": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "volume": 1_000 + i} for i in range(30)]
    return SharedData(
        ticker="TST",
        scan_date="2026-06-04",
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


def _negative_gamma_dict() -> dict:
    """A NEGATIVE-regime gamma snapshot with walls + a flip strike."""
    return {
        "ticker": "TST",
        "spot": 107.0,
        "total_gex": -3.51e9,
        "regime": "negative",
        "call_gex": 1.0e9,
        "put_gex": 4.51e9,
        "walls": [
            {"strike": 740.0, "gamma_dollars": 0.94e9},
            {"strike": 745.0, "gamma_dollars": 0.82e9},
            {"strike": 735.0, "gamma_dollars": 0.59e9},
        ],
        "gamma_flip": 107.0,
    }


# --------------------------------------------------------------------------- #
# 1. Enabled + NEGATIVE regime → block rendered with key facts
# --------------------------------------------------------------------------- #


def test_negative_regime_block_rendered(monkeypatch):
    monkeypatch.setattr(qc, "fetch_gamma_exposure", lambda t: _negative_gamma_dict())

    out = build_quant_context(_shared(), "TST")

    assert "DEALER GAMMA" in out
    assert "NEGATIVE" in out
    # net GEX rendered compactly in billions.
    assert "-$3.51B" in out
    # at least one wall strike present.
    assert "740" in out
    # block sits inside the QUANT CONTEXT (before the close marker).
    assert out.index("DEALER GAMMA") < out.index("=== END QUANT CONTEXT ===")


# --------------------------------------------------------------------------- #
# 2. Flag OFF → block absent, rest still renders
# --------------------------------------------------------------------------- #


def test_flag_off_omits_block(monkeypatch):
    monkeypatch.setattr(qc, "fetch_gamma_exposure", lambda t: _negative_gamma_dict())

    set_flow_enabled(False)
    try:
        out = build_quant_context(_shared(), "TST")
    finally:
        set_flow_enabled(True)

    assert "DEALER GAMMA" not in out
    # rest of the context still present.
    assert "=== QUANT CONTEXT" in out
    assert "=== END QUANT CONTEXT ===" in out
    assert flow_enabled() is True  # restored


# --------------------------------------------------------------------------- #
# 3. No options data (None) → no block, no crash, context still renders
# --------------------------------------------------------------------------- #


def test_none_gamma_omits_block(monkeypatch):
    monkeypatch.setattr(qc, "fetch_gamma_exposure", lambda t: None)

    out = build_quant_context(_shared(), "TST")

    assert "DEALER GAMMA" not in out
    assert "=== END QUANT CONTEXT ===" in out
    assert "TECHNICAL INDICATORS" in out  # body still rendered


def test_flat_regime_omits_block(monkeypatch):
    flat = {"ticker": "TST", "spot": 100.0, "total_gex": 0.0, "regime": "flat", "call_gex": 0.0, "put_gex": 0.0, "walls": [], "gamma_flip": None}
    monkeypatch.setattr(qc, "fetch_gamma_exposure", lambda t: flat)

    out = build_quant_context(_shared(), "TST")

    assert "DEALER GAMMA" not in out


# --------------------------------------------------------------------------- #
# 4. Cache: underlying fetch called once per ticker; clear_gamma_cache resets
# --------------------------------------------------------------------------- #


def test_cache_fetches_once_per_ticker(monkeypatch):
    calls = {"n": 0}

    def _counting_fetch(t):
        calls["n"] += 1
        return _negative_gamma_dict()

    monkeypatch.setattr(qc, "fetch_gamma_exposure", _counting_fetch)

    # Many section-style calls for the same ticker.
    for _ in range(5):
        build_quant_context(_shared(), "TST")
    assert calls["n"] == 1

    # Direct _get_gamma repeats also hit the cache.
    qc._get_gamma("TST")
    assert calls["n"] == 1

    # clear → next access refetches.
    clear_gamma_cache()
    qc._get_gamma("TST")
    assert calls["n"] == 2


def test_get_gamma_caches_none_on_exception(monkeypatch):
    calls = {"n": 0}

    def _boom(t):
        calls["n"] += 1
        raise RuntimeError("yfinance exploded")

    monkeypatch.setattr(qc, "fetch_gamma_exposure", _boom)

    assert qc._get_gamma("TST") is None
    assert qc._get_gamma("TST") is None  # cached None, not re-raised
    assert calls["n"] == 1
