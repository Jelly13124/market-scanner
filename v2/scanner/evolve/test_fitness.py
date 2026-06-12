"""Tests for the scanner-evolve fitness bridge.

Task 2 scope: ``_detectors_from_config`` — construct live detector instances
from a :class:`ScannerEvolveConfig`.

Task 3 scope: ``scanner_fitness`` — A/B-vs-random fitness over a regime window,
no-lookahead. Fully offline + deterministic: synthetic in-memory bundles, an
injected ``window_of`` stub, no network, no LLM.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from v2.data.models import Price
from v2.scanner.detectors import (
    GapDetector,
    HighBreakoutDetector,
    MaCrossDetector,
    RsiDivergenceDetector,
)
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.evolve import fitness as fitness_mod
from v2.scanner.evolve.config import apply_delta, load_config
from v2.scanner.evolve.fitness import _detectors_from_config, scanner_fitness

_CONFIG_PATH = Path(__file__).parent / "scanner_skill_config.yaml"


def _by_type(detectors):
    return {type(d): d for d in detectors}


def test_baseline_builds_four_detectors_with_baseline_params():
    cfg = load_config(_CONFIG_PATH)
    detectors = _detectors_from_config(cfg)

    assert len(detectors) == 4
    by_type = _by_type(detectors)
    assert set(by_type) == {
        HighBreakoutDetector,
        MaCrossDetector,
        GapDetector,
        RsiDivergenceDetector,
    }

    assert by_type[HighBreakoutDetector]._window == 252
    ma = by_type[MaCrossDetector]
    assert ma._fast == 50
    assert ma._slow == 200
    assert by_type[GapDetector]._threshold == 3.0
    assert by_type[RsiDivergenceDetector]._div_window == 40


def test_delta_rebuilds_detectors_with_new_params():
    cfg = load_config(_CONFIG_PATH)
    cfg = apply_delta(cfg, {"detectors.ma_cross.fast": 20, "detectors.ma_cross.slow": 150})
    detectors = _detectors_from_config(cfg)

    ma = _by_type(detectors)[MaCrossDetector]
    assert ma._fast == 20
    assert ma._slow == 150
    assert ma._min_bars == 152  # slow + 2
    # Derived lookback must cover the required bars (slow*2 + 100 = 400).
    assert ma._lookback >= ma._min_bars


def test_derived_lookback_covers_required_bars_at_range_top():
    """At the top of the adjustable ranges, derived lookback ≥ required bars."""
    cfg = load_config(_CONFIG_PATH)
    cfg = apply_delta(
        cfg,
        {
            "detectors.high_breakout.window": 300,
            "detectors.ma_cross.slow": 300,
        },
    )
    detectors = _detectors_from_config(cfg)
    by_type = _by_type(detectors)

    hb = by_type[HighBreakoutDetector]
    # high_breakout needs window + 2 trading bars.
    assert hb._lookback >= hb._window + 2

    ma = by_type[MaCrossDetector]
    assert ma._lookback >= ma._min_bars


def test_unknown_detector_name_raises():
    cfg = load_config(_CONFIG_PATH)
    cfg.detectors["bogus_detector"] = {"foo": 1}
    with pytest.raises(ValueError):
        _detectors_from_config(cfg)


# ===========================================================================
# Task 3: scanner_fitness — A/B-vs-random over a regime, no-lookahead
# ===========================================================================

_START = "2024-01-01"


def _price(time_iso: str, close: float) -> Price:
    return Price(open=close, close=close, high=close, low=close, volume=1_000_000, time=time_iso)


def _bundle(ticker: str, closes: list[float], start: str = _START) -> TickerBundle:
    """Build a TickerBundle from a daily close series (1 calendar day per bar)."""
    d = date.fromisoformat(start)
    prices = [_price((d + timedelta(days=i)).isoformat(), c) for i, c in enumerate(closes)]
    return TickerBundle(ticker=ticker, prices=prices)


def _iso(start: str, i: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=i)).isoformat()


def _high_breakout_closes(break_idx: int, *, warmup: float = 100.0, dip: float = 95.0, jump: float = 130.0):
    """Closes that make HighBreakoutDetector(window=60) fire ON the bar at ``break_idx``.

    Flat warmup (the trailing 60-bar max), a 3-bar dip just before the break so
    yesterday sits BELOW the prior max (first-day gate), then a jump on the break
    bar, then a continued rise so a 5d forward return exists.
    """
    closes = [warmup] * (break_idx - 3)
    closes += [dip, dip, dip]  # the 3 bars immediately before the break
    closes.append(jump)  # the break bar at index == break_idx
    # Post-break tail so a 5d forward return is computable from break_idx.
    closes += [jump + 1.0 * k for k in range(1, 11)]
    return closes


def test_contract_keys_and_types():
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = {
        "AAA": _bundle("AAA", _high_breakout_closes(break_idx)),
        "BBB": _bundle("BBB", [100.0] * 100),  # never fires
    }
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)

    assert set(out) == {"fitness", "diff", "t_stat", "n_fired", "alpha_5d"}
    assert isinstance(out["fitness"], float)
    assert isinstance(out["diff"], float)
    assert isinstance(out["t_stat"], float)
    assert isinstance(out["n_fired"], int)
    assert out["alpha_5d"] is None  # no spy_bundle


def test_fires_when_config_tuned():
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = {
        "AAA": _bundle("AAA", _high_breakout_closes(break_idx)),
        "BBB": _bundle("BBB", [100.0] * 100),
    }
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out["n_fired"] > 0


def test_nothing_fires_is_graceful():
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    # Flat universe → no detector can fire; window covers the dates either way.
    bundles = {
        "AAA": _bundle("AAA", [100.0] * 120),
        "BBB": _bundle("BBB", [100.0] * 120),
    }
    window = [(_iso(_START, 80), _iso(_START, 100))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out["n_fired"] == 0
    assert out["fitness"] == 0.0
    assert out["diff"] == 0.0
    assert out["t_stat"] == 0.0
    assert out["alpha_5d"] is None


def test_window_outside_data_is_graceful():
    """A window past the end of the data yields no as-of dates → nothing fires."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    bundles = {"AAA": _bundle("AAA", _high_breakout_closes(80))}
    window = [("2030-01-01", "2030-12-31")]  # no overlap with the synthetic dates
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out["n_fired"] == 0
    assert out["fitness"] == 0.0


def test_threshold_sensitivity_changes_fired_set():
    """Two windows differing by gap.threshold-equivalent — here, a window that
    includes the break vs one that excludes it → different n_fired."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = {"AAA": _bundle("AAA", _high_breakout_closes(break_idx))}

    win_hit = [(_iso(_START, break_idx), _iso(_START, break_idx))]
    win_miss = [(_iso(_START, break_idx - 5), _iso(_START, break_idx - 5))]

    out_hit = scanner_fitness(bundles, cfg, "val", window_of=lambda s: win_hit, rebalance_step=1)
    out_miss = scanner_fitness(bundles, cfg, "val", window_of=lambda s: win_miss, rebalance_step=1)

    assert out_hit["n_fired"] != out_miss["n_fired"]


def test_never_raises_on_junk_bundle():
    """A too-short / empty bundle mixed in must not raise — just contributes nothing."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = {
        "AAA": _bundle("AAA", _high_breakout_closes(break_idx)),
        "EMPTY": TickerBundle(ticker="EMPTY", prices=[]),
        "SHORT": _bundle("SHORT", [100.0, 101.0, 102.0]),
    }
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert isinstance(out["n_fired"], int)  # no exception raised


def test_determinism():
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = {
        "AAA": _bundle("AAA", _high_breakout_closes(break_idx)),
        "BBB": _bundle("BBB", [100.0] * 100),
        "CCC": _bundle("CCC", [100.0 + 0.1 * i for i in range(100)]),
    }
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]
    out1 = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    out2 = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    assert out1 == out2


def test_no_lookahead_future_spike_does_not_fire():
    """A breakout spike placed AFTER the as-of date must not make the detector
    fire on the as-of date — proof the CachedAsOfClient clamps to <= asof."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    closes = _high_breakout_closes(break_idx)  # spike at index 80
    bundles = {"AAA": _bundle("AAA", closes)}
    # As-of BEFORE the spike: detector can only see flat/dip bars <= asof-1.
    asof = _iso(_START, break_idx - 1)
    window = [(asof, asof)]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, rebalance_step=1)
    assert out["n_fired"] == 0


def test_no_lookahead_clamp_lets_break_bar_through_but_not_future_spike():
    """PAIRED no-lookahead discriminator: clamp-to-<=asof, NOT errored-out.

    The sibling ``test_no_lookahead_future_spike_does_not_fire`` only asserts
    ``n_fired == 0`` on the future-spike case. That assertion ALSO holds if
    ``_UniverseAsOfClient.set_asof`` is removed: the resulting ``RuntimeError``
    inside the detector is swallowed by ``run_scan``'s per-detector isolation,
    so the detector silently fires nothing and ``n_fired == 0`` either way.
    A green ``== 0`` therefore can't distinguish "correctly clamped" from
    "errored out" — false assurance on the load-bearing invariant.

    This test adds the discriminating half: an ON-break as-of date that MUST
    yield ``n_fired > 0``. The ``> 0`` is the discriminator — if ``set_asof``
    were a no-op (or raised), the break bar would never be visible / the
    detector would error, and this case would ALSO yield ``n_fired == 0`` and
    FAIL. Both halves use the same breakout series; only the as-of date moves.
    """
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = {"AAA": _bundle("AAA", _high_breakout_closes(break_idx))}

    # ON the break bar: the clamp must let the break bar through → fires.
    asof_on = _iso(_START, break_idx)
    out_on = scanner_fitness(bundles, cfg, "val", window_of=lambda s: [(asof_on, asof_on)], rebalance_step=1)
    assert out_on["n_fired"] > 0  # discriminator: fails if set_asof is a no-op

    # ONE bar BEFORE the break: the spike is in the future → excluded.
    asof_before = _iso(_START, break_idx - 1)
    out_before = scanner_fitness(bundles, cfg, "val", window_of=lambda s: [(asof_before, asof_before)], rebalance_step=1)
    assert out_before["n_fired"] == 0


def test_alpha_computed_with_spy_bundle():
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = {"AAA": _bundle("AAA", _high_breakout_closes(break_idx))}
    spy = _bundle("SPY", [100.0] * 200)  # flat SPY → spy 5d return == 0
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]
    out = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, spy_bundle=spy)
    assert out["n_fired"] > 0
    assert out["alpha_5d"] is not None
    assert isinstance(out["alpha_5d"], float)


# ===========================================================================
# Task 4: parse bundles ONCE, reuse the parsed series across iterations.
# ===========================================================================


def _multi_bundles(break_idx: int = 80) -> dict:
    """A small universe that fires (AAA) plus several never-fire fillers.

    The fillers widen the random baseline so multiple distinct tickers get
    parsed via the forward-return path — giving the parse-counter something to
    count across.
    """
    bundles = {"AAA": _bundle("AAA", _high_breakout_closes(break_idx))}
    for name in ("BBB", "CCC", "DDD", "EEE"):
        bundles[name] = _bundle(name, [100.0 + 0.1 * i for i in range(120)])
    return bundles


class _ParseCounter:
    """Wrap ``fitness._parse_bundle_series`` and tally calls by (id) bundle.

    Counting by ``id(bundle)`` is a faithful proxy for "by ticker" here: each
    ticker has exactly one immutable bundle object for the run.
    """

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
    """A SHARED cache → each ticker's series is parsed at most once TOTAL across
    two calls, not once-per-call-per-ticker."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = _multi_bundles(break_idx)
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]

    counter = _ParseCounter(monkeypatch)
    shared: dict = {}

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, cache=shared)
    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, cache=shared)

    # At most one parse per bundle object total — the second call is a pure hit.
    assert counter.total <= len(bundles)
    # And every parse was for a DISTINCT bundle (no re-parse of an already-seen one).
    assert counter.total == counter.distinct


def test_threshold_only_delta_reuses_cache(monkeypatch):
    """A threshold-only config change between two cache-sharing calls adds no new
    parse for already-seen tickers."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = _multi_bundles(break_idx)
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]

    counter = _ParseCounter(monkeypatch)
    shared: dict = {}

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, cache=shared)
    parsed_after_first = counter.total

    cfg2 = apply_delta(cfg, {"detectors.gap.threshold": 4.0})
    scanner_fitness(bundles, cfg2, "val", window_of=lambda s: window, cache=shared)

    # No additional parse: every ticker was already in the shared cache.
    assert counter.total == parsed_after_first


def test_no_shared_cache_reparses(monkeypatch):
    """Two calls WITHOUT a shared cache (each gets its own throwaway) → the
    second call re-parses, proving the memoization is what saves the work."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = _multi_bundles(break_idx)
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]

    counter = _ParseCounter(monkeypatch)

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    after_first = counter.total
    assert after_first > 0

    scanner_fitness(bundles, cfg, "val", window_of=lambda s: window)
    # The second throwaway-cache call parses again — total strictly grows.
    assert counter.total > after_first


def test_cache_is_pure_identical_results():
    """Results with a shared cache are IDENTICAL to results without one (cache is
    a perf optimization, never changes the returned dict)."""
    cfg = apply_delta(load_config(_CONFIG_PATH), {"detectors.high_breakout.window": 60})
    break_idx = 80
    bundles = _multi_bundles(break_idx)
    spy = _bundle("SPY", [100.0] * 200)
    window = [(_iso(_START, break_idx), _iso(_START, break_idx))]

    shared: dict = {}
    out_cached = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, spy_bundle=spy, cache=shared)
    out_uncached = scanner_fitness(bundles, cfg, "val", window_of=lambda s: window, spy_bundle=spy, cache=None)
    assert out_cached == out_uncached
