"""Tests for the scanner-evolve fitness bridge.

Task 2 scope: ``_detectors_from_config`` only — construct live detector
instances from a :class:`ScannerEvolveConfig`. Offline; no scan run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from v2.scanner.detectors import (
    GapDetector,
    HighBreakoutDetector,
    MaCrossDetector,
    RsiDivergenceDetector,
)
from v2.scanner.evolve.config import apply_delta, load_config
from v2.scanner.evolve.fitness import _detectors_from_config

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
