"""Graduate the EVOLVED scanner config into a live paper-trading sleeve.

The scanner self-evolve loop tuned the ``intraday_move`` detector's thresholds.
Its retained-best config is committed as ``graduated_config.yaml`` (the run store
``scanner_evolve_run/`` is an untracked local artifact, so the committed yaml is
the deploy-safe source of truth). This module turns that config into a runnable
scanner seam for the ``scanner_evolved`` paper sleeve:

* :func:`load_graduated_config` resolves the graduated config, degrading to the
  baseline ``scanner_skill_config.yaml`` (with a logged warning) if the
  graduated file is missing. It never raises on a missing graduated file.

* :func:`build_scanner_evolved_detectors` builds the FULL production detector
  basket (every class in ``ALL_DETECTORS``) but with ``IntradayMoveDetector``
  swapped for the TUNED one from the graduated config. So the sleeve differs
  from ``scanner_only`` ONLY in intraday_move's thresholds — a clean A/B on the
  evolved thresholds against the real scanner.

* :func:`build_scanner_evolved_fn` wraps that basket into a
  ``run_scan_evolved_fn(scan_date, top_n) -> list[str]`` seam, shaped exactly
  like the ``run_scan_fn`` the paper-trading harness already injects.

Mirrors :mod:`v2.self_evolve.graduate`: best-effort config load (degrade to
baseline, never raise on a missing graduated file), and lazy heavy imports
inside the seam so importing this module offline pulls in nothing network-bound.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from v2.scanner.detectors import ALL_DETECTORS, EventDetector
from v2.scanner.evolve.config import ScannerEvolveConfig, load_config
from v2.scanner.evolve.fitness import _detectors_from_config

logger = logging.getLogger(__name__)

#: The committed graduated (promoted) scanner-evolve config.
DEFAULT_GRADUATED_CONFIG = Path(__file__).resolve().parent / "graduated_config.yaml"

#: The baseline config — the fallback when the graduated file is missing.
BASELINE_CONFIG = Path(__file__).resolve().parent / "scanner_skill_config.yaml"


def load_graduated_config(path=DEFAULT_GRADUATED_CONFIG) -> ScannerEvolveConfig:
    """Return the graduated :class:`ScannerEvolveConfig`, else the baseline.

    Loads ``path`` (the committed graduated config) via ``load_config``. If the
    graduated file does not exist, logs a warning and falls back to the baseline
    ``scanner_skill_config.yaml`` — never raises on a missing graduated file
    (degrade to baseline). A missing/broken BASELINE re-raises (a real
    misconfiguration worth surfacing).
    """
    p = Path(path)
    if not p.exists():
        logger.warning(
            "load_graduated_config: %s missing; falling back to baseline %s",
            p,
            BASELINE_CONFIG,
        )
        return load_config(BASELINE_CONFIG)
    return load_config(p)


def build_scanner_evolved_detectors(config: ScannerEvolveConfig | None = None) -> list[EventDetector]:
    """Build the full production basket with intraday_move swapped for the tuned one.

    Loads the graduated config (if not passed), builds the TUNED
    ``IntradayMoveDetector`` from it (via ``_detectors_from_config``), and
    appends every OTHER registered detector at its production default. The result
    is the full ``ALL_DETECTORS`` basket with exactly one ``intraday_move`` — the
    tuned variant — so it differs from ``scanner_only`` only in intraday's
    thresholds.
    """
    if config is None:
        config = load_graduated_config()
    tuned = _detectors_from_config(config)  # the tuned intraday_move (one detector)
    others = [c() for c in ALL_DETECTORS if c().name != "intraday_move"]
    return tuned + others


def build_scanner_evolved_fn(
    provider_factory,
    universe_tickers,
    *,
    config: ScannerEvolveConfig | None = None,
) -> Callable[[str, int], list[str]]:
    """Build the live ``run_scan_evolved_fn(scan_date, top_n) -> list[str]`` seam.

    The returned callable runs the FULL production scanner over
    ``universe_tickers`` as-of ``scan_date`` but with the tuned intraday_move
    detector swapped in, returning the Top-N ranked ticker strings. Same
    shape/signature as the harness's ``run_scan_fn``. The detector basket is
    built once (the graduated config is read once at build time).

    The scanner runner import is deferred inside the seam so importing this
    module offline drags in no network/data stack.

    Args:
        provider_factory: Zero-arg factory returning a fresh data client
            (mirrors the other live seams; passed through to ``run_scan``).
        universe_tickers: The ticker universe to scan each week.
        config: Optional pre-loaded config; loaded from the graduated yaml if None.
    """
    detectors = build_scanner_evolved_detectors(config)

    def run_scan_evolved_fn(scan_date: str, top_n: int) -> list[str]:
        from v2.scanner.runner import run_scan

        entries = run_scan(
            tickers=universe_tickers,
            end_date=scan_date,
            top_n=top_n,
            detectors=detectors,
            provider_factory=provider_factory,
        )
        return [e.ticker for e in entries]

    return run_scan_evolved_fn
