"""Baseline (v0) vs evolved (v0.0.9) — out-of-sample comparison on the held-out test.

Selection happened entirely on val, so reading BOTH configs on test is a legitimate
held-out comparison (test was never used to select). Answers: did evolution actually
improve the pre-filter out-of-sample, or is the evolved config just riding the
baseline's positivity? Same 40-ticker universe / span / fitness params as the evolve
run, so the evolved test number should reproduce +2.37pp (a determinism sanity check).

Run: PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/compare_evolved_vs_baseline_test.py
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

import v2.scanner.evolve as _evolve_pkg
from v2.data.factory import get_provider_factory
from v2.scanner.eval import run_eval
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.evolve import samples
from v2.scanner.evolve.config import load_config
from v2.scanner.evolve.fitness import scanner_fitness
from v2.scanner.evolve.run import _best_config, _full_span
from v2.scanner.universes import load_universe

logger = logging.getLogger("compare_evolved_vs_baseline_test")

_N_TICKERS = 40
_OUT_DIR = "scanner_evolve_run"


def _fmt(m: dict) -> str:
    return f"interestingness={m['interestingness_diff']*100:+.2f}pp t={m['interestingness_t']:+.2f} n_fired={m['n_fired']:>4d} | signed={m['signed_diff']*100:+.2f}pp"


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    baseline = load_config(Path(_evolve_pkg.__file__).parent / "scanner_skill_config.yaml")
    evolved = _best_config(_OUT_DIR)  # the retained-best (v0.0.9)

    factory = get_provider_factory()
    universe = load_universe("nasdaq100_sp500")[:_N_TICKERS]
    span_start, span_end = _full_span()  # includes the test window
    logger.info("prefetching %d tickers + SPY over %s..%s", len(universe), span_start, span_end)
    bundles = run_eval.prefetch_price_bundles(universe, factory, span_start, span_end)
    spy = TickerBundle(ticker="SPY", prices=run_eval.fetch_spy(factory, span_start, span_end))

    cache: dict = {}  # per-ticker price parse is config-independent → shared
    rows = []
    for label, cfg in (("baseline v0", baseline), ("evolved v0.0.9", evolved)):
        for sample in ("val", "test"):
            m = scanner_fitness(bundles, cfg, sample, window_of=samples.window_of, spy_bundle=spy, cache=cache)
            rows.append((label, sample, m))
            print(f"[{label:>15} | {sample:>4}] {_fmt(m)}")

    # The verdict: baseline vs evolved on the held-out test.
    bt = next(m for lbl, s, m in rows if lbl == "baseline v0" and s == "test")
    et = next(m for lbl, s, m in rows if lbl == "evolved v0.0.9" and s == "test")
    delta = (et["interestingness_diff"] - bt["interestingness_diff"]) * 100
    print("\n=== OUT-OF-SAMPLE VERDICT (held-out test) ===")
    print(f"baseline  test interestingness = {bt['interestingness_diff']*100:+.2f}pp (t={bt['interestingness_t']:+.2f})")
    print(f"evolved   test interestingness = {et['interestingness_diff']*100:+.2f}pp (t={et['interestingness_t']:+.2f})")
    print(f"evolution net OOS delta        = {delta:+.2f}pp")
    print("(positive delta = tuning helped out-of-sample; ~0 / negative = val gains were in-sample overfit)")


if __name__ == "__main__":
    main()
