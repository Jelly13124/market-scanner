"""Scanner self-evolve wiring + CLI — tune detector thresholds via the SHARED loop.

This is the scanner's counterpart to :mod:`v2.self_evolve.run`. It does NOT
re-implement the evolution loop: it REUSES :func:`v2.self_evolve.loop.evolve` by
injecting the scanner-specific seams (config rebuild, apply_delta, the A/B-vs-
random keep rule, and a ``backtest_fn`` that closes over
:func:`~v2.scanner.evolve.fitness.scanner_fitness`). The loop's hard invariant is
preserved end-to-end: it reads **train + val** only; the held-out **test** sample
is read exactly ONCE, post-loop, on the retained-best config.

The scanner kernel is pinned (invariant #2): ``event_weight == 1.0`` /
``quant_weight == 0.0`` are NOT adjustable, so the proposer can only move detector
thresholds, per-detector severity multipliers, and ``top_n`` — never re-enable the
known-bad fundamental signals.

``evolve_scanner`` is fully offline-testable (stub proposer + stub/real fitness
over synthetic bundles). ``main`` is the LIVE (paid) driver: it prefetches price
bundles ONCE over the full train+val+test span and runs the loop; the network
prefetch is injectable (``prefetch_fn`` / ``spy_fetch_fn``) so Task 7's smoke test
exercises the CLI offline.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import fields
from pathlib import Path

from v2.scanner.evolve import report, samples
from v2.scanner.evolve.config import (
    SCANNER_ADJUSTABLE,
    ScannerEvolveConfig,
    load_config,
)
from v2.scanner.evolve.config import apply_delta as scanner_apply_delta
from v2.scanner.evolve.fitness import scanner_fitness

logger = logging.getLogger(__name__)

#: keep-rule guardrail constants (documented at each use in ``_scanner_keep``).
_MIN_FIRED_ABS = 5  # absolute floor on n_fired (a config that fires almost nothing is noise)
_T_TOL = 0.5  # how much worse the candidate t_stat may be before we reject (significance guard)

#: Prefetch padding (mirrors run_eval._LOOKBACK_DAYS / _FORWARD_DAYS). Detector
#: lookbacks reach ~252 bars (≈ a year) → ~400d before; forward returns reach
#: ~5 bars but we pad ~45d after to be safe.
_LOOKBACK_DAYS = 400
_FORWARD_DAYS = 45


#: The prose DISCIPLINE forwarded to the proposer (the exact adjustable paths are
#: injected separately via ``SCANNER_ADJUSTABLE``). This is the fixed contract the
#: LLM must respect — what the scanner is, and what success means.
SCANNER_SKILL_MD = """\
# Scanner self-evolve kernel

You are tuning a price-ONLY, event-driven SCANNER. The scanner is an LLM-cost
PRE-FILTER: it screens a universe down to a Top-N watchlist that a downstream
agent then analyzes. It is NOT a directional alpha model — do not optimize for
directional or SPY-adjusted alpha.

## Fixed kernel (NEVER change — not adjustable)
- `event_weight = 1.0`, `quant_weight = 0.0`. The fundamental signals are PROVEN
  to hurt; they can never be re-enabled. The proposer cannot touch these.

## What you MAY tune (within declared ranges)
- Detector thresholds: high_breakout `window`, ma_cross `fast`/`slow`,
  gap `threshold`, rsi_divergence `div_window`.
- Per-detector `severity_mult` (one multiplier per detector).
- `top_n` (the size of the fired watchlist).

## The objective
Improve the A/B-vs-random forward-return `diff` on VALIDATION: the mean
forward return of the fired Top-N MINUS a seeded random same-universe baseline.
A bigger `diff` means the screen concentrates the universe better than chance.

## Discipline
- A config that fires almost nothing has a meaningless `diff`; keep enough
  tickers firing (an n_fired guardrail enforces this).
- Don't chase a marginally higher `diff` at the cost of a collapsing t_stat —
  the edge must stay at least roughly as significant.
- Validation `diff` is NOT the live edge. The honest judge is the live scanner
  forward-test; treat val as a search signal, not a verdict.
"""


def _rebuild_scanner_config(config_dict: dict) -> ScannerEvolveConfig:
    """Reconstruct a :class:`ScannerEvolveConfig` from a persisted ``asdict`` mapping.

    Only known dataclass fields are consumed (forward/backward-compatible with a
    record that carried extra keys). Mirrors the factor loop's ``_rebuild_config``.
    """
    known = {f.name for f in fields(ScannerEvolveConfig)}
    kwargs = {k: v for k, v in config_dict.items() if k in known}
    return ScannerEvolveConfig(**kwargs)


def _scanner_keep(candidate_val: dict, best_val: dict, base_val: dict) -> bool:
    """The scanner KEEP rule (A/B-vs-random). ``True`` → keep, else roll back.

    Reads the fitness dicts (``{fitness, diff, t_stat, n_fired, alpha_5d}``)
    rather than the factor sharpe/turnover/drawdown. Keep iff ALL hold:
    """
    cand_diff = candidate_val.get("diff")
    if cand_diff is None:
        # No measurable edge → nothing to keep.
        return False

    # n_fired guardrail: the screen must not COLLAPSE. Require at least the
    # absolute floor AND half the baseline's fired count, so a config that stops
    # firing (and thus has a meaningless diff) is rejected.
    base_n_fired = base_val.get("n_fired", 0)
    floor = max(_MIN_FIRED_ABS, 0.5 * base_n_fired)
    if candidate_val.get("n_fired", 0) < floor:
        return False

    # fitness improves: the candidate's diff must strictly beat the running-best
    # (a None best diff degrades to -inf so any real diff clears it).
    best_diff = best_val.get("diff")
    best_diff = float("-inf") if best_diff is None else best_diff
    if not (cand_diff > best_diff):
        return False

    # t_stat guardrail: the edge may not become MEANINGFULLY less significant.
    # Reject if the candidate t_stat is worse than the running-best's by > _T_TOL.
    best_t = best_val.get("t_stat", float("-inf"))
    if candidate_val.get("t_stat", 0) < best_t - _T_TOL:
        return False

    return True


def evolve_scanner(
    bundles,
    base_config: ScannerEvolveConfig,
    *,
    iterations: int,
    base_dir,
    skill_md: str | None = None,
    propose_fn=None,
    spy_bundle=None,
    cache: dict | None = None,
    llm_fn=None,
) -> list[dict]:
    """Run the scanner evolution loop and return the optimization path log.

    Wraps :func:`v2.self_evolve.loop.evolve` with the scanner seams. The loop
    reads **train + val** only — ``test`` is never passed here (the CLI reads it
    once, post-loop).

    Parameters
    ----------
    bundles
        ``{ticker: TickerBundle}`` — opaque to the loop; passed to ``scanner_fitness``.
    base_config
        The baseline :class:`ScannerEvolveConfig` (the ``v0`` running-best).
    iterations
        Number of propose→evaluate rounds this invocation attempts.
    base_dir
        Version store / path log directory. Resumed if it already holds versions.
    skill_md
        Kernel/discipline text for the proposer; defaults to :data:`SCANNER_SKILL_MD`.
    propose_fn
        Override the proposer seam (tests inject a stub). Defaults to
        :func:`v2.self_evolve.proposer.propose` bound to ``SCANNER_ADJUSTABLE`` +
        the scanner ``apply_delta`` (and threading ``llm_fn``).
    spy_bundle
        Optional SPY :class:`TickerBundle` for the alpha_5d side-metric.
    cache
        Shared parse cache for the forward-return path (prefetch-once). Built once
        here and reused across all iterations; a fresh ``{}`` if not supplied.
    llm_fn
        Forwarded to the default proposer (ignored when ``propose_fn`` is injected).
    """
    from v2.self_evolve import proposer as _proposer_mod
    from v2.self_evolve.loop import evolve

    # ONE shared prefetch-once parse cache for the whole run (Task 4): bundles are
    # immutable, so a config-only delta reuses every parsed series across iterations.
    cache = {} if cache is None else cache

    def backtest_fn(b, c, s):
        return scanner_fitness(b, c, s, window_of=samples.window_of, spy_bundle=spy_bundle, cache=cache)

    if propose_fn is None:

        def propose_fn(skill, config, val_history, *, llm_fn=llm_fn):
            return _proposer_mod.propose(
                skill,
                config,
                val_history,
                llm_fn=llm_fn,
                adjustable=SCANNER_ADJUSTABLE,
                apply_delta=scanner_apply_delta,
            )

    return evolve(
        bundles,
        base_config,
        iterations=iterations,
        base_dir=base_dir,
        skill_md=skill_md or SCANNER_SKILL_MD,
        propose_fn=propose_fn,
        backtest_fn=backtest_fn,
        apply_delta_fn=scanner_apply_delta,
        rebuild_config_fn=_rebuild_scanner_config,
        keep_fn=_scanner_keep,
    )


def _best_config(base_dir) -> ScannerEvolveConfig:
    """The retained-best config = the LAST KEPT version's config, off disk.

    Walks the path log for the most recent ``kept`` entry and rebuilds it. Falls
    back to the ``v0`` baseline so a run where nothing was kept still yields a
    config to score on test.
    """
    from v2.self_evolve.versioning import read_path_log, read_version

    last_kept = None
    for entry in read_path_log(base_dir):
        if entry.get("kept"):
            last_kept = entry.get("v_id")

    for vid in (last_kept, "v0"):
        if not vid:
            continue
        rec = read_version(base_dir, vid)
        cfg = rec.get("config")
        if isinstance(cfg, dict):
            try:
                return _rebuild_scanner_config(cfg)
            except (TypeError, ValueError, KeyError):
                continue
    raise RuntimeError(f"no retained config could be reconstructed under {base_dir}")


def _full_span() -> tuple[str, str]:
    """Prefetch span = union of ALL sample windows (train+val+TEST), padded.

    Earliest start − ~400d to latest end + ~45d (mirrors ``run_eval._full_span``).
    Reads ``test`` here only to size the PREFETCH — the loop still never scores it.
    """
    from datetime import date, timedelta

    starts, ends = [], []
    for spans in samples.SAMPLES.values():
        for w in spans:
            starts.append(w.start)
            ends.append(w.end)
    start = (date.fromisoformat(min(starts)) - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    end = (date.fromisoformat(max(ends)) + timedelta(days=_FORWARD_DAYS)).isoformat()
    return start, end


def main(argv=None, *, prefetch_fn=None, spy_fetch_fn=None, propose_fn=None, llm_fn=None) -> int:
    """CLI: prefetch ONCE → evolve (train+val) → read TEST once post-loop → report.

    ``prefetch_fn`` / ``spy_fetch_fn`` are injectable so Task 7's smoke test runs
    the whole CLI offline; ``propose_fn`` / ``llm_fn`` are threaded into
    ``evolve_scanner`` so the smoke can drive the full path with a stub proposer
    (no LLM). All default to the real (live) seams.
    """
    from datetime import datetime, timezone
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Self-evolve the price-only scanner (detector thresholds), then read the held-out test sample once.")
    parser.add_argument("--iterations", type=int, default=10, help="Number of propose->evaluate rounds.")
    parser.add_argument("--universe", default="nasdaq100_sp500", help="Universe kind to evolve over.")
    parser.add_argument("--out-dir", default="scanner_evolve_run", help="Version store + summary directory.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(Path(__file__).parent / "scanner_skill_config.yaml")

    # -- prefetch span = union of ALL sample windows (train+val+test), padded.
    span_start, span_end = _full_span()
    logger.info("scanner-evolve prefetch span: %s..%s (universe=%s)", span_start, span_end, args.universe)

    # -- Prefetch bundles + SPY ONCE over the full span (injectable for offline tests).
    if prefetch_fn is None or spy_fetch_fn is None:
        from v2.data.factory import get_provider_factory
        from v2.scanner.eval import run_eval
        from v2.scanner.eval.cached_asof_client import TickerBundle
        from v2.scanner.universes import load_universe

        provider_factory = get_provider_factory()

        if prefetch_fn is None:

            def prefetch_fn(start, end):
                tickers = load_universe(args.universe)
                return run_eval.prefetch_price_bundles(tickers, provider_factory, start, end)

        if spy_fetch_fn is None:

            def spy_fetch_fn(start, end):
                return TickerBundle(ticker="SPY", prices=run_eval.fetch_spy(provider_factory, start, end))

    bundles = prefetch_fn(span_start, span_end)
    spy = spy_fetch_fn(span_start, span_end)

    # -- The evolution loop. Reads TRAIN + VAL only (the loop's own invariant).
    cache: dict = {}
    logger.info("evolving scanner for %d iterations", args.iterations)
    path_log = evolve_scanner(
        bundles,
        base_config,
        iterations=args.iterations,
        base_dir=out_dir,
        spy_bundle=spy,
        cache=cache,
        propose_fn=propose_fn,
        llm_fn=llm_fn,
    )

    # -- THE single, post-loop, held-out read: scanner_fitness("test") exactly ONCE,
    #    on the retained-best config reconstructed from the version store.
    best_config = _best_config(out_dir)
    logger.info("scoring retained-best on the held-out TEST sample (single read)")
    test_metrics = scanner_fitness(
        bundles,
        best_config,
        "test",
        window_of=samples.window_of,
        spy_bundle=spy,
        cache=cache,
    )

    # -- The run report (md + html), rendered from the version store + the single
    #    post-loop test read. ``generated_at`` is computed HERE (the report is pure
    #    rendering and never calls datetime.now() itself).
    del path_log  # the report reads the path log off disk; we don't pass it through.
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    md_path, html_path = report.write_report(
        out_dir,
        test_metrics=test_metrics,
        generated_at=generated_at,
    )
    logger.info("report written: %s + %s | test diff=%s", md_path, html_path, test_metrics.get("diff"))
    print(str(md_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
