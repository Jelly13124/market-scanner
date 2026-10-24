"""Volume-confirmation measurement for the ``intraday_move`` detector.

MEASUREMENT ONLY — this changes no production code. The scanner's most useful
detector, ``intraday_move``, is price-only: it never looks at volume. The open
question is whether an intraday_move fire that lands ON HIGH VOLUME predicts a
bigger forward move than one on low volume. If it does, a future volume gate
would be worth building; if it doesn't, the detector stays as-is.

How we measure it (reusing the existing, tested eval harness):

  * Replay ``detector.detect(ticker, asof, fd)`` over a regime's trading days
    through :class:`CachedAsOfClient` with ``set_asof(asof)`` — the detector is
    blind to the future (no lookahead).
  * For each FIRED ``(ticker, asof)`` compute the fire bar's volume z-score from
    the trailing 20 bars UP TO (and excluding) the fire bar — the fire day's own
    volume is known at its close, so a ``<= asof`` window has no lookahead — and
    bucket the fire into ``high_vol`` (vol_z >= threshold) vs ``low_vol``.
  * Compute each fire's forward return from the ticker's FULL (UNCLAMPED) price
    list — at eval time the future is known (this is a backtest), exactly the
    "clamp for the decision, unclamped for the outcome" rule the rest of the
    harness follows.
  * Build the SAME seeded random per-ticker baseline as
    :func:`score_detector`, then call :func:`evaluate_detector` once per bucket
    (high vs baseline, low vs baseline) to get each bucket's interestingness
    vs random.

Output: one row per (regime, horizon, bucket) →
``scanner_eval/volume_confirm.csv``.

THE VOLUME-Z FORMULA is copied verbatim from
:class:`~v2.scanner.detectors.volume_anomaly.VolumeAnomalyDetector`: trailing
``window=20`` bars, ``vol_mean = mean(trailing)``,
``vol_std = max(std(trailing, ddof=1), vol_mean * 0.10)`` (a 10%-of-mean std
floor — NOT ``or 1e-6``), ``vol_z = (today_vol - vol_mean) / vol_std``.
"""

from __future__ import annotations

import csv
import logging
import random

import numpy as np

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
#: Trailing window for the volume z-score (matches VolumeAnomalyDetector).
VOLUME_WINDOW = 20
#: A fire is "high volume" when its volume z-score is >= this threshold.
DEFAULT_VOL_THRESHOLD = 1.0


# ---------------------------------------------------------------------------
# Volume z-score (no-lookahead: trailing window is strictly before the fire bar)
# ---------------------------------------------------------------------------


def volume_z(prices, asof_idx: int, window: int = VOLUME_WINDOW) -> float | None:
    """Volume z-score of bar ``asof_idx`` vs the trailing ``window`` bars.

    ``prices`` is the full ascending series (a list of ``Price`` bars OR a list
    of raw volume floats). ``asof_idx`` is the index of the fire bar. The
    trailing window is ``volumes[asof_idx-window : asof_idx]`` (strictly BEFORE
    the fire bar) and the day's own volume is ``volumes[asof_idx]`` — the fire
    day's volume is known at its close, so this is lookahead-free.

    Std floor is 10% of the trailing mean (copied from VolumeAnomalyDetector);
    when std collapses to 0 (identical trailing volumes) the floor prevents a
    divide-by-zero. Returns ``None`` when there are fewer than ``window``
    trailing bars, or the trailing mean is non-positive.
    """
    if asof_idx < window or asof_idx >= len(prices):
        return None
    volumes = [_volume_of(p) for p in prices]
    today_vol = volumes[asof_idx]
    trailing = volumes[asof_idx - window : asof_idx]
    if len(trailing) < window:
        return None
    arr = np.asarray(trailing, dtype=float)
    vol_mean = float(arr.mean())
    if vol_mean <= 0:
        return None
    vol_std = max(float(arr.std(ddof=1)), vol_mean * 0.10)
    return (today_vol - vol_mean) / vol_std


def _volume_of(p) -> float:
    """Volume of a ``Price`` bar, or the value itself when ``prices`` is raw floats."""
    v = getattr(p, "volume", p)
    return float(v)


# ---------------------------------------------------------------------------
# run_volume_confirm — one detector x one regime
# ---------------------------------------------------------------------------


def run_volume_confirm(
    detector,
    bundles_by_ticker,
    spy_prices,
    regime,
    *,
    vol_threshold: float = DEFAULT_VOL_THRESHOLD,
    horizons=HORIZONS,
    window: int = VOLUME_WINDOW,
    baseline_per_ticker: int = BASELINE_PER_TICKER,
    rng_seed: int = 0,
) -> dict:
    """Split ``detector``'s fires over ``regime`` by volume and measure each
    bucket's interestingness vs a seeded random baseline.

    Returns ``{horizon_int: {"high_vol": {...}, "low_vol": {...},
    "vol_threshold": float}}`` where each bucket dict carries ``n``,
    ``interestingness_diff``, ``interestingness_t`` and ``abs_mean_fired``.

    The detector is replayed through :class:`CachedAsOfClient` (no lookahead);
    each fire's vol-z is computed from bars ``<= asof`` and its forward return
    from the UNCLAMPED full series. The random baseline mirrors
    :func:`score_detector` exactly (same per-ticker sampling, same seed) so the
    two buckets are compared against the identical reference distribution.
    """
    rng = random.Random(rng_seed)

    # Per-horizon, per-bucket SIGNED forward returns of fired events, plus the
    # shared signed baseline (evaluate_detector takes signed inputs and derives
    # the abs/interestingness internally).
    fired_signed = {h: {"high_vol": [], "low_vol": []} for h in horizons}
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
            try:
                client.set_asof(asof)
                trig = detector.detect(ticker, asof, client)
            except Exception:
                logger.debug("detect raised for %s @ %s", ticker, asof, exc_info=True)
                continue
            if trig is None or not trig.triggered:
                continue
            i = didx.get(asof)
            if i is None:
                continue
            vz = volume_z(prices, i, window)
            if vz is None:
                continue  # not enough trailing volume history to classify
            bucket = "high_vol" if vz >= vol_threshold else "low_vol"
            for h in horizons:
                r = forward_return(closes, i, h)  # UNCLAMPED ticker fwd return
                if r is not None:
                    fired_signed[h][bucket].append(r)

        # Seeded random baseline for this ticker — identical to score_detector:
        # sample valid as-of indices within the regime window and take their
        # forward returns.
        win_idxs = [didx[d] for d in asof_days if didx.get(d) is not None]
        valid = [i for i in win_idxs if forward_return(closes, i, max(horizons)) is not None]
        if valid:
            k = min(baseline_per_ticker, len(valid))
            for i in rng.sample(valid, k):
                for h in horizons:
                    r = forward_return(closes, i, h)
                    if r is not None:
                        baseline_signed[h].append(r)

    out: dict = {}
    for h in horizons:
        per_bucket: dict = {"vol_threshold": float(vol_threshold)}
        for bucket in ("high_vol", "low_vol"):
            ev = evaluate_detector(
                fire_returns=fired_signed[h][bucket],
                baseline_returns=baseline_signed[h],
                horizon=h,
            )
            per_bucket[bucket] = {
                "n": ev["n_fired"],
                "interestingness_diff": ev["interestingness_diff"],
                "interestingness_t": ev["interestingness_t"],
                "abs_mean_fired": ev["abs_mean_fired"],
            }
        out[h] = per_bucket
    return out


def _closes(prices) -> list[float | None]:
    """Adjusted-close-preferred closes, one per bar (``None`` where unusable)."""
    return [close_of(p) for p in prices]


# ---------------------------------------------------------------------------
# run_all — flat rows over regimes x horizons x bucket
# ---------------------------------------------------------------------------


def run_all(detector, bundles_by_ticker, spy_prices, regimes, **kw) -> list[dict]:
    """Flat list of CSV-ready rows over (regime x horizon x bucket).

    Each regime is wrapped in its own try/except: a failure on one regime logs
    and is skipped, so it can't lose the rows already gathered for the others.
    """
    rows: list[dict] = []
    for regime in regimes:
        try:
            per_h = run_volume_confirm(detector, bundles_by_ticker, spy_prices, regime, **kw)
        except Exception:
            logger.exception(
                "run_volume_confirm failed for regime=%s — skipping",
                getattr(regime, "name", regime),
            )
            continue
        for h, per_bucket in per_h.items():
            for bucket in ("high_vol", "low_vol"):
                b = per_bucket[bucket]
                rows.append(
                    {
                        "detector": detector.name,
                        "regime": regime.name,
                        "regime_label": regime.label,
                        "horizon": f"{h}d",
                        "bucket": bucket,
                        "vol_threshold": per_bucket["vol_threshold"],
                        "n": b["n"],
                        "interestingness_diff": b["interestingness_diff"],
                        "interestingness_t": b["interestingness_t"],
                        "abs_mean_fired": b["abs_mean_fired"],
                    }
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
    "bucket",
    "vol_threshold",
    "n",
    "interestingness_diff",
    "interestingness_t",
    "abs_mean_fired",
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
    """Run the volume-confirmation measurement on the real IntradayMoveDetector.

    Reuses the exact data setup of the existing eval scripts: the
    ``rerender_eval_report.REGIMES`` windows, the first 80 ``nasdaq100_sp500``
    tickers, a one-shot price prefetch per ticker via
    :func:`prefetch_price_bundles`, and SPY over the same wide span. Writes
    ``scanner_eval/volume_confirm.csv`` and logs a per-(regime, horizon) summary.
    """
    import logging as _logging
    from pathlib import Path

    from dotenv import load_dotenv

    from v2.data.factory import get_provider_factory
    from v2.scanner.detectors import IntradayMoveDetector
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
        "volume_confirm: %d tickers, span=%s..%s, regimes=%d",
        len(tickers),
        span_start,
        span_end,
        len(REGIMES),
    )

    bundles = prefetch_price_bundles(tickers, factory, span_start, span_end)
    spy_prices = fetch_spy(factory, span_start, span_end)

    detector = IntradayMoveDetector()
    rows = run_all(detector, bundles, spy_prices, REGIMES)

    out_csv = out_dir / "volume_confirm.csv"
    write_csv(rows, out_csv)
    logger.info("volume_confirm: wrote %d rows to %s", len(rows), out_csv)

    for r in rows:
        logger.info(
            "  %s %s %-8s n=%-4d interest_diff=%+.4f t=%+.2f abs_mean=%.4f",
            r["regime"],
            r["horizon"],
            r["bucket"],
            r["n"],
            r["interestingness_diff"],
            r["interestingness_t"],
            r["abs_mean_fired"],
        )


if __name__ == "__main__":
    main()
