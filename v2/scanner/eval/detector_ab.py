"""Detector A/B evaluation harness.

Measures whether a detector's fired events have predictive forward-return
value versus a random baseline drawn from the same price universe.  Data is
injected — no live network calls are made here.

Public API
----------
forward_return(closes, idx, horizon) -> float | None
evaluate_detector(*, fire_returns, baseline_returns, horizon) -> dict
run_ab(*, detector, prices_by_ticker, asof_dates_by_ticker,
        fd_factory, horizon, baseline_per_ticker, rng_seed) -> dict
"""

from __future__ import annotations

import math
import random

import numpy as np

from v2.scanner.detectors.base import close_of


# ---------------------------------------------------------------------------
# forward_return
# ---------------------------------------------------------------------------


def forward_return(closes: list[float], idx: int, horizon: int) -> float | None:
    """(close[idx+horizon] / close[idx]) - 1, or None if out of range/invalid."""
    if idx < 0 or idx >= len(closes):
        return None
    end_idx = idx + horizon
    if end_idx >= len(closes):
        return None
    base = closes[idx]
    if not base:  # zero or falsy → avoid division by zero
        return None
    return closes[end_idx] / base - 1.0


# ---------------------------------------------------------------------------
# evaluate_detector
# ---------------------------------------------------------------------------


def evaluate_detector(
    *,
    fire_returns: list[float],
    baseline_returns: list[float],
    horizon: int = 20,
) -> dict:
    """Compare forward returns of fired events vs a random baseline.

    Returns a dict with keys:
        n_fired, mean_fwd_return, baseline_mean, diff, t_stat, horizon

    Welch t-stat between the two arrays; guard n < 2 → t_stat = 0.0.
    """
    n_fired = len(fire_returns)
    n_base = len(baseline_returns)

    mean_fwd = float(np.mean(fire_returns)) if n_fired > 0 else 0.0
    baseline_mean = float(np.mean(baseline_returns)) if n_base > 0 else 0.0
    diff = mean_fwd - baseline_mean

    t_stat = 0.0
    if n_fired >= 2 and n_base >= 2:
        vA = float(np.var(fire_returns, ddof=1))
        vB = float(np.var(baseline_returns, ddof=1))
        denom_sq = vA / n_fired + vB / n_base
        if denom_sq > 0.0:
            t_stat = diff / math.sqrt(denom_sq)

    abs_fired = [abs(x) for x in fire_returns]
    abs_base = [abs(x) for x in baseline_returns]
    abs_mean_fired = float(np.mean(abs_fired)) if abs_fired else 0.0
    abs_mean_baseline = float(np.mean(abs_base)) if abs_base else 0.0
    interestingness_diff = abs_mean_fired - abs_mean_baseline
    interestingness_t = 0.0
    if len(abs_fired) >= 2 and len(abs_base) >= 2:
        vA = float(np.var(abs_fired, ddof=1))
        vB = float(np.var(abs_base, ddof=1))
        denom_sq = vA / len(abs_fired) + vB / len(abs_base)
        if denom_sq > 0.0:
            interestingness_t = interestingness_diff / math.sqrt(denom_sq)

    return {
        "n_fired": n_fired,
        "mean_fwd_return": mean_fwd,
        "baseline_mean": baseline_mean,
        "diff": diff,
        "t_stat": t_stat,
        "horizon": horizon,
        "abs_mean_fired": abs_mean_fired,
        "abs_mean_baseline": abs_mean_baseline,
        "interestingness_diff": interestingness_diff,
        "interestingness_t": interestingness_t,
    }


# ---------------------------------------------------------------------------
# run_ab
# ---------------------------------------------------------------------------


def run_ab(
    *,
    detector,
    prices_by_ticker: dict[str, list],
    asof_dates_by_ticker: dict[str, list[str]],
    fd_factory,
    horizon: int = 20,
    baseline_per_ticker: int = 20,
    rng_seed: int = 0,
) -> dict:
    """Run detector A/B eval against a seeded random baseline.

    For each (ticker, asof_date), call detector.detect(ticker, asof, fd).
    Collect forward `horizon` returns for FIRED events → fire_returns.
    Build a baseline: for each ticker sample `baseline_per_ticker` random
    valid indices, compute their forward returns → baseline_returns.

    Uses a seeded random.Random for determinism.
    """
    rng = random.Random(rng_seed)
    fire_returns: list[float] = []
    baseline_returns: list[float] = []

    for ticker, asof_dates in asof_dates_by_ticker.items():
        prices = prices_by_ticker.get(ticker, [])
        closes = [close_of(p) for p in prices]
        # Filter out None closes; build parallel list of valid (idx, close) pairs
        valid_closes = [c for c in closes if c is not None]

        # Map from price.time → index in closes list for fast lookup
        time_to_idx: dict[str, int] = {p.time: i for i, p in enumerate(prices)}

        fd = fd_factory(ticker)

        for asof in asof_dates:
            result = detector.detect(ticker, asof, fd)
            if result is not None and result.triggered:
                # Find the index of asof in the price series
                idx = time_to_idx.get(asof)
                if idx is not None:
                    ret = forward_return(valid_closes, idx, horizon)
                    if ret is not None:
                        fire_returns.append(ret)

        # Build baseline: sample random valid start indices where forward return exists
        valid_start_indices = [
            i for i in range(len(valid_closes))
            if i + horizon < len(valid_closes)
        ]
        if valid_start_indices:
            k = min(baseline_per_ticker, len(valid_start_indices))
            sampled = rng.sample(valid_start_indices, k)
            for i in sampled:
                ret = forward_return(valid_closes, i, horizon)
                if ret is not None:
                    baseline_returns.append(ret)

    return evaluate_detector(
        fire_returns=fire_returns,
        baseline_returns=baseline_returns,
        horizon=horizon,
    )


# ---------------------------------------------------------------------------
# CLI stub (untested — live calls guarded under __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run detector A/B eval (live data)")
    parser.add_argument("--detector", required=True, help="Detector name (e.g. high_breakout)")
    parser.add_argument("--tickers", nargs="+", required=True, help="Ticker list")
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--baseline", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    from v2.scanner.detectors import ALL_DETECTORS
    from v2.data.client import DataClient  # type: ignore[import]

    detector_map = {c().name: c for c in ALL_DETECTORS}
    if args.detector not in detector_map:
        raise SystemExit(f"Unknown detector '{args.detector}'. Available: {list(detector_map)}")

    det = detector_map[args.detector]()
    print(f"[cli] detector={det.name} tickers={args.tickers} horizon={args.horizon}")
    # Live data fetch would go here — intentionally stubbed.
    print("[cli] Live run not yet implemented.")
