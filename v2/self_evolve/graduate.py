"""Graduate the best EVOLVED config into a live paper-trading sleeve (Task 9).

The self-evolve loop (:mod:`v2.self_evolve.loop`) leaves an on-disk version
store under ``strategy_skill/versions/`` whose ``path_log.jsonl`` records, in
append order, every candidate it tried and whether each was *kept* (strictly
beat the running-best on validation Sharpe within the guardrails). This module
turns that store into a runnable strategy:

* :func:`load_best_config` resolves the **top val-retained** config — the LAST
  ``kept`` entry in the path log — and rebuilds it as a
  :class:`~v2.self_evolve.config.StrategyConfig`. With no kept version (a fresh /
  empty store) it falls back to the ``skill_config.yaml`` baseline.

* :func:`build_factor_fn` wraps that config plus the deterministic portfolio
  kernel (:func:`v2.self_evolve.strategy_gen.generate_holdings`) into a
  ``factor_fn(scan_date) -> list[str]`` seam, shaped exactly like the
  ``run_scan_fn`` / ``agent_fn`` seams the paper-trading harness already injects.
  The harness equal-weights whatever ticker list it returns.

Two hard properties, mirroring the rest of the harness:

* **No look-ahead.** The live ``factor_fn`` builds bundles only over
  ``[scan_date - lookback_days, scan_date]`` and hands ``scan_date`` to
  ``generate_holdings`` as its as-of ceiling; that function additionally clamps
  every price bar to ``<= asof`` and lags fundamentals, so nothing dated after
  the scan can enter the book.

* **Best-effort, never raises.** ``load_best_config`` degrades to the baseline on
  any read/parse failure; the live ``factor_fn`` returns ``[]`` on any failure
  (the sleeve simply holds no conviction that week). The heavy provider / bundle
  imports are LAZY inside ``factor_fn`` so importing this module offline pulls in
  nothing network-bound.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from v2.self_evolve.config import StrategyConfig, load_config
from v2.self_evolve.strategy_gen import generate_holdings
from v2.self_evolve.versioning import read_path_log, read_version

logger = logging.getLogger(__name__)

#: The repo's strategy-skill directory (holds ``skill_config.yaml`` + ``versions/``).
#: ``parents[2]`` is the repo root: ``v2/self_evolve/graduate.py`` -> ``v2`` ->
#: ``self_evolve`` -> repo root is two hops up from the package dir.
DEFAULT_BASE_DIR = Path(__file__).resolve().parents[2] / "strategy_skill"

#: Default price/fundamental history window (calendar days) the live ``factor_fn``
#: prefetches behind each scan date. ~3y so the longest lookback (momentum ~252
#: trading days) and realized-vol windows have ample history.
DEFAULT_LOOKBACK_DAYS = 1100


def load_best_config(base_dir=DEFAULT_BASE_DIR) -> StrategyConfig:
    """Return the top val-retained :class:`StrategyConfig`, else the baseline.

    The "best" config is the LAST entry in ``read_path_log(base_dir)`` whose
    ``kept`` flag is True — i.e. the most recent candidate the evolution loop
    actually adopted. Its full config is read back from that version's
    ``version.json`` (``record["config"]``) and rebuilt via ``StrategyConfig``.

    Best-effort and total: a missing/empty log, no kept entry, an unreadable
    version, or a config that fails to rebuild all fall back to loading the
    ``skill_config.yaml`` baseline. Only a missing/broken BASELINE re-raises
    (a real misconfiguration worth surfacing).
    """
    try:
        log = read_path_log(base_dir)
    except Exception:  # noqa: BLE001 — versioning reads are best-effort; fall back
        logger.warning("load_best_config: read_path_log failed for %s; using baseline", base_dir, exc_info=True)
        log = []

    for entry in reversed(log):
        if not (isinstance(entry, dict) and entry.get("kept") is True):
            continue
        v_id = entry.get("v_id")
        if not v_id:
            continue
        try:
            record = read_version(base_dir, v_id)
            config_dict = record.get("config")
            if isinstance(config_dict, dict):
                return _config_from_dict(config_dict)
        except Exception:  # noqa: BLE001 — a junk version row is skipped, not fatal
            logger.warning("load_best_config: version %s unreadable; trying older", v_id, exc_info=True)
            continue

    # No kept version usable → baseline. A broken baseline is a real misconfig.
    return load_config(Path(base_dir) / "skill_config.yaml")


def _config_from_dict(config_dict: dict) -> StrategyConfig:
    """Rebuild a :class:`StrategyConfig` from a persisted ``asdict`` mapping.

    Only known dataclass fields are consumed, so a record that carried extra
    bookkeeping keys still rebuilds. ``__post_init__`` re-normalizes the factor
    weights (idempotent for an already-normalized stored config).
    """
    from dataclasses import fields

    known = {f.name for f in fields(StrategyConfig)}
    return StrategyConfig(**{k: v for k, v in config_dict.items() if k in known})


def build_factor_fn(
    provider_factory,
    universe_tickers,
    *,
    base_dir=DEFAULT_BASE_DIR,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> Callable[[str], list[str]]:
    """Build the live ``factor_fn(scan_date) -> list[str]`` seam.

    The returned callable, given a scan date, prefetches price/fundamental
    ``bundles`` for ``universe_tickers`` over ``[scan_date - lookback_days,
    scan_date]``, loads the best evolved config, and runs
    :func:`generate_holdings` as-of ``scan_date`` — returning just the held
    tickers (the harness equal-weights them). It is best-effort: ANY failure
    (data fetch, config load, holdings) yields ``[]`` so the sleeve holds no
    conviction rather than crashing the weekly run.

    The provider / bundle imports are deferred INSIDE ``factor_fn`` so importing
    this module (and the offline test suite) drags in no network/data stack.

    Args:
        provider_factory: Zero-arg factory returning a fresh data client
            (mirrors the other live seams; passed through to ``build_bundles``).
        universe_tickers: The ticker universe to score each week.
        base_dir: Version-store dir to read the best config from.
        lookback_days: Calendar-day history window prefetched behind each scan.
    """

    def factor_fn(scan_date: str) -> list[str]:
        try:
            from datetime import date, timedelta

            from v2.workflow_backtest.bundles import build_bundles

            end = date.fromisoformat(scan_date)
            start = (end - timedelta(days=lookback_days)).isoformat()
            # No look-ahead: bundles are bounded at end_date == scan_date, and
            # generate_holdings clamps every bar to <= asof on top of that.
            bundles = build_bundles(
                universe_tickers,
                provider_factory,
                start,
                scan_date,
            )
            config = load_best_config(base_dir)
            holdings = generate_holdings(bundles, scan_date, config)
            return list(holdings.keys())
        except Exception:  # noqa: BLE001 — never raise into the runner; no conviction
            logger.exception("factor_fn: failed for scan_date=%s; returning no targets", scan_date)
            return []

    return factor_fn
