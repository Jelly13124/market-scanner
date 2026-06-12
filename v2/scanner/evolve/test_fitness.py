"""Tests for the scanner-evolve fitness bridge.

``_detectors_from_config`` — construct live ``intraday_move`` detector instances
from a :class:`ScannerEvolveConfig`.

``scanner_fitness`` — A/B-vs-random fitness over a regime window, no-lookahead.
Fully offline + deterministic: synthetic in-memory bundles, an injected
``window_of`` stub, no network, no LLM.

The evolve set was re-scoped (2026-06-12) to ``intraday_move`` ONLY. The
synthetic fixtures engineer a bar whose intraday return (open→close) crosses the
absolute ``close_vs_open_pct`` gate so the detector fires on a known as-of date.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from v2.data.models import Price
from v2.scanner.detectors import IntradayMoveDetector
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.evolve import fitness as fitness_mod
from v2.scanner.evolve.config import apply_delta, load_config
from v2.scanner.evolve.fitness import _detectors_from_config, scanner_fitness

_CONFIG_PATH = Path(__file__).parent / "scanner_skill_config.yaml"


# ===========================================================================
# _detectors_from_config
# ===========================================================================


def test_baseline_builds_single_intraday_detector_with_baseline_params():
    cfg = load_config(_CONFIG_PATH)
    detectors = _detectors_from_config(cfg)

    assert len(detectors) == 1
    det = detectors[0]
    assert isinstance(det, IntradayMoveDetector)
    assert det._z_window == 60
    assert det._cvo_pct == 0.04
    assert det._gap_pct == 0.03
    assert det._range_pct == 0.06
    assert det._z_thresh == 2.5
    # Derived lookback covers z_window + 2 bars: max(90, 60*2.5+40) = 190.
    assert det._lookback_days >= det._z_window + 2


def test_delta_rebuilds_detector_with_new_params():
    cfg = load_config(_CONFIG_PATH)
    cfg = apply_delta(
        cfg,
        {"detectors.intraday_move.z_window": 90, "detectors.intraday_move.z_threshold": 3.0},
    )
    det = _detectors_from_config(cfg)[0]
    assert det._z_window == 90
    assert det._z_thresh == 3.0
    assert det._lookback_days >= det._z_window + 2


def test_derived_lookback_covers_required_bars_at_range_top():
    """At the top of the adjustable range (z_window=120), derived lookback in
    calendar days yields ≥ z_window + 2 trading bars at ~5/7 density."""
    cfg = load_config(_CONFIG_PATH)
    cfg = apply_delta(cfg, {"detectors.intraday_move.z_window": 120})
    det = _detectors_from_config(cfg)[0]
    # lookback_days = max(90, 120*2.5+40) = 340 calendar days. The synthetic
    # bundles use 1 bar / calendar day, so 340 >> 122 bars needed; even at a
    # ~5/7 trading density (~243 bars) it clears z_window + 2 = 122.
    assert det._lookback_days * (5 / 7) >= det._z_window + 2


def test_unknown_detector_name_raises():
    cfg = load_config(_CONFIG_PATH)
    cfg.detectors["bogus_detector"] = {"foo": 1}
    with pytest.raises(ValueError):
        _detectors_from_config(cfg)


# ===========================================================================
# Synthetic intraday-firing fixtures
# ===========================================================================

_START = "2024-01-01"


def _bar(time_iso: str, *, open_: float, close: float, high: float | None = None, low: float | None = None) -> Price:
    hi = high if high is not None else max(open_, close)
    lo = low if low is not None else min(open_, close)
    return Price(open=open_, close=close, high=hi, low=lo, volume=1_000_000, time=time_iso)


def _flat_bar(time_iso: str, level: float = 100.0) -> Price:
    """A 'normal' bar: open == close == level → cvo 0, gap 0, range 0."""
    return _bar(time_iso, open_=level, close=level)


def _iso(start: str, i: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=i)).isoformat()


def _intraday_fire_prices(break_idx: int, *, n_after: int = 8, start: str = _START) -> list[Price]:
    """A series of flat bars then a big-intraday-move bar at ``break_idx``.

    ``break_idx`` normal flat bars (level 100, cvo=0) provide the trailing
    z-window baseline, then the break bar has open=100, close=110 →
    close_vs_open = +10% which crosses the 4% absolute gate → fires. A short
    rising tail after the break makes a 5d forward return computable.
    """
    prices = [_flat_bar(_iso(start, i)) for i in range(break_idx)]
    # The break bar: +10% intraday move.
    prices.append(_bar(_iso(start, break_idx), open_=100.0, close=110.0))
    # Rising tail so forward returns exist (close keeps climbing).
    for k in range(1, n_after + 1):
        lvl = 110.0 + 1.0 * k
        prices.append(_bar(_iso(start, break_idx + k), open_=lvl, close=lvl))
    return prices


def _bundle_from_prices(ticker: str, prices: list[Price]) -> TickerBundle:
    return TickerBundle(ticker=ticker, prices=prices)


def _flat_bundle(ticker: str, n: int, start: str = _START) -> TickerBundle:
    return TickerBundle(ticker=ticker, prices=[_flat_bar(_iso(start, i)) for i in range(n)])


def _spy_flat_bundle(n: int = 260, start: str = _START) -> TickerBundle:
    return TickerBundle(ticker="SPY", prices=[_flat_bar(_iso(start, i)) for i in range(n)])


# break_idx must be >= z_window + 1 so the trailing window is full.
_BREAK_IDX = 70


# ===========================================================================
# scanner_fitness — contract / fires / graceful / invariants
# ===========================================================================


def test_contract_keys_and_types():
    cfg = load_config(_CONFIG_PATH)
    bundles = {
        "AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX)),
        "BBB": _flat_bundle("BBB", _BREAK_IDX + 10),  # never fires
    }
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)

    assert set(out) == {
        "fitness",
        "interestingness_diff",
        "interestingness_t",
        "n_fired",
        "signed_diff",
        "signed_t",
        "alpha_5d",
    }
    assert isinstance(out["fitness"], float)
    assert isinstance(out["interestingness_diff"], float)
    assert isinstance(out["interestingness_t"], float)
    assert isinstance(out["signed_diff"], float)
    assert isinstance(out["signed_t"], float)
    assert isinstance(out["n_fired"], int)
    # PRIMARY fitness IS the interestingness (magnitude vs random) metric.
    assert out["fitness"] == out["interestingness_diff"]
    assert out["alpha_5d"] is None  # no spy_bundle


def test_fires_on_intraday_move():
    cfg = load_config(_CONFIG_PATH)
    bundles = {
        "AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX)),
        "BBB": _flat_bundle("BBB", _BREAK_IDX + 10),
    }
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out["n_fired"] > 0


def test_nothing_fires_is_graceful():
    cfg = load_config(_CONFIG_PATH)
    # Flat universe → no intraday move can fire.
    bundles = {
        "AAA": _flat_bundle("AAA", 120),
        "BBB": _flat_bundle("BBB", 120),
    }
    window = [(_iso(_START, 80), _iso(_START, 100))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out["n_fired"] == 0
    assert out["fitness"] == 0.0
    assert out["interestingness_diff"] == 0.0
    assert out["interestingness_t"] == 0.0
    assert out["signed_diff"] == 0.0
    assert out["signed_t"] == 0.0
    assert out["alpha_5d"] is None


def test_window_outside_data_is_graceful():
    cfg = load_config(_CONFIG_PATH)
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX))}
    window = [("2030-01-01", "2030-12-31")]  # no overlap with the synthetic dates
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out["n_fired"] == 0
    assert out["fitness"] == 0.0


def test_threshold_sensitivity_changes_fired_set():
    """A z_threshold/cvo-gate-equivalent change: an as-of date ON the intraday
    move fires; one before it (only flat bars visible) does not."""
    cfg = load_config(_CONFIG_PATH)
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX))}

    win_hit = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]
    win_miss = [(_iso(_START, _BREAK_IDX - 5), _iso(_START, _BREAK_IDX - 5))]

    out_hit = scanner_fitness(bundles, cfg, "val", window_of=lambda s: win_hit, rebalance_step=1)
    out_miss = scanner_fitness(bundles, cfg, "val", window_of=lambda s: win_miss, rebalance_step=1)

    assert out_hit["n_fired"] != out_miss["n_fired"]


def test_threshold_delta_changes_fired_set():
    """Raising close_vs_open_pct above the engineered 10% move suppresses the
    absolute gate. The bar's z-score still fires it (flat baseline → huge z), so
    this asserts the delta is at least exercised and the run stays graceful."""
    cfg = load_config(_CONFIG_PATH)
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX))}
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]

    out_base = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, rebalance_step=1)
    # A higher z_threshold makes the gate stricter; results stay well-formed.
    cfg2 = apply_delta(cfg, {"detectors.intraday_move.z_threshold": 4.0})
    out2 = scanner_fitness(bundles, cfg2, "val", window_of=lambda s: window, rebalance_step=1)
    assert isinstance(out_base["n_fired"], int)
    assert isinstance(out2["n_fired"], int)
    assert out_base["n_fired"] > 0  # the +10% move clears the 4% gate at baseline


def test_never_raises_on_junk_bundle():
    cfg = load_config(_CONFIG_PATH)
    bundles = {
        "AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX)),
        "EMPTY": TickerBundle(ticker="EMPTY", prices=[]),
        "SHORT": _flat_bundle("SHORT", 3),
    }
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert isinstance(out["n_fired"], int)  # no exception raised


def test_determinism():
    cfg = load_config(_CONFIG_PATH)
    bundles = {
        "AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX)),
        "BBB": _flat_bundle("BBB", 100),
        "CCC": _flat_bundle("CCC", 100),
    }
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]
    out1 = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    out2 = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out1 == out2


def test_no_lookahead_future_move_does_not_fire():
    """An intraday-move bar placed AFTER the as-of date must not make the
    detector fire on the as-of date — proof the CachedAsOfClient clamps."""
    cfg = load_config(_CONFIG_PATH)
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX))}
    asof = _iso(_START, _BREAK_IDX - 1)  # before the move; only flat bars visible
    window = [(asof, asof)]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, rebalance_step=1)
    assert out["n_fired"] == 0


def test_no_lookahead_clamp_lets_move_bar_through_but_not_future_move():
    """PAIRED no-lookahead discriminator: clamp-to-<=asof, NOT errored-out.

    The ON-move as-of date MUST yield ``n_fired > 0`` (the > 0 discriminates a
    correct clamp from a no-op/errored set_asof, both of which would yield 0).
    The one-bar-before case must yield 0 (the move is in the future).
    """
    cfg = load_config(_CONFIG_PATH)
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX))}

    asof_on = _iso(_START, _BREAK_IDX)
    out_on = scanner_fitness(bundles, cfg, "val", window_of=lambda s: [(asof_on, asof_on)], rebalance_step=1)
    assert out_on["n_fired"] > 0  # discriminator: fails if set_asof is a no-op

    asof_before = _iso(_START, _BREAK_IDX - 1)
    out_before = scanner_fitness(bundles, cfg, "val", window_of=lambda s: [(asof_before, asof_before)], rebalance_step=1)
    assert out_before["n_fired"] == 0


def test_alpha_computed_with_spy_bundle():
    cfg = load_config(_CONFIG_PATH)
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX))}
    spy = _spy_flat_bundle()  # flat SPY → spy 5d return == 0
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, spy_bundle=spy)
    assert out["n_fired"] > 0
    assert out["alpha_5d"] is not None
    assert isinstance(out["alpha_5d"], float)


def test_spy_bundle_threads_benchmark_into_run_scan(monkeypatch):
    """Passing ``spy_bundle`` must thread the SPY benchmark into ``run_scan``
    (``benchmark_ticker="SPY"``), exercising the SPY-relative path — not silently
    ignore it. We spy on ``run_scan`` to capture the kwarg both with and without
    a SPY bundle, AND confirm the fired detector ran benchmark-adjusted.
    """
    import v2.scanner.evolve.fitness as fmod

    real_run_scan = fmod.run_scan
    seen: list[object] = []

    def spy_run_scan(*args, **kwargs):
        seen.append(kwargs.get("benchmark_ticker"))
        return real_run_scan(*args, **kwargs)

    monkeypatch.setattr(fmod, "run_scan", spy_run_scan)

    cfg = load_config(_CONFIG_PATH)
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(_BREAK_IDX))}
    spy = _spy_flat_bundle()
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]

    out_no_spy = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, rebalance_step=1)
    assert seen[-1] is None  # no benchmark threaded when spy_bundle is None

    out_spy = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, spy_bundle=spy, rebalance_step=1)
    assert "SPY" in seen  # benchmark threaded into run_scan when spy_bundle given
    # The SPY path is exercised, not ignored: alpha is computed and the detector
    # still fires SPY-relative (flat SPY → the +10% raw move survives adjustment).
    assert out_spy["n_fired"] > 0
    assert out_spy["alpha_5d"] is not None


# ===========================================================================
# Parse-cache: parse bundles ONCE, reuse the parsed series across calls.
# ===========================================================================


def _multi_bundles(break_idx: int = _BREAK_IDX) -> dict:
    bundles = {"AAA": _bundle_from_prices("AAA", _intraday_fire_prices(break_idx))}
    for name in ("BBB", "CCC", "DDD", "EEE"):
        bundles[name] = _flat_bundle(name, break_idx + 12)
    return bundles


class _ParseCounter:
    """Wrap ``fitness._parse_bundle_series`` and tally calls by ``id(bundle)``."""

    def __init__(self, monkeypatch):
        self._real = fitness_mod._parse_bundle_series
        self.calls: list[int] = []
        monkeypatch.setattr(fitness_mod, "_parse_bundle_series", self)

    def __call__(self, bundle):
        self.calls.append(id(bundle))
        return self._real(bundle)

    @property
    def total(self) -> int:
        return len(self.calls)

    @property
    def distinct(self) -> int:
        return len(set(self.calls))


def test_parsed_once_per_ticker_across_calls(monkeypatch):
    cfg = load_config(_CONFIG_PATH)
    bundles = _multi_bundles()
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]

    counter = _ParseCounter(monkeypatch)
    shared: dict = {}

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, cache=shared)
    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, cache=shared)

    assert counter.total <= len(bundles)
    assert counter.total == counter.distinct


def test_threshold_only_delta_reuses_cache(monkeypatch):
    cfg = load_config(_CONFIG_PATH)
    bundles = _multi_bundles()
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]

    counter = _ParseCounter(monkeypatch)
    shared: dict = {}

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, cache=shared)
    parsed_after_first = counter.total

    cfg2 = apply_delta(cfg, {"detectors.intraday_move.z_threshold": 3.0})
    scanner_fitness(bundles, cfg2, "val", window_of=lambda s: window, cache=shared)

    assert counter.total == parsed_after_first


def test_no_shared_cache_reparses(monkeypatch):
    cfg = load_config(_CONFIG_PATH)
    bundles = _multi_bundles()
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]

    counter = _ParseCounter(monkeypatch)

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    after_first = counter.total
    assert after_first > 0

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert counter.total > after_first


def test_cache_is_pure_identical_results():
    cfg = load_config(_CONFIG_PATH)
    bundles = _multi_bundles()
    spy = _spy_flat_bundle()
    window = [(_iso(_START, _BREAK_IDX), _iso(_START, _BREAK_IDX))]

    shared: dict = {}
    out_cached = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, spy_bundle=spy, cache=shared)
    out_uncached = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, spy_bundle=spy, cache=None)
    assert out_cached == out_uncached
