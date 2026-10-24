"""CLI entry point for the self-evolve loop — the LIVE (paid) driver.

This is the thin wiring that takes the offline-tested pieces and runs them for
real: load a ticker universe, build price+enrich bundles spanning the full
train+val+test span, run :func:`v2.self_evolve.loop.evolve` with the LIVE
DeepSeek proposer, then — ONCE, and only AFTER the loop has returned — read the
held-out ``test`` sample a single time via :func:`v2.self_evolve.backtest.backtest`
on the retained-best config, and render the report.

Sample isolation is preserved end-to-end: the loop reads train+val only (its own
invariant); the SOLE ``backtest(..., "test")`` call in this whole program is the
one below, after ``evolve`` finishes. The retained-best config is the LAST KEPT
version's config, read back from the on-disk version store.

The provider / universe imports are LAZY (inside :func:`main`) so importing this
module — or running the offline pytest smoke — never pulls in the data stack or
touches the network. The OFFLINE end-to-end coverage lives in
``v2/self_evolve/test_smoke.py`` (stub proposer, synthetic bundles); this CLI is
the paid counterpart and is not exercised by the test suite.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

#: Span start for bundle prefetch — comfortably before the train window start
#: (2016-01-01) so the factor lookbacks have history on the first rebalance.
_SPAN_START = "2015-01-01"


def _best_config(base_dir):
    """The retained-best config = the LAST KEPT version's config, off disk.

    Walks the path log for the most recent ``kept`` entry and rebuilds its
    persisted config into a :class:`~v2.self_evolve.config.StrategyConfig`. Falls
    back to the ``v0`` baseline (and finally to ``skill_config.yaml``) so a run
    where nothing was kept still yields a config to score on test.
    """
    from v2.self_evolve.config import StrategyConfig, load_config
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
                return StrategyConfig(**cfg)
            except (TypeError, ValueError):
                continue

    # Last resort: the on-disk baseline yaml.
    return load_config(os.path.join(base_dir, "skill_config.yaml"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Self-evolve a factor strategy, then read the held-out test sample once.")
    parser.add_argument("--iterations", type=int, default=10, help="Number of propose->evaluate rounds.")
    parser.add_argument("--universe", default="nasdaq100", help="Universe kind (sp500 | nasdaq100 | ...).")
    parser.add_argument("--base-dir", default="strategy_skill", help="Skill dir holding skill_config.yaml + the version store.")
    parser.add_argument("--out-dir", default="self_evolve_run", help="Directory for the rendered report.")
    parser.add_argument("--provider", default=None, help="Data provider override (fd | finnhub | eodhd | ...).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # -- LAZY imports: keep module import (and the offline smoke) network-free.
    from v2.data.factory import get_provider_factory
    from v2.scanner.universes.loader import load_universe
    from v2.self_evolve.backtest import backtest
    from v2.self_evolve.config import load_config
    from v2.self_evolve.loop import evolve
    from v2.self_evolve.report import write_report
    from v2.workflow_backtest.bundles import build_bundles

    base_dir = args.base_dir
    config_path = os.path.join(base_dir, "skill_config.yaml")
    skill_md_path = os.path.join(base_dir, "SKILL.md")

    base_config = load_config(config_path)
    skill_md = ""
    try:
        with open(skill_md_path, encoding="utf-8") as fh:
            skill_md = fh.read()
    except OSError:
        logger.info("no SKILL.md at %s; proceeding with empty kernel text", skill_md_path)

    # -- universe + bundles spanning the FULL train+val+test span.
    tickers = load_universe(args.universe)
    end_date = _dt.date.today().isoformat()
    logger.info("building bundles: %d tickers over %s..%s", len(tickers), _SPAN_START, end_date)
    provider_factory = get_provider_factory(args.provider)
    bundles = build_bundles(tickers, provider_factory, _SPAN_START, end_date, enrich=True)

    # -- the evolution loop (LIVE proposer = the default). Reads train+val only.
    logger.info("evolving for %d iterations", args.iterations)
    evolve(bundles, base_config, iterations=args.iterations, base_dir=base_dir, skill_md=skill_md)

    # -- retained-best config = last KEPT version's config (off disk).
    best_config = _best_config(base_dir)

    # -- THE single, post-loop, held-out read: backtest("test") exactly ONCE.
    logger.info("scoring retained-best on the held-out TEST sample (single read)")
    test_metrics = backtest(bundles, best_config, "test")

    out = write_report(
        args.out_dir,
        base_dir=base_dir,
        bundles=bundles,
        best_config=best_config,
        test_metrics=test_metrics,
    )
    logger.info("report written: %s | test_sharpe=%s", out.get("report_html"), out.get("test_sharpe"))
    print(out["report_md"])
    print(out["report_html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
