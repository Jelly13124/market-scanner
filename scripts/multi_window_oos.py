"""Multi-window out-of-sample robustness: baseline v0 vs evolved v0.0.9 across
several held-out periods (none used in train/val or for selection).

The single held-out test (2025-09+) said evolution helped +1.06pp — but n=1 can
be lucky. This scores BOTH configs on additional non-overlapping windows carved
from the unused gaps between/around the train(bear+bull)/val(choppy) windows, so
we can see whether the evolved config's edge is stable across regimes/periods.

All windows below are disjoint from train (bear_2022 2022-01..2022-10,
bull_2023_24 2023-10..2024-07) and val (choppy_2025 2025-02..2025-08), and none
was used to SELECT the config (selection happened on val only). Injected via
scanner_fitness's `window_of` seam.

Run: PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/multi_window_oos.py
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

import v2.scanner.evolve as _evolve_pkg
from v2.data.factory import get_provider_factory
from v2.scanner.eval import run_eval
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.evolve.config import load_config
from v2.scanner.evolve.fitness import scanner_fitness
from v2.scanner.evolve.run import _best_config
from v2.scanner.universes import load_universe

logger = logging.getLogger("multi_window_oos")

_N_TICKERS = 40
_OUT_DIR = "scanner_evolve_run"
#: widened so the earliest (2021) window has enough lookback for z_window=90.
_SPAN_START = "2020-06-01"
_SPAN_END = "2026-07-16"

#: (name, start, end) — each disjoint from train/val and unused for selection.
_WINDOWS = [
    ("2021_bull", "2021-03-01", "2021-12-31"),
    ("2023_h1", "2022-11-01", "2023-09-30"),
    ("2024h2_25h1", "2024-08-01", "2025-02-10"),
    ("heldout_test", "2025-09-01", "2026-06-01"),
]


def _score(bundles, cfg, start, end, spy) -> dict:
    return scanner_fitness(
        bundles,
        cfg,
        "oos",
        window_of=lambda _s: [(start, end)],
        spy_bundle=spy,
    )


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    baseline = load_config(Path(_evolve_pkg.__file__).parent / "scanner_skill_config.yaml")
    evolved = _best_config(_OUT_DIR)  # v0.0.9

    factory = get_provider_factory()
    universe = load_universe("nasdaq100_sp500")[:_N_TICKERS]
    logger.info("prefetching %d tickers + SPY over %s..%s", len(universe), _SPAN_START, _SPAN_END)
    bundles = run_eval.prefetch_price_bundles(universe, factory, _SPAN_START, _SPAN_END)
    spy = TickerBundle(ticker="SPY", prices=run_eval.fetch_spy(factory, _SPAN_START, _SPAN_END))

    print(f"\n{'window':>14} | {'baseline':>22} | {'evolved':>22} | {'delta':>8}")
    print("-" * 76)
    wins = 0
    deltas = []
    for name, start, end in _WINDOWS:
        b = _score(bundles, baseline, start, end, spy)
        e = _score(bundles, evolved, start, end, spy)
        d = (e["interestingness_diff"] - b["interestingness_diff"]) * 100
        deltas.append(d)
        if d > 0:
            wins += 1
        bs = f"{b['interestingness_diff']*100:+.2f}pp t={b['interestingness_t']:+.2f} n={b['n_fired']}"
        es = f"{e['interestingness_diff']*100:+.2f}pp t={e['interestingness_t']:+.2f} n={e['n_fired']}"
        print(f"{name:>14} | {bs:>22} | {es:>22} | {d:>+6.2f}pp")

    mean_d = sum(deltas) / len(deltas) if deltas else 0.0
    print("-" * 76)
    print(f"evolved beat baseline in {wins}/{len(_WINDOWS)} windows; mean OOS delta = {mean_d:+.2f}pp")
    print("(all windows held-out: none used in train/val or for selection. LIVE forward-test = real judge.)")


if __name__ == "__main__":
    main()
