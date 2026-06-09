"""Offline tests for the bounded config loader/validator (Task 1).

These exercise the PROTOCOL boundary: the LLM may only edit paths declared in
``ADJUSTABLE``, only within the declared range. Everything here is pure Python —
no network, no LLM, no data files beyond the checked-in baseline yaml.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from v2.self_evolve.config import (
    ADJUSTABLE,
    ConfigError,
    StrategyConfig,
    apply_delta,
    load_config,
    validate,
)

BASELINE = Path(__file__).resolve().parents[2] / "strategy_skill" / "skill_config.yaml"


# ---------------------------------------------------------------------------
# 1. load_config on the baseline yaml → sum-normalized weights
# ---------------------------------------------------------------------------


def test_load_baseline_returns_strategy_config():
    cfg = load_config(BASELINE)
    assert isinstance(cfg, StrategyConfig)


def test_load_baseline_weights_sum_normalized():
    cfg = load_config(BASELINE)
    assert sum(cfg.factor_weights.values()) == pytest.approx(1.0)
    # The five canonical factors are all present.
    assert set(cfg.factor_weights) == {
        "momentum",
        "low_vol",
        "reversal",
        "value",
        "quality",
    }


def test_load_baseline_scalar_fields_in_range():
    cfg = load_config(BASELINE)
    assert 20 <= cfg.top_n <= 50
    assert 0.03 <= cfg.max_weight <= 0.08
    assert cfg.rebalance == "monthly"
    assert cfg.cost_bps >= 0


# ---------------------------------------------------------------------------
# 2. validate rejects out-of-range
# ---------------------------------------------------------------------------


def test_validate_rejects_top_n_below_min():
    cfg = load_config(BASELINE)
    cfg.top_n = 10  # below the [20, 50] floor
    with pytest.raises(ConfigError):
        validate(cfg)


def test_validate_rejects_max_weight_above_max():
    cfg = load_config(BASELINE)
    cfg.max_weight = 0.2  # above the [0.03, 0.08] ceiling
    with pytest.raises(ConfigError):
        validate(cfg)


def test_validate_rejects_negative_factor_weight():
    cfg = load_config(BASELINE)
    # A negative weight is outside [0, 1]. Bypass normalization by setting the
    # dict directly so validate() is what catches it.
    cfg.factor_weights = {
        "momentum": -0.1,
        "low_vol": 0.3,
        "reversal": 0.2,
        "value": 0.3,
        "quality": 0.3,
    }
    with pytest.raises(ConfigError):
        validate(cfg)


# ---------------------------------------------------------------------------
# 3. apply_delta
# ---------------------------------------------------------------------------


def test_apply_delta_returns_new_renormalized_config():
    cfg = load_config(BASELINE)
    original_momentum = cfg.factor_weights["momentum"]
    new_cfg = apply_delta(cfg, {"factor_weights.momentum": 0.40})

    # New object, original untouched.
    assert new_cfg is not cfg
    assert cfg.factor_weights["momentum"] == original_momentum

    # Result is re-normalized to 1.0.
    assert sum(new_cfg.factor_weights.values()) == pytest.approx(1.0)
    # Momentum moved up relative to the others.
    assert new_cfg.factor_weights["momentum"] > new_cfg.factor_weights["low_vol"]


def test_apply_delta_scalar_path():
    cfg = load_config(BASELINE)
    new_cfg = apply_delta(cfg, {"top_n": 40})
    assert new_cfg.top_n == 40
    assert cfg.top_n != 40 or cfg is not new_cfg  # original unchanged identity


def test_apply_delta_out_of_range_raises():
    cfg = load_config(BASELINE)
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"top_n": 5})  # below [20, 50]


def test_apply_delta_unknown_path_raises():
    cfg = load_config(BASELINE)
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"foo.bar": 1})


def test_apply_delta_non_adjustable_path_raises():
    cfg = load_config(BASELINE)
    # rebalance is fixed kernel, not in ADJUSTABLE → editing it is forbidden.
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"rebalance": "weekly"})


# ---------------------------------------------------------------------------
# Protocol / dataclass sanity
# ---------------------------------------------------------------------------


def test_strategy_config_is_dataclass():
    assert dataclasses.is_dataclass(StrategyConfig)


def test_adjustable_declares_known_paths():
    # Every ADJUSTABLE key is a dotted path or a top-level scalar field name.
    assert "factor_weights.momentum" in ADJUSTABLE
    assert "top_n" in ADJUSTABLE
    assert "max_weight" in ADJUSTABLE
    # Each entry is a (min, max) numeric tuple.
    lo, hi = ADJUSTABLE["top_n"]
    assert lo == 20 and hi == 50


# ---------------------------------------------------------------------------
# Inert-knob exclusion (final review H1): tilt_strength / holding_buffer are
# NOT read by the strategy, so they must not be tunable levers (a proposer
# round spent on them can't move the metric). cost_bps, now a real lever after
# the transaction-cost fix, stays adjustable.
# ---------------------------------------------------------------------------


def test_inert_knobs_excluded_from_adjustable():
    assert "tilt_strength" not in ADJUSTABLE
    assert "holding_buffer" not in ADJUSTABLE


def test_cost_bps_is_adjustable():
    # cost_bps is a live lever now that the backtest charges it.
    assert "cost_bps" in ADJUSTABLE
    lo, hi = ADJUSTABLE["cost_bps"]
    assert lo <= 10.0 <= hi  # the baseline default sits inside the range


def test_apply_delta_rejects_removed_inert_knob():
    cfg = load_config(BASELINE)
    # A proposer targeting a now-inert path is rejected (caller maps this to None
    # → no wasted iteration), exactly like any other non-adjustable path.
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"tilt_strength": 0.7})
    with pytest.raises(ConfigError):
        apply_delta(cfg, {"holding_buffer": 10})


def test_validate_still_passes_after_removing_inert_knobs():
    # Removing keys from ADJUSTABLE must not break validation of the still-present
    # fields: the baseline (which still carries tilt_strength/holding_buffer as
    # dataclass fields) validates cleanly.
    cfg = load_config(BASELINE)
    validate(cfg)  # must not raise
    assert cfg.tilt_strength == pytest.approx(0.50)
    assert cfg.holding_buffer == 5
