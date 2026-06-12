"""Tests for the bounded scanner-evolve config protocol.

Pure Python — no network, no LLM. Mirrors ``v2/self_evolve/test_config.py`` in
spirit: load the baseline, assert the allow-list, and exercise the
``apply_delta`` / ``validate`` guard-rails (including invariant #2: the proposer
can never re-enable the fixed kernel ``quant_weight=0`` / ``event_weight=1``).

The evolve set was re-scoped (2026-06-12) to ``intraday_move`` ONLY.
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
    # Baseline detector params (locked to the intraday_move constructor).
    iday = cfg.detectors["intraday_move"]
    assert iday["z_window"] == 60
    assert iday["close_vs_open_pct"] == 0.04
    assert iday["gap_pct"] == 0.03
    assert iday["range_pct"] == 0.06
    assert iday["z_threshold"] == 2.5
    assert cfg.severity_mult == {"intraday_move": 1.0}
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
        "detectors.intraday_move.z_window": (20, 120),
        "detectors.intraday_move.close_vs_open_pct": (0.02, 0.10),
        "detectors.intraday_move.gap_pct": (0.015, 0.08),
        "detectors.intraday_move.range_pct": (0.03, 0.12),
        "detectors.intraday_move.z_threshold": (1.5, 4.0),
        "severity_mult.intraday_move": (0.5, 2.0),
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
    new = apply_delta(cfg, {"detectors.intraday_move.z_threshold": 3.0})
    assert new.detectors["intraday_move"]["z_threshold"] == 3.0
    # Input untouched.
    assert cfg.detectors["intraday_move"]["z_threshold"] == 2.5
    assert new is not cfg


def test_apply_delta_three_level_path_multiple_params():
    cfg = load_config(_YAML)
    new = apply_delta(
        cfg,
        {"detectors.intraday_move.z_window": 90, "detectors.intraday_move.gap_pct": 0.05},
    )
    assert new.detectors["intraday_move"]["z_window"] == 90
    assert new.detectors["intraday_move"]["gap_pct"] == 0.05
    # Input untouched.
    assert cfg.detectors["intraday_move"]["z_window"] == 60
    assert cfg.detectors["intraday_move"]["gap_pct"] == 0.03


def test_apply_delta_enforces_integer_on_z_window():
    cfg = load_config(_YAML)
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"detectors.intraday_move.z_window": 60.5})


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
        apply_delta(cfg, {"detectors.intraday_move.nonsense": 1.0})


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
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


def test_validate_rejects_wrong_detector_keyset():
    cfg = load_config(_YAML)
    cfg.detectors["bogus"] = {"x": 1}
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
