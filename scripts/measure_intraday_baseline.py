"""One-off: measure the intraday_move BASELINE interestingness on real data.

The re-scoped scanner-evolve tunes a single detector — ``intraday_move`` — under
the pre-filter (interestingness-vs-random) metric. Before spending compute on
evolution, this confirms the BASELINE config already flags bigger movers than
random (positive interestingness) on real prices, in train + val. No evolution
loop; baseline config only; the held-out ``test`` sample is NOT touched.

Bounded (~30 tickers) so it runs in a few minutes. Prices via the env provider
(hybrid → EODHD EOD OHLCV + SPY). The replay is no-lookahead (CachedAsOfClient);
forward returns are the graded outcome.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/measure_intraday_baseline.py
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
from v2.scanner.universes import load_universe

logger = logging.getLogger("measure_intraday_baseline")

_N_TICKERS = 30
#: train+val union (bear_2022 / bull_2023_24 / choppy_2025) − ~400d lookback,
#: + ~45d forward. The held-out test window (2025-09+) is deliberately excluded.
_SPAN_START = "2020-11-01"
_SPAN_END = "2025-09-30"
_REBALANCE_STEP = 5


def _fmt(m: dict) -> str:
    a = m.get("alpha_5d")
    a_s = f"{a:+.5f}" if isinstance(a, float) else "n/a"
    return f"interestingness_diff={m['interestingness_diff']:+.5f} " f"t={m['interestingness_t']:+.2f} " f"n_fired={m['n_fired']:>5d} " f"| signed_diff={m['signed_diff']:+.5f} alpha_5d={a_s}"


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load_config(Path(_evolve_pkg.__file__).parent / "scanner_skill_config.yaml")
    factory = get_provider_factory()
    universe = load_universe("nasdaq100_sp500")[:_N_TICKERS]

    logger.info("prefetching %d tickers + SPY over %s..%s", len(universe), _SPAN_START, _SPAN_END)
    bundles = run_eval.prefetch_price_bundles(universe, factory, _SPAN_START, _SPAN_END)
    spy = TickerBundle(ticker="SPY", prices=run_eval.fetch_spy(factory, _SPAN_START, _SPAN_END))
    n_with_bars = sum(1 for b in bundles.values() if b.prices)
    logger.info("prefetched: %d/%d tickers have bars; SPY bars=%d", n_with_bars, len(universe), len(spy.prices))

    print("\n=== intraday_move BASELINE interestingness (SPY-relative) ===")
    cache: dict = {}
    for sample in ("train", "val"):
        m = scanner_fitness(
            bundles,
            cfg,
            sample,
            window_of=samples.window_of,
            spy_bundle=spy,
            cache=cache,
            rebalance_step=_REBALANCE_STEP,
        )
        verdict = "POSITIVE" if m["interestingness_diff"] > 0 else "NOT positive"
        print(f"[{sample:>5}] {_fmt(m)}   -> {verdict}")

    print("\n=== same, RAW (no SPY adjustment) for comparison ===")
    cache_raw: dict = {}
    for sample in ("train", "val"):
        m = scanner_fitness(
            bundles,
            cfg,
            sample,
            window_of=samples.window_of,
            spy_bundle=None,
            cache=cache_raw,
            rebalance_step=_REBALANCE_STEP,
        )
        verdict = "POSITIVE" if m["interestingness_diff"] > 0 else "NOT positive"
        print(f"[{sample:>5}] {_fmt(m)}   -> {verdict}")

    print("\nNote: interestingness_diff > 0 with t >= ~2 = the baseline flags bigger movers than random")
    print("(the pre-filter's job). The LIVE scanner forward-test remains the real judge.")


if __name__ == "__main__":
    main()
