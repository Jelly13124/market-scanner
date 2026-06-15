"""Offline tests for graduating the best evolved config into a paper sleeve (Task 9).

Everything here is OFFLINE: no network, no LLM, no DB. The version store is plain
JSON on a tmp dir (written via the real :mod:`v2.self_evolve.versioning` helpers),
the bundles are synthetic ``SimpleNamespace`` fakes, and the ``factor_fn`` seam
wraps the REAL :func:`v2.self_evolve.strategy_gen.generate_holdings` over those
bundles + a fixed :class:`StrategyConfig` fixture.

Pins the graduation contract the live paper sleeve depends on:

* :func:`load_best_config` returns the LAST ``kept`` version's config, and falls
  back to the ``skill_config.yaml`` baseline on an empty store;
* ``compute_targets("factor_evolved", ...)`` with an injected ``factor_fn``
  returns exactly the holdings' ticker list (long-only, deduped);
* the never-raises guarantee holds (a raising ``factor_fn`` / ``factor_fn=None``
  both collapse to ``[]``);
* ``"factor_evolved"`` is a registered sleeve.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from src.paper_trading.sleeves import SLEEVE_NAMES, compute_targets
from v2.self_evolve.config import FACTOR_KEYS, StrategyConfig, load_config
from v2.self_evolve.graduate import load_best_config
from v2.self_evolve.strategy_gen import generate_holdings
from v2.self_evolve.versioning import append_path_log, write_version

BASELINE = Path(__file__).resolve().parents[2] / "strategy_skill" / "skill_config.yaml"


# ---------------------------------------------------------------------------
# Fixtures: a real StrategyConfig + synthetic bundles (mirrors test_strategy_gen)
# ---------------------------------------------------------------------------


def _config(**overrides) -> StrategyConfig:
    """A real, validatable :class:`StrategyConfig` (weights normalized on build)."""
    base = dict(
        factor_weights={"momentum": 0.30, "low_vol": 0.25, "reversal": 0.15, "value": 0.15, "quality": 0.15},
        lookback={"momentum_days": 180, "vol_days": 30, "reversal_days": 10},
        top_n=30,
        holding_buffer=5,
        max_weight=0.05,
        liquidity_pct={"mktcap_pct": 0.20, "advol_pct": 0.20},
        tilt_strength=0.5,
    )
    base.update(overrides)
    return StrategyConfig(**base)


def _price(d: str, close: float, volume: float) -> SimpleNamespace:
    return SimpleNamespace(time=d, close=close, volume=volume)


def _series(asof: date, n: int, *, start_price: float, step: float, jitter: float = 0.3, volume: float = 1_000_000.0):
    """``n`` daily bars ENDING on ``asof`` (nonzero jitter → defined realized vol)."""
    start = asof - timedelta(days=n - 1)
    return [_price((start + timedelta(days=i)).isoformat(), start_price + i * step + (i % 5) * jitter, volume) for i in range(n)]


ASOF = "2020-12-31"
_ASOF_D = date(2020, 12, 31)


def _synthetic_bundles() -> dict:
    """Six liquid names with cleanly separated momentum (steepest ramps win)."""
    steps = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.4, "E": 0.2, "F": 0.05}
    return {t: SimpleNamespace(prices=_series(_ASOF_D, 400, start_price=100.0, step=s), metrics_history=[]) for t, s in steps.items()}


# ---------------------------------------------------------------------------
# 1. load_best_config — last kept version wins; empty store → baseline
# ---------------------------------------------------------------------------


def test_load_best_config_returns_last_kept_version(tmp_path) -> None:
    # Two kept + one rolled-back round. The LAST kept (v0.0.2) must win, even
    # though a later (rolled-back) round exists after it.
    kept_first = _config(top_n=25)
    kept_last = _config(top_n=42)  # the one we expect back
    rolled_back = _config(top_n=50)

    write_version(tmp_path, "v0", {"config": asdict(_config(top_n=30)), "kept": True})
    write_version(tmp_path, "v0.0.1", {"config": asdict(kept_first), "kept": True})
    write_version(tmp_path, "v0.0.2", {"config": asdict(kept_last), "kept": True})
    write_version(tmp_path, "v0.0.3", {"config": asdict(rolled_back), "kept": False})

    for v_id, cfg, kept in [
        ("v0", _config(top_n=30), True),
        ("v0.0.1", kept_first, True),
        ("v0.0.2", kept_last, True),
        ("v0.0.3", rolled_back, False),
    ]:
        append_path_log(tmp_path, {"v_id": v_id, "hypothesis": "h", "val_sharpe": 1.0, "kept": kept})

    best = load_best_config(tmp_path)
    assert isinstance(best, StrategyConfig)
    # The LAST kept entry's config (v0.0.2), not the later rolled-back v0.0.3.
    assert best.top_n == 42
    assert best.factor_weights == kept_last.factor_weights


def test_load_best_config_skips_trailing_rolled_back(tmp_path) -> None:
    # A store whose final entries are all rolled back must walk BACK to the last
    # kept one rather than returning a rolled-back config or the baseline.
    write_version(tmp_path, "v0.0.1", {"config": asdict(_config(top_n=33)), "kept": True})
    write_version(tmp_path, "v0.0.2", {"config": asdict(_config(top_n=48)), "kept": False})
    append_path_log(tmp_path, {"v_id": "v0.0.1", "kept": True})
    append_path_log(tmp_path, {"v_id": "v0.0.2", "kept": False})

    assert load_best_config(tmp_path).top_n == 33


def test_load_best_config_empty_store_falls_back_to_baseline(tmp_path) -> None:
    # No path log / versions under tmp_path, but a minimal valid skill_config.yaml
    # sits there → load_best_config must return that baseline, not raise.
    (tmp_path / "skill_config.yaml").write_text(BASELINE.read_text(encoding="utf-8"), encoding="utf-8")
    best = load_best_config(tmp_path)
    baseline = load_config(tmp_path / "skill_config.yaml")
    assert isinstance(best, StrategyConfig)
    assert best.top_n == baseline.top_n
    assert best.factor_weights == baseline.factor_weights


def test_load_best_config_real_strategy_skill_dir_loads() -> None:
    # Pointed at the REAL strategy_skill dir (default), it must return a valid
    # config whether or not the loop has run (kept version or baseline fallback).
    cfg = load_best_config()
    assert isinstance(cfg, StrategyConfig)
    # Assert against the canonical key set (not a frozen list) so adding a factor
    # to FACTOR_KEYS doesn't make this real-dir test go stale.
    assert set(cfg.factor_weights) == set(FACTOR_KEYS)


# ---------------------------------------------------------------------------
# 2. compute_targets("factor_evolved", ...) with an injected REAL factor_fn
# ---------------------------------------------------------------------------


def test_factor_evolved_returns_generate_holdings_tickers() -> None:
    bundles = _synthetic_bundles()
    # Pure-momentum, keep the 3 steepest ramps, drop nobody on liquidity.
    cfg = _config(
        factor_weights={"momentum": 1.0, "low_vol": 0.0, "reversal": 0.0, "value": 0.0, "quality": 0.0},
        top_n=3,
        max_weight=0.60,
        liquidity_pct={"mktcap_pct": 0.0, "advol_pct": 0.0},
    )
    expected = list(generate_holdings(bundles, ASOF, cfg).keys())
    assert expected  # sanity: the fixture actually produces a non-empty book

    def factor_fn(scan_date: str) -> list[str]:
        return list(generate_holdings(bundles, scan_date, cfg).keys())

    targets = compute_targets("factor_evolved", ASOF, run_scan_fn=lambda *_: [], factor_fn=factor_fn)
    assert targets == expected
    # Long-only, deduped ticker strings.
    assert all(isinstance(t, str) for t in targets)
    assert len(targets) == len(set(targets))


def test_factor_evolved_dedupes_and_filters_non_strings() -> None:
    # A misbehaving factor_fn that emits dups + a non-string must be cleaned to a
    # deduped, string-only, order-preserving list.
    def factor_fn(scan_date: str):
        return ["AAA", "BBB", "AAA", 123, "CCC"]

    targets = compute_targets("factor_evolved", ASOF, run_scan_fn=lambda *_: [], factor_fn=factor_fn)
    assert targets == ["AAA", "BBB", "CCC"]


# ---------------------------------------------------------------------------
# 3. never-raises: raising factor_fn / factor_fn=None → []
# ---------------------------------------------------------------------------


def test_factor_evolved_factor_fn_raising_returns_empty() -> None:
    def boom(scan_date: str):
        raise RuntimeError("factor path exploded")

    assert compute_targets("factor_evolved", ASOF, run_scan_fn=lambda *_: [], factor_fn=boom) == []


def test_factor_evolved_none_factor_fn_returns_empty() -> None:
    assert compute_targets("factor_evolved", ASOF, run_scan_fn=lambda *_: [], factor_fn=None) == []


def test_factor_evolved_factor_fn_returning_none_returns_empty() -> None:
    assert compute_targets("factor_evolved", ASOF, run_scan_fn=lambda *_: [], factor_fn=lambda _d: None) == []


# ---------------------------------------------------------------------------
# 4. factor_evolved is a registered sleeve
# ---------------------------------------------------------------------------


def test_factor_evolved_in_sleeve_names() -> None:
    assert "factor_evolved" in SLEEVE_NAMES
