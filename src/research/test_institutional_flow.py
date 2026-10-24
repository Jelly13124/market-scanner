"""Offline tests for the gamma-exposure (GEX) module.

No network: the live adapter is exercised only through an injected stub
``fetch_fn``. yfinance is never imported or called here.
"""

from __future__ import annotations

import math

from src.research.institutional_flow import (
    _bs_gamma,
    compute_gex,
    fetch_gamma_exposure,
)


# --------------------------------------------------------------------------- #
# _bs_gamma
# --------------------------------------------------------------------------- #


def test_bs_gamma_atm_is_positive_and_finite():
    g = _bs_gamma(spot=100.0, strike=100.0, iv=0.30, t_years=0.25)
    assert g > 0.0
    assert math.isfinite(g)


def test_bs_gamma_matches_closed_form():
    # Cross-check against a direct hand computation of the same formula.
    spot, strike, iv, t, r = 100.0, 100.0, 0.30, 0.25, 0.04
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    expected = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * d1 * d1) / (spot * iv * sqrt_t)
    assert _bs_gamma(spot, strike, iv, t) == expected


def test_bs_gamma_guards_return_zero():
    assert _bs_gamma(100.0, 100.0, 0.0, 0.25) == 0.0  # iv <= 0
    assert _bs_gamma(100.0, 100.0, -0.1, 0.25) == 0.0  # iv < 0
    assert _bs_gamma(100.0, 100.0, 0.30, 0.0) == 0.0  # t <= 0
    assert _bs_gamma(100.0, 100.0, 0.30, -1.0) == 0.0  # t < 0
    assert _bs_gamma(0.0, 100.0, 0.30, 0.25) == 0.0  # spot <= 0
    assert _bs_gamma(100.0, 0.0, 0.30, 0.25) == 0.0  # strike <= 0


def test_bs_gamma_peaks_near_atm():
    # Gamma should be largest at-the-money and fall off in the wings.
    atm = _bs_gamma(100.0, 100.0, 0.30, 0.25)
    deep_otm = _bs_gamma(100.0, 200.0, 0.30, 0.25)
    deep_itm = _bs_gamma(100.0, 50.0, 0.30, 0.25)
    assert atm > deep_otm
    assert atm > deep_itm


# --------------------------------------------------------------------------- #
# compute_gex
# --------------------------------------------------------------------------- #


def _opt(type_, strike, oi, iv=0.30, t=0.25):
    return {"type": type_, "strike": strike, "open_interest": oi, "iv": iv, "t_years": t}


def test_compute_gex_calls_dominate_positive():
    spot = 100.0
    chains = [
        _opt("call", 100.0, oi=1000.0),
        _opt("call", 105.0, oi=500.0),
        _opt("put", 95.0, oi=100.0),
    ]
    out = compute_gex(spot, chains)
    assert out["total_gex"] > 0.0
    assert out["regime"] == "positive"
    assert out["call_gex"] > out["put_gex"]
    # Net is exactly calls minus puts.
    assert math.isclose(out["total_gex"], out["call_gex"] - out["put_gex"])


def test_compute_gex_puts_dominate_negative():
    spot = 100.0
    chains = [
        _opt("call", 100.0, oi=100.0),
        _opt("put", 100.0, oi=1000.0),
        _opt("put", 95.0, oi=500.0),
    ]
    out = compute_gex(spot, chains)
    assert out["total_gex"] < 0.0
    assert out["regime"] == "negative"
    assert out["put_gex"] > out["call_gex"]


def test_compute_gex_walls_sorted_desc_by_abs():
    spot = 100.0
    # Strike 100 gets the most OI -> biggest wall; 110 least.
    chains = [
        _opt("call", 100.0, oi=2000.0),
        _opt("put", 100.0, oi=2000.0),
        _opt("call", 105.0, oi=800.0),
        _opt("put", 95.0, oi=400.0),
        _opt("call", 110.0, oi=50.0),
    ]
    out = compute_gex(spot, chains)
    walls = out["walls"]
    # Four distinct strikes: 100 (call+put aggregated), 105, 95, 110.
    assert len(walls) == 4
    mags = [abs(w["gamma_dollars"]) for w in walls]
    assert mags == sorted(mags, reverse=True)
    # The 100-strike (call+put OI aggregated) should be the top wall.
    assert walls[0]["strike"] == 100.0


def test_compute_gex_walls_capped_at_five():
    spot = 100.0
    chains = [_opt("call", float(90 + i), oi=100.0 + i) for i in range(12)]
    out = compute_gex(spot, chains)
    assert len(out["walls"]) == 5


def test_compute_gex_walls_aggregate_call_and_put_per_strike():
    spot = 100.0
    chains = [_opt("call", 100.0, oi=1000.0), _opt("put", 100.0, oi=1000.0)]
    out = compute_gex(spot, chains)
    # One strike, aggregating both legs.
    assert len(out["walls"]) == 1
    assert out["walls"][0]["strike"] == 100.0
    # Wall magnitude = call_gex + put_gex (both positive dollar-gamma).
    assert math.isclose(out["walls"][0]["gamma_dollars"], out["call_gex"] + out["put_gex"])


def test_compute_gex_dollar_scaling_formula():
    # Single option: verify the exact dollar-gamma scaling end to end.
    spot = 100.0
    strike, iv, t, oi = 100.0, 0.30, 0.25, 1000.0
    out = compute_gex(spot, [_opt("call", strike, oi=oi, iv=iv, t=t)])
    g = _bs_gamma(spot, strike, iv, t)
    expected = g * oi * 100.0 * spot * spot * 0.01
    assert math.isclose(out["call_gex"], expected)
    assert math.isclose(out["total_gex"], expected)


def test_compute_gex_gamma_flip_between_put_and_call_clusters():
    # Puts concentrated low, calls concentrated high -> cumulative net GEX
    # walks from negative (put side) up through zero into positive (call side).
    spot = 100.0
    chains = [
        _opt("put", 90.0, oi=2000.0),
        _opt("put", 95.0, oi=1500.0),
        _opt("call", 105.0, oi=1500.0),
        _opt("call", 110.0, oi=2000.0),
    ]
    out = compute_gex(spot, chains)
    flip = out["gamma_flip"]
    assert flip is not None
    # Crossing happens somewhere between the put cluster and call cluster.
    assert 90.0 <= flip <= 110.0


def test_compute_gex_gamma_flip_none_for_single_strike():
    out = compute_gex(100.0, [_opt("call", 100.0, oi=1000.0)])
    assert out["gamma_flip"] is None


def test_compute_gex_empty_chains_flat():
    out = compute_gex(100.0, [])
    assert out == {
        "total_gex": 0.0,
        "regime": "flat",
        "call_gex": 0.0,
        "put_gex": 0.0,
        "walls": [],
        "gamma_flip": None,
    }


def test_compute_gex_zero_spot_flat():
    out = compute_gex(0.0, [_opt("call", 100.0, oi=1000.0)])
    assert out["regime"] == "flat"
    assert out["total_gex"] == 0.0


def test_compute_gex_all_degenerate_options_flat():
    # Non-empty chain but every option contributes no gamma (zero OI / zero t).
    spot = 100.0
    chains = [
        _opt("call", 100.0, oi=0.0),
        _opt("put", 95.0, oi=0.0, t=0.0),
    ]
    out = compute_gex(spot, chains)
    assert out["regime"] == "flat"
    assert out["walls"] == []
    assert out["total_gex"] == 0.0


def test_compute_gex_skips_malformed_options_without_raising():
    spot = 100.0
    chains = [
        {"type": "call", "strike": 100.0, "open_interest": 1000.0, "iv": 0.30, "t_years": 0.25},
        {"type": "call"},  # missing keys
        {"type": "weird", "strike": 100.0, "open_interest": 1.0, "iv": 0.3, "t_years": 0.25},
        {"type": "put", "strike": "nan-ish", "open_interest": 1.0, "iv": 0.3, "t_years": 0.25},
    ]
    out = compute_gex(spot, chains)  # must not raise
    assert out["total_gex"] > 0.0
    assert out["call_gex"] > 0.0
    assert out["put_gex"] == 0.0


# --------------------------------------------------------------------------- #
# fetch_gamma_exposure (stubbed fetch_fn — no network)
# --------------------------------------------------------------------------- #


def test_fetch_gamma_exposure_with_stub_returns_dict():
    spot = 100.0
    chains = [
        _opt("call", 100.0, oi=1000.0),
        _opt("put", 95.0, oi=500.0),
    ]

    def stub(ticker, max_expiries):
        assert ticker == "AAPL"
        assert max_expiries == 8
        return spot, chains

    out = fetch_gamma_exposure("AAPL", fetch_fn=stub)
    assert out is not None
    assert out["ticker"] == "AAPL"
    assert out["spot"] == spot
    # GEX fields are merged in.
    assert "total_gex" in out
    assert "regime" in out
    assert "walls" in out
    assert "gamma_flip" in out
    assert out["total_gex"] == compute_gex(spot, chains)["total_gex"]


def test_fetch_gamma_exposure_passes_max_expiries():
    captured = {}

    def stub(ticker, max_expiries):
        captured["max_expiries"] = max_expiries
        return 100.0, [_opt("call", 100.0, oi=10.0)]

    fetch_gamma_exposure("MSFT", max_expiries=3, fetch_fn=stub)
    assert captured["max_expiries"] == 3


def test_fetch_gamma_exposure_returns_none_on_fetch_error():
    def boom(ticker, max_expiries):
        raise RuntimeError("network down")

    out = fetch_gamma_exposure("AAPL", fetch_fn=boom)
    assert out is None  # best-effort: swallow the error


def test_fetch_gamma_exposure_empty_chain_is_flat_not_none():
    def stub(ticker, max_expiries):
        return 100.0, []

    out = fetch_gamma_exposure("AAPL", fetch_fn=stub)
    assert out is not None
    assert out["ticker"] == "AAPL"
    assert out["regime"] == "flat"
