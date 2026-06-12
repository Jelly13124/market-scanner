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
