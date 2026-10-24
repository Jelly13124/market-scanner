"""Offline tests for the scanner_evolved graduation seam.

These tests must run with no network and no LLM. They exercise
:mod:`v2.scanner.evolve.graduate` — the committed graduated config, the tuned
detector basket, and the missing-file fallback — without ever calling the live
scanner (the seam builds detectors eagerly but defers ``run_scan``).
"""

from __future__ import annotations

from v2.scanner.detectors import ALL_DETECTORS
from v2.scanner.evolve.config import ScannerEvolveConfig
from v2.scanner.evolve.graduate import (
    build_scanner_evolved_detectors,
    load_graduated_config,
)


# -- load_graduated_config ----------------------------------------------------


def test_load_graduated_config_loads_and_validates() -> None:
    """The committed graduated yaml loads cleanly and carries the tuned params."""
    cfg = load_graduated_config()
    assert isinstance(cfg, ScannerEvolveConfig)
    im = cfg.detectors["intraday_move"]
    assert im["z_window"] == 90
    assert im["close_vs_open_pct"] == 0.05
    assert im["gap_pct"] == 0.04
    assert im["z_threshold"] == 3.5
    assert cfg.top_n == 20


def test_load_graduated_config_missing_falls_back_to_baseline(tmp_path, caplog) -> None:
    """A missing graduated file degrades to the baseline config (never raises)."""
    missing = tmp_path / "does_not_exist.yaml"
    with caplog.at_level("WARNING"):
        cfg = load_graduated_config(missing)
    # Degraded to baseline: baseline intraday_move thresholds (z_window=60, z=2.5).
    im = cfg.detectors["intraday_move"]
    assert im["z_window"] == 60
    assert im["z_threshold"] == 2.5
    assert any("missing" in r.message.lower() for r in caplog.records)


# -- build_scanner_evolved_detectors ------------------------------------------


def test_build_detectors_is_full_basket_with_tuned_intraday() -> None:
    """Full ALL_DETECTORS basket, with exactly one TUNED intraday_move."""
    dets = build_scanner_evolved_detectors()

    # Same count as the production basket (one swapped, not added/removed).
    assert len(dets) == len(ALL_DETECTORS)

    # Exactly one intraday_move, and it carries the tuned attrs.
    intraday = [d for d in dets if d.name == "intraday_move"]
    assert len(intraday) == 1
    im = intraday[0]
    assert im._z_window == 90
    assert im._cvo_pct == 0.05
    assert im._gap_pct == 0.04
    assert im._z_thresh == 3.5

    # Every other registered detector name is present.
    expected_other_names = {c().name for c in ALL_DETECTORS if c().name != "intraday_move"}
    got_other_names = {d.name for d in dets if d.name != "intraday_move"}
    assert got_other_names == expected_other_names
