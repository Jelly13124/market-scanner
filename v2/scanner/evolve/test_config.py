"""Tests for the bounded scanner-evolve config protocol.

Pure Python — no network, no LLM. Mirrors ``v2/self_evolve/test_config.py`` in
spirit: load the baseline, assert the allow-list, and exercise the
``apply_delta`` / ``validate`` guard-rails (including invariant #2: the proposer
can never re-enable the fixed kernel ``quant_weight=0`` / ``event_weight=1``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from v2.scanner.evolve.config import (
    SCANNER_ADJUSTABLE,
    ConfigError,
    ScannerEvolveConfig,
    apply_delta,
    load_config,
    validate,
)

_YAML = Path(__file__).with_name("scanner_skill_config.yaml")


# ---------------------------------------------------------------------------
# load_config / baseline
# ---------------------------------------------------------------------------
def test_load_config_reads_baseline_and_validates():
    cfg = load_config(_YAML)
    assert isinstance(cfg, ScannerEvolveConfig)
    # Baseline detector params (locked to the real detector constructors).
    assert cfg.detectors["high_breakout"]["window"] == 252
    assert cfg.detectors["ma_cross"]["fast"] == 50
    assert cfg.detectors["ma_cross"]["slow"] == 200
    assert cfg.detectors["gap"]["threshold"] == 3.0
    assert cfg.detectors["rsi_divergence"]["div_window"] == 40
    assert cfg.severity_mult == {
        "high_breakout": 1.0,
        "ma_cross": 1.0,
        "gap": 1.0,
        "rsi_divergence": 1.0,
    }
    assert cfg.top_n == 20
    # Fixed kernel.
    assert cfg.event_weight == 1.0
    assert cfg.quant_weight == 0.0
    # Baseline must validate clean.
    validate(cfg)


# ---------------------------------------------------------------------------
# SCANNER_ADJUSTABLE allow-list
# ---------------------------------------------------------------------------
def test_scanner_adjustable_exact_paths_and_bounds():
    assert SCANNER_ADJUSTABLE == {
        "detectors.high_breakout.window": (60, 300),
        "detectors.ma_cross.fast": (10, 100),
        "detectors.ma_cross.slow": (120, 300),
        "detectors.gap.threshold": (2.0, 5.0),
        "detectors.rsi_divergence.div_window": (20, 80),
        "severity_mult.high_breakout": (0.5, 2.0),
        "severity_mult.ma_cross": (0.5, 2.0),
        "severity_mult.gap": (0.5, 2.0),
        "severity_mult.rsi_divergence": (0.5, 2.0),
        "top_n": (10, 50),
    }


def test_every_baseline_default_lies_inside_its_range():
    cfg = load_config(_YAML)
    for path, (lo, hi) in SCANNER_ADJUSTABLE.items():
        value = _read(cfg, path)
        assert lo <= value <= hi, f"{path}={value} not in [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# apply_delta
# ---------------------------------------------------------------------------
def test_apply_delta_in_range_returns_new_config_input_unchanged():
    cfg = load_config(_YAML)
    new = apply_delta(cfg, {"detectors.gap.threshold": 4.0})
    assert new.detectors["gap"]["threshold"] == 4.0
    # Input untouched.
    assert cfg.detectors["gap"]["threshold"] == 3.0
    assert new is not cfg


def test_apply_delta_three_level_path_ma_cross_fast_slow():
    cfg = load_config(_YAML)
    new = apply_delta(cfg, {"detectors.ma_cross.fast": 30, "detectors.ma_cross.slow": 150})
    assert new.detectors["ma_cross"]["fast"] == 30
    assert new.detectors["ma_cross"]["slow"] == 150
    # Input untouched.
    assert cfg.detectors["ma_cross"]["fast"] == 50
    assert cfg.detectors["ma_cross"]["slow"] == 200


def test_apply_delta_rejects_out_of_range():
    cfg = load_config(_YAML)
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"top_n": 99})


def test_apply_delta_rejects_quant_weight():
    cfg = load_config(_YAML)
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"quant_weight": 0.5})


def test_apply_delta_rejects_event_weight():
    cfg = load_config(_YAML)
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"event_weight": 0.5})


def test_apply_delta_rejects_unknown_path():
    cfg = load_config(_YAML)
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"detectors.gap.nonsense": 1.0})


# ---------------------------------------------------------------------------
# validate cross-field
# ---------------------------------------------------------------------------
def test_validate_rejects_fast_ge_slow():
    cfg = load_config(_YAML)
    # fast's range [10,100] and slow's range [120,300] are disjoint, so the
    # cross-field rule can only be exercised by mutating fields directly past
    # their bounds. validate must reject fast >= slow.
    cfg.detectors["ma_cross"]["fast"] = 200
    cfg.detectors["ma_cross"]["slow"] = 150
    with pytest.raises(ConfigError):
        validate(cfg)


def test_validate_rejects_quant_weight_deviation():
    cfg = load_config(_YAML)
    cfg.quant_weight = 0.5
    with pytest.raises(ConfigError):
        validate(cfg)


def test_validate_rejects_event_weight_deviation():
    cfg = load_config(_YAML)
    cfg.event_weight = 0.5
    with pytest.raises(ConfigError):
        validate(cfg)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _read(cfg: ScannerEvolveConfig, path: str):
    parts = path.split(".")
    if parts[0] == "detectors":
        return cfg.detectors[parts[1]][parts[2]]
    if parts[0] == "severity_mult":
        return cfg.severity_mult[parts[1]]
    return getattr(cfg, path)
