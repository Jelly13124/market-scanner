"""Per-detector x regime scorecard driver for the scanner-evaluation harness.

We score each detector's usefulness by replaying it over a regime's trading
days and measuring two things on the stocks it FIRES on:

  * **interestingness** — do fired stocks move MORE (|fwd return|) than a random
    baseline drawn from the same ticker/window? A screener earns its LLM-budget
    cost only if it concentrates attention on bars that actually move.
  * **direction-adjusted alpha** — does the predicted direction pay vs SPY? A
    bearish call that dropped is positive dir-alpha (a short that worked).

THE CRITICAL CORRECTNESS RULE
-----------------------------
**Clamp for the DECISION, but use the UNCLAMPED full series for the OUTCOME.**
The detector must be blind to the future, so it is called through
:class:`CachedAsOfClient` with ``set_asof(asof)`` — every read it does is
clamped to ``<= asof``. But the forward return that measures what happened
AFTER the fire is computed from the ticker's FULL price list: at eval time the
future IS known (this is a backtest). Computing forward returns through the
as-of-clamped client would return ``None`` for every future bar and silently
zero out every score.

Output: one row per (detector, regime, horizon). ``HORIZONS = (5, 20)`` →
two rows per (detector, regime).
"""

from __future__ import annotations

import csv
import logging
import math
import random

import numpy as np

from v2.backtesting.forward_returns import direction_adjust
from v2.scanner.detectors.base import close_of
from v2.scanner.eval.cached_asof_client import CachedAsOfClient
from v2.scanner.eval.detector_ab import evaluate_detector, forward_return

logger = logging.getLogger(__name__)

#: Forward-return horizons (trading-day offsets on the ticker's own bars).
HORIZONS = (5, 20)
#: How many random as-of bars to sample per ticker for the interestingness baseline.
BASELINE_PER_TICKER = 20


# ---------------------------------------------------------------------------
# Price-series helpers
# ---------------------------------------------------------------------------


def _date_index(prices) -> dict[str, int]:
    """Map ``YYYY-MM-DD`` -> index in the (ascending) price list.

    Last-write-wins on duplicate dates, which keeps the index pointing at the
    final bar for a day — consistent with the ascending ordering the rest of
    the harness assumes.
    """
    return {(p.time or "")[:10]: i for i, p in enumerate(prices)}


def _closes(prices) -> list[float | None]:
    """Adjusted-close-preferred closes, one per bar (``None`` where unusable)."""
    return [close_of(p) for p in prices]


def _trading_days_in(prices, start: str, end: str) -> list[str]:
    """Sorted ``YYYY-MM-DD`` strings of bars within the inclusive ``[start, end]``."""
    days = []
    for p in prices:
        day = (p.time or "")[:10]
        if start <= day <= end:
            days.append(day)
    days.sort()
    return days


# ---------------------------------------------------------------------------
# score_detector
# ---------------------------------------------------------------------------


def score_detector(
    detector,
    regime,
    bundles_by_ticker,
    spy_prices,
    *,
    horizons=HORIZONS,
    baseline_per_ticker=BASELINE_PER_TICKER,
    rng_seed=0,
) -> list[dict]:
    """One detector over one regime across the universe → one row per horizon.

    For each ticker:
      * replay ``detector.detect(ticker, asof, client)`` over the regime's
        trading days, with the client clamped to each ``asof`` (no lookahead);
      * for every FIRED bar, accumulate the UNCLAMPED forward return (signed,
        for interestingness) and the direction-adjusted alpha vs SPY;
      * draw a random per-ticker baseline of forward returns for the
        interestingness comparison.

    Coverage = fraction of tickers on which the detector ran cleanly at least
    once (returned a non-``None`` verdict). Empty-price tickers and tickers the
    detector only ever returned ``None`` on do NOT count toward coverage.
    """
    rng = random.Random(rng_seed)
    spy_closes = _closes(spy_prices)
    spy_idx = _date_index(spy_prices)

    # per-horizon accumulators
    fired_signed = {h: [] for h in horizons}     # signed fwd returns of fired events
    baseline_signed = {h: [] for h in horizons}  # signed fwd returns of random baseline
    fired_dir_alpha = {h: [] for h in horizons}  # direction-adjusted alpha of fired events
    n_tickers = 0
    n_tickers_with_data = 0

    for ticker, bundle in bundles_by_ticker.items():
        prices = bundle.prices
        if not prices:
            n_tickers += 1
            continue
        n_tickers += 1
        closes = _closes(prices)
        didx = _date_index(prices)
        asof_days = _trading_days_in(prices, regime.start, regime.end)
        if not asof_days:
            continue
        client = CachedAsOfClient(bundle)
        ran_clean = False
        for asof in asof_days:
            try:
                client.set_asof(asof)
                trig = detector.detect(ticker, asof, client)
            except Exception:
                logger.debug("detect raised for %s @ %s", ticker, asof, exc_info=True)
                continue
            if trig is None:
                continue  # no data — doesn't count toward coverage unless it ran elsewhere
            ran_clean = True
            if not trig.triggered:
                continue
            i = didx.get(asof)
            if i is None:
                continue
            for h in horizons:
                r = forward_return(closes, i, h)  # ticker fwd (UNCLAMPED)
                if r is None:
                    continue
                fired_signed[h].append(r)
                # alpha vs SPY over the same window
                si = spy_idx.get(asof)
                sr = forward_return(spy_closes, si, h) if si is not None else None
                alpha = (r - sr) if sr is not None else None
                da = direction_adjust(alpha, trig.direction)
                if da is not None:
                    fired_dir_alpha[h].append(da)
        if ran_clean:
            n_tickers_with_data += 1
        # random baseline for this ticker: sample as-of indices within the window
        win_idxs = [didx[d] for d in asof_days if didx.get(d) is not None]
        valid = [i for i in win_idxs if forward_return(closes, i, max(horizons)) is not None]
        if valid:
            k = min(baseline_per_ticker, len(valid))
            for i in rng.sample(valid, k):
                for h in horizons:
                    r = forward_return(closes, i, h)
                    if r is not None:
                        baseline_signed[h].append(r)

    coverage = (n_tickers_with_data / n_tickers) if n_tickers else 0.0
    rows = []
    for h in horizons:
        ev = evaluate_detector(
            fire_returns=fired_signed[h],
            baseline_returns=baseline_signed[h],
            horizon=h,
        )
        da = fired_dir_alpha[h]
        dir_alpha_mean = float(np.mean(da)) if da else 0.0
        dir_alpha_t = 0.0
        if len(da) >= 2:
            sd = float(np.std(da, ddof=1))
            if sd > 0:
                dir_alpha_t = dir_alpha_mean / (sd / math.sqrt(len(da)))
        rows.append(
            {
                "detector": detector.name,
                "regime": regime.name,
                "regime_label": regime.label,
                "horizon": f"{h}d",
                "n_fired": ev["n_fired"],
                "coverage": round(coverage, 3),
                "interestingness_diff": ev["interestingness_diff"],
                "interestingness_t": ev["interestingness_t"],
                "abs_mean_fired": ev["abs_mean_fired"],
                "abs_mean_baseline": ev["abs_mean_baseline"],
                "signed_mean_fired": ev["mean_fwd_return"],
                "dir_alpha_mean": dir_alpha_mean,
                "dir_alpha_t": dir_alpha_t,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# score_all_detectors
# ---------------------------------------------------------------------------


def score_all_detectors(
    detectors,
    regimes,
    bundles_by_ticker,
    spy_prices,
    **kw,
) -> list[dict]:
    """Flat list of scorecard rows over (detector x regime).

    Each (detector, regime) pair yields ``len(horizons)`` rows. A failure in one
    ``score_detector`` call is logged and skipped — it appends nothing and never
    aborts the rest of the sweep, so one broken detector can't lose the report.
    """
    rows: list[dict] = []
    for detector in detectors:
        for regime in regimes:
            try:
                rows.extend(
                    score_detector(detector, regime, bundles_by_ticker, spy_prices, **kw)
                )
            except Exception:
                logger.exception(
                    "score_detector failed for detector=%s regime=%s — skipping",
                    getattr(detector, "name", detector),
                    getattr(regime, "name", regime),
                )
    return rows


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = (
    "detector",
    "regime",
    "regime_label",
    "horizon",
    "n_fired",
    "coverage",
    "interestingness_diff",
    "interestingness_t",
    "abs_mean_fired",
    "abs_mean_baseline",
    "signed_mean_fired",
    "dir_alpha_mean",
    "dir_alpha_t",
)


def write_detectors_csv(rows, path) -> None:
    """Write scorecard rows to ``path`` as CSV with the :data:`CSV_COLUMNS` header."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
