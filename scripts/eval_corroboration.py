"""Corroboration measurement — does multi-detector CO-FIRE predict a bigger move?

MEASUREMENT ONLY — this changes no production code (no scoring change). Tonight's
finding: individually 12/13 detectors look weak, yet the detector COMBINATION
(Top-N composite) beat SPY in all three regimes. The hypothesis under test here is
**corroboration**: when >=2 detectors fire on the SAME (ticker, day), the forward
move is bigger than a single-detector fire (and bigger than a random pick).

How we measure it (reusing the existing, tested eval harness):

  * Replay ALL ``detectors`` over a regime's trading days through
    :class:`CachedAsOfClient` with ``set_asof(asof)`` — every detector is blind to
    the future (no lookahead). Collect the EventTriggers that actually fired.
  * If >=1 fired, the (ticker, asof) is an EVENT. Bucket it by how many fired:
    ``'1'`` / ``'2'`` / ``'3+'``. Give it a NET direction (bullish vs bearish
    majority across the firing detectors) and a same-direction flag (every firing
    detector agreed on sign).
  * Compute each event's forward return from the ticker's FULL (UNCLAMPED) price
    list — at eval time the future is known (this is a backtest), exactly the
    "clamp for the DECISION, unclamped for the OUTCOME" rule the rest of the
    harness follows. Direction-adjusted alpha uses the NET direction vs SPY.
  * Build the SAME seeded random per-ticker baseline as :func:`score_detector`,
    then call :func:`evaluate_detector` once per bucket to get its interestingness
    vs random. Additionally split the 2+ events into same-direction vs mixed-
    direction and measure each, and report a one-sample dir-alpha mean + t per
    bucket.

Output: one row per (regime, horizon, bucket) — buckets ``'1' / '2' / '3+'`` plus
``'2+_samedir' / '2+_mixeddir'`` — to ``scanner_eval/corroboration.csv``.
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
from v2.scanner.eval.detector_scorecard import (
    BASELINE_PER_TICKER,
    _date_index,
    _trading_days_in,
)

logger = logging.getLogger(__name__)

#: Forward-return horizons (trading-day offsets on the ticker's own bars).
HORIZONS = (5, 20)

#: The n_triggered buckets reported as plain rows, plus the same/mixed split of 2+.
_BUCKETS = ("1", "2", "3+")
_SPLIT_BUCKETS = ("2+_samedir", "2+_mixeddir")


# ---------------------------------------------------------------------------
# Net direction across the firing detectors
# ---------------------------------------------------------------------------


def _net_direction(triggered) -> tuple[str, int]:
    """Net direction of a set of firing EventTriggers + the same-direction count.

    ``triggered`` is the list of EventTriggers that fired (``triggered=True``).
    Count bullish vs bearish (neutrals don't vote on sign). The net direction is
    the majority; ties (incl. all-neutral) → ``"neutral"``. ``same_dir_count`` is
    ``max(n_bull, n_bear)`` — the size of the largest agreeing camp. When it
    equals ``len(triggered)`` every firing detector agreed on sign.
    """
    n_bull = sum(1 for t in triggered if t.direction == "bullish")
    n_bear = sum(1 for t in triggered if t.direction == "bearish")
    if n_bull > n_bear:
        direction = "bullish"
    elif n_bear > n_bull:
        direction = "bearish"
    else:
        direction = "neutral"
    return direction, max(n_bull, n_bear)


def _bucket_for(n_triggered: int) -> str:
    """Map a fired-count to its bucket label (``'1' / '2' / '3+'``)."""
    if n_triggered == 1:
        return "1"
    if n_triggered == 2:
        return "2"
    return "3+"


def _closes(prices) -> list[float | None]:
    """Adjusted-close-preferred closes, one per bar (``None`` where unusable)."""
    return [close_of(p) for p in prices]


def _one_sample_t(values: list[float]) -> tuple[float, float]:
    """One-sample (mean, t-stat vs 0) of ``values``; ``(0,0)`` when n < 2 or sd==0."""
    if not values:
        return 0.0, 0.0
    mean = float(np.mean(values))
    if len(values) < 2:
        return mean, 0.0
    sd = float(np.std(values, ddof=1))
    if sd <= 0:
        return mean, 0.0
    return mean, mean / (sd / math.sqrt(len(values)))


# ---------------------------------------------------------------------------
# run_corroboration — ALL detectors x one regime
# ---------------------------------------------------------------------------


def run_corroboration(
    detectors,
    bundles_by_ticker,
    spy_prices,
    regime,
    *,
    horizons=HORIZONS,
    baseline_per_ticker: int = BASELINE_PER_TICKER,
    rng_seed: int = 0,
) -> list[dict]:
    """Bucket each (ticker, asof) EVENT by how many detectors co-fired and measure
    each bucket's interestingness vs a seeded random baseline.

    For every (ticker, asof) in ``regime``: build ONE :class:`CachedAsOfClient`,
    ``set_asof(asof)``, run ALL ``detectors`` (no lookahead), and collect the
    EventTriggers that fired. If >=1 fired the bar is an EVENT with a bucket by
    ``n_triggered`` (``'1' / '2' / '3+'``), a NET direction, and a same-direction
    flag. Its forward return is read from the UNCLAMPED full series and its
    direction-adjusted alpha (net direction vs SPY) is recorded.

    The random baseline mirrors :func:`score_detector` exactly (same per-ticker
    sampling, same seed) so every bucket is compared against one shared reference
    distribution. The 2+ events are additionally split into same-direction vs
    mixed-direction. Returns one row per (regime, horizon, bucket) for the three
    count buckets plus the two 2+ split buckets, each carrying ``n``,
    ``interestingness_diff``, ``interestingness_t``, ``dir_alpha_mean`` and
    ``dir_alpha_t``.
    """
    rng = random.Random(rng_seed)
    spy_closes = _closes(spy_prices)
    spy_idx = _date_index(spy_prices)

    # Per-horizon SIGNED forward returns + dir-alpha, keyed by bucket. The split
    # buckets ('2+_samedir' / '2+_mixeddir') get their own keys alongside.
    all_keys = _BUCKETS + _SPLIT_BUCKETS
    fired_signed = {h: {k: [] for k in all_keys} for h in horizons}
    fired_dir_alpha = {h: {k: [] for k in all_keys} for h in horizons}
    baseline_signed = {h: [] for h in horizons}

    for ticker, bundle in bundles_by_ticker.items():
        prices = bundle.prices
        if not prices:
            continue
        closes = _closes(prices)
        didx = _date_index(prices)
        asof_days = _trading_days_in(prices, regime.start, regime.end)
        if not asof_days:
            continue

        client = CachedAsOfClient(bundle)
        for asof in asof_days:
            triggered: list = []
            for det in detectors:
                try:
                    client.set_asof(asof)
                    trig = det.detect(ticker, asof, client)
                except Exception:
                    logger.debug(
                        "detect raised for %s @ %s (det=%s)",
                        ticker,
                        asof,
                        getattr(det, "name", det),
                        exc_info=True,
                    )
                    continue
                if trig is not None and trig.triggered:
                    triggered.append(trig)

            n_trig = len(triggered)
            if n_trig == 0:
                continue  # not an event
            i = didx.get(asof)
            if i is None:
                continue
            bucket = _bucket_for(n_trig)
            net_dir, same_dir_count = _net_direction(triggered)
            same_dir = same_dir_count == n_trig
            for h in horizons:
                r = forward_return(closes, i, h)  # UNCLAMPED ticker fwd return
                if r is None:
                    continue
                fired_signed[h][bucket].append(r)
                # dir-alpha vs SPY over the same window, using the NET direction.
                si = spy_idx.get(asof)
                sr = forward_return(spy_closes, si, h) if si is not None else None
                alpha = (r - sr) if sr is not None else None
                da = direction_adjust(alpha, net_dir)
                if da is not None:
                    fired_dir_alpha[h][bucket].append(da)
                # 2+ same/mixed split (n_triggered >= 2).
                if n_trig >= 2:
                    split = "2+_samedir" if same_dir else "2+_mixeddir"
                    fired_signed[h][split].append(r)
                    if da is not None:
                        fired_dir_alpha[h][split].append(da)

        # Seeded random baseline for this ticker — identical to score_detector:
        # sample valid as-of indices within the regime window, take their fwd rets.
        win_idxs = [didx[d] for d in asof_days if didx.get(d) is not None]
        valid = [i for i in win_idxs if forward_return(closes, i, max(horizons)) is not None]
        if valid:
            k = min(baseline_per_ticker, len(valid))
            for i in rng.sample(valid, k):
                for h in horizons:
                    r = forward_return(closes, i, h)
                    if r is not None:
                        baseline_signed[h].append(r)

    rows: list[dict] = []
    for h in horizons:
        for bucket in all_keys:
            ev = evaluate_detector(
                fire_returns=fired_signed[h][bucket],
                baseline_returns=baseline_signed[h],
                horizon=h,
            )
            dir_alpha_mean, dir_alpha_t = _one_sample_t(fired_dir_alpha[h][bucket])
            rows.append(
                {
                    "regime": regime.name,
                    "regime_label": regime.label,
                    "horizon": f"{h}d",
                    "bucket": bucket,
                    "n": ev["n_fired"],
                    "interestingness_diff": ev["interestingness_diff"],
                    "interestingness_t": ev["interestingness_t"],
                    "dir_alpha_mean": dir_alpha_mean,
                    "dir_alpha_t": dir_alpha_t,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# run_all — flat rows over regimes
# ---------------------------------------------------------------------------


def run_all(detectors, bundles_by_ticker, spy_prices, regimes, **kw) -> list[dict]:
    """Flat list of CSV-ready rows over (regime x horizon x bucket).

    Each regime is wrapped in its own try/except: a failure on one regime logs
    and is skipped, so it can't lose the rows already gathered for the others.
    """
    rows: list[dict] = []
    for regime in regimes:
        try:
            rows.extend(
                run_corroboration(detectors, bundles_by_ticker, spy_prices, regime, **kw)
            )
        except Exception:
            logger.exception(
                "run_corroboration failed for regime=%s — skipping",
                getattr(regime, "name", regime),
            )
    return rows


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = (
    "regime",
    "regime_label",
    "horizon",
    "bucket",
    "n",
    "interestingness_diff",
    "interestingness_t",
    "dir_alpha_mean",
    "dir_alpha_t",
)


def write_csv(rows, path) -> None:
    """Write measurement rows to ``path`` as CSV with the :data:`CSV_COLUMNS` header."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# main — real-data run (NOT exercised by the offline tests)
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the corroboration measurement on the real registered detectors.

    Reuses the exact data setup of the existing eval scripts: the
    ``rerender_eval_report.REGIMES`` windows, the first 80 ``nasdaq100_sp500``
    tickers, a one-shot price prefetch per ticker via
    :func:`prefetch_price_bundles`, and SPY over the same wide span. Writes
    ``scanner_eval/corroboration.csv`` and logs a per-(regime, horizon) summary.
    """
    import logging as _logging
    from pathlib import Path

    from dotenv import load_dotenv

    from v2.data.factory import get_provider_factory
    from v2.scanner.detectors import ALL_DETECTORS
    from v2.scanner.eval.run_eval import fetch_spy, prefetch_price_bundles
    from v2.scanner.universes import load_universe
    from scripts.rerender_eval_report import REGIMES

    # API keys (EODHD/FINNHUB) live in .env at repo root; load before clients.
    load_dotenv()
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    repo = Path(__file__).resolve().parents[1]
    out_dir = repo / "scanner_eval"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Wide prefetch span covering all REGIMES plus detector lookback + forward.
    span_start = "2020-11-01"
    span_end = "2025-09-30"

    tickers = load_universe("nasdaq100_sp500")[:80]
    factory = get_provider_factory()
    logger.info(
        "corroboration: %d tickers, span=%s..%s, regimes=%d",
        len(tickers),
        span_start,
        span_end,
        len(REGIMES),
    )

    bundles = prefetch_price_bundles(tickers, factory, span_start, span_end)
    spy_prices = fetch_spy(factory, span_start, span_end)

    detectors = [c() for c in ALL_DETECTORS]
    rows = run_all(detectors, bundles, spy_prices, REGIMES)

    out_csv = out_dir / "corroboration.csv"
    write_csv(rows, out_csv)
    logger.info("corroboration: wrote %d rows to %s", len(rows), out_csv)

    for r in rows:
        logger.info(
            "  %s %s %-12s n=%-4d interest_diff=%+.4f t=%+.2f dir_alpha=%+.4f t=%+.2f",
            r["regime"],
            r["horizon"],
            r["bucket"],
            r["n"],
            r["interestingness_diff"],
            r["interestingness_t"],
            r["dir_alpha_mean"],
            r["dir_alpha_t"],
        )


if __name__ == "__main__":
    main()
