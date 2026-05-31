"""Bounded Phase-3 full-replay confirmation for the scanner-eval harness.

Phases 1–2 of the eval study each detector / quant signal in isolation
(interestingness vs random, cross-sectional rank-IC). Phase 3 is the
*confirmation* run: replay the REAL scanner Top-N over each regime using the
existing full-replay engine, with quant signals ON and OFF, to answer two
production questions directly:

  (a) what mean 5d alpha did the actual Top-N earn in this regime, and
  (b) does the quant overlay help — i.e. ON-minus-OFF alpha delta (ablation).

Two hard properties, both load-bearing for an overnight unattended run:

  * **Bounded.** Every engine call passes ``max_days`` so a regime can't run
    for hours. Full-replay on a large universe is slow; Phase 3 is a smoke-
    sized confirmation, not an exhaustive sweep.
  * **Fail-soft.** A single engine failure (missing data, provider hiccup) is
    logged and leaves that one CSV as ``None`` — it never aborts the other
    regime/quant combinations. Downstream summary renders the missing cell as
    "n/a" rather than losing the whole report.

This module owns only the orchestration + CSV aggregation; the heavy lifting
(scan replay, forward returns, alpha) is the engine's. ``run_backtest`` is
injectable purely so tests can drive the plumbing offline without a network.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_phase3(
    regimes,
    *,
    universe_kind="nasdaq100_sp500",
    top_n=20,
    max_days=8,
    out_dir,
    provider_factory=None,
    run_backtest=None,
) -> dict:
    """Run a bounded full replay for each regime x (quant ON, quant OFF).

    For every regime window we invoke the engine twice — once with quant
    signals on (the production config) and once off (ablation) — writing one
    CSV per combination into ``out_dir``. Each call is wrapped in try/except:
    a failure is logged and leaves that combination's CSV ``None``; it never
    aborts the rest of the matrix.

    ``run_backtest`` defaults to the real ``v2.backtesting.engine.run_backtest``
    and is injectable so tests exercise the plumbing without a real replay.

    Returns ``{regime_name: {"quant_on_csv": Path|None, "quant_off_csv": Path|None}}``.
    """
    from v2.scanner.eval.regimes import RegimeWindow  # noqa: F401 — type only

    if run_backtest is None:
        from v2.backtesting.engine import run_backtest as run_backtest

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict = {}
    for rw in regimes:
        name = getattr(rw, "name", None) or rw["name"]
        start = getattr(rw, "start", None) or rw["start"]
        end = getattr(rw, "end", None) or rw["end"]

        entry: dict = {}
        for use_quant, key in ((True, "quant_on_csv"), (False, "quant_off_csv")):
            csv_path = out_dir / f"phase3_{name}_quant{'on' if use_quant else 'off'}.csv"
            try:
                run_backtest(
                    universe_kind=universe_kind,
                    universe_tickers=None,
                    weights_payload=None,
                    start_date=start,
                    end_date=end,
                    top_n=top_n,
                    output_path=csv_path,
                    max_days=max_days,
                    provider_factory=provider_factory,
                    use_quant_signals=use_quant,
                )
                entry[key] = csv_path if csv_path.exists() else None
            except Exception:
                logger.exception("phase3 backtest failed for %s quant=%s", name, use_quant)
                entry[key] = None
        result[name] = entry
    return result


def _mean_col(csv_path, col) -> tuple[float | None, int]:
    """Mean of the non-empty float ``col`` in ``csv_path``.

    Returns ``(mean_or_None, n_rows_with_value)``. A ``None`` path, a missing
    file, an absent column, or zero usable values all collapse to ``(None, 0)``
    — never a raise, so a malformed CSV can't sink the summary.
    """
    if csv_path is None:
        return None, 0
    path = Path(csv_path)
    if not path.exists():
        return None, 0

    values: list[float] = []
    try:
        with path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or col not in reader.fieldnames:
                return None, 0
            for row in reader:
                raw = row.get(col)
                if raw is None or raw == "":
                    continue
                try:
                    values.append(float(raw))
                except (TypeError, ValueError):
                    continue
    except OSError:
        logger.exception("phase3 summary failed reading %s", path)
        return None, 0

    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def summarize_phase3(run_result: dict) -> dict:
    """Turn the :func:`run_phase3` path map into report-ready numbers per regime.

    Returns ``{regime_name: {...}}`` where each value carries:

      * ``mean_alpha_5d`` / ``mean_dir_alpha_5d`` — from the quant-ON CSV (the
        production config: this is "what the real Top-N earned"),
      * ``quant_on_alpha`` / ``quant_off_alpha`` — mean ``alpha_5d`` per arm,
      * ``quant_delta`` — ``quant_on_alpha - quant_off_alpha`` (``None`` if
        either arm is missing): the ablation answer to "does quant help?",
      * ``n_on`` / ``n_off`` — usable-row counts behind each arm's mean.

    Any missing CSV degrades to ``None`` numbers + ``0`` counts, never a crash.
    """
    out: dict = {}
    for name, entry in run_result.items():
        on_csv = entry.get("quant_on_csv")
        off_csv = entry.get("quant_off_csv")

        quant_on_alpha, n_on = _mean_col(on_csv, "alpha_5d")
        quant_off_alpha, n_off = _mean_col(off_csv, "alpha_5d")
        mean_dir_alpha_5d, _ = _mean_col(on_csv, "dir_alpha_5d")

        if quant_on_alpha is not None and quant_off_alpha is not None:
            quant_delta = quant_on_alpha - quant_off_alpha
        else:
            quant_delta = None

        out[name] = {
            # mean_alpha_5d is the production (quant-ON) number by definition.
            "mean_alpha_5d": quant_on_alpha,
            "mean_dir_alpha_5d": mean_dir_alpha_5d,
            "quant_on_alpha": quant_on_alpha,
            "quant_off_alpha": quant_off_alpha,
            "quant_delta": quant_delta,
            "n_on": n_on,
            "n_off": n_off,
        }
    return out
