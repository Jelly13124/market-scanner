"""Per-signal x regime cross-sectional rank-IC study for the eval harness.

Quant signals (momentum, value, quality, earnings_quality, technical) are
point-in-time cross-sectional factors. The right usefulness measure is the
**Information Coefficient (IC)**: at each rebalance date, rank-correlate the
factor value across the universe with the forward return. A positive *mean* IC
means the factor sorts winners from losers; ~0 means it's noise; negative means
it's inverted. We segment by regime.

THE CRITICAL CORRECTNESS RULE
-----------------------------
**Clamp for the factor value, but use the UNCLAMPED full series for the return.**
The factor must be blind to the future, so it is computed through
:class:`CachedAsOfClient` with ``set_asof(asof)`` — every read it does is clamped
to ``<= asof``. But the forward return that measures what happened AFTER the
rebalance is read from the ticker's FULL price list: at eval time the future IS
known (this is a backtest). Computing the forward return through the clamped
client would return ``None`` for every future bar and silently void every IC.

DATA-LIMITED via usable coverage
--------------------------------
A signal returns the data-missing sentinel (``value=0.0`` + a ``"reason"`` in
``metadata``) when it has no historical fundamentals to work with. Those results
are excluded from the cross-section. ``coverage`` (mean usable-ticker fraction
across rebalance dates) is how a signal reads as DATA-LIMITED: a value/quality
signal with no point-in-time fundamentals collapses to ``coverage == 0.0`` and
``n_dates == 0`` rather than producing a spurious IC.

Output: one row per (signal, regime, horizon). ``HORIZONS = (5, 20)`` → two rows
per (signal, regime).
"""

from __future__ import annotations

import csv
import logging
import math

import numpy as np
import pandas as pd

from v2.scanner.eval.cached_asof_client import CachedAsOfClient
from v2.scanner.eval.detector_ab import forward_return
from v2.scanner.eval.detector_scorecard import _closes, _date_index, _trading_days_in

logger = logging.getLogger(__name__)

#: Forward-return horizons (trading-day offsets on the ticker's own bars).
HORIZONS = (5, 20)
#: Trading days between rebalance dates (≈ weekly).
REBALANCE_EVERY = 5
#: Need at least this many usable tickers to compute an IC at a given date.
MIN_CROSS_SECTION = 5


# ---------------------------------------------------------------------------
# Usability + rebalance helpers
# ---------------------------------------------------------------------------


def _is_usable(result) -> bool:
    """True unless *result* is the data-missing sentinel (value 0.0 + a reason).

    The signal convention is to return ``value=0.0`` with a ``metadata["reason"]``
    when it has no/insufficient data. Such a result is NOT a real factor reading
    and must be excluded from the cross-section.
    """
    md = getattr(result, "metadata", None) or {}
    return not (float(getattr(result, "value", 0.0)) == 0.0 and "reason" in md)


def _rebalance_dates(all_days: list[str], every: int) -> list[str]:
    """Every ``every``-th trading day (≈ weekly when ``every == 5``)."""
    return all_days[::every]


def _union_trading_days(bundles_by_ticker, start: str, end: str) -> list[str]:
    """Sorted union of all tickers' trading days within the inclusive window."""
    days: set[str] = set()
    for bundle in bundles_by_ticker.values():
        days.update(_trading_days_in(bundle.prices, start, end))
    return sorted(days)


# ---------------------------------------------------------------------------
# score_signal
# ---------------------------------------------------------------------------


def score_signal(
    signal,
    regime,
    bundles_by_ticker,
    *,
    horizons=HORIZONS,
    rebalance_every=REBALANCE_EVERY,
) -> list[dict]:
    """One signal over one regime across the universe → one row per horizon.

    At each weekly rebalance date we build the cross-section: for each ticker,
    clamp the client to that date and compute the factor value (no lookahead).
    Keep only tickers whose result is usable AND that have a non-``None``
    UNCLAMPED forward return at the horizon. With ``>= MIN_CROSS_SECTION`` such
    pairs we Spearman-correlate value-vs-return to get that date's IC.

    Aggregated per horizon:
      * ``mean_ic``  — mean of per-date ICs (NaN dates skipped),
      * ``ic_t``     — ``mean_ic / std(ic, ddof=1) * sqrt(n_dates)`` (0 if < 2 dates),
      * ``n_dates``  — number of dates that yielded a valid IC,
      * ``coverage`` — mean over rebalance dates of usable / bar-having tickers.
    """
    # Per-ticker price scaffolding (closes + date->index), built once.
    closes_by_ticker: dict[str, list] = {}
    didx_by_ticker: dict[str, dict] = {}
    for ticker, bundle in bundles_by_ticker.items():
        closes_by_ticker[ticker] = _closes(bundle.prices)
        didx_by_ticker[ticker] = _date_index(bundle.prices)

    all_days = _union_trading_days(bundles_by_ticker, regime.start, regime.end)
    rebal_dates = _rebalance_dates(all_days, rebalance_every)

    # Reuse one as-of client per ticker across all dates (cheap, just re-clamps).
    clients = {t: CachedAsOfClient(b) for t, b in bundles_by_ticker.items()}

    ics_by_h: dict[int, list[float]] = {h: [] for h in horizons}
    # Coverage is horizon-independent: it counts usable factor values among the
    # tickers that HAVE a bar on the rebalance date. Tracked once per date.
    coverage_fracs: list[float] = []

    for date_iso in rebal_dates:
        # values usable for the cross-section, keyed by ticker (factor value only)
        usable_values: dict[str, float] = {}
        n_with_bar = 0
        for ticker, bundle in bundles_by_ticker.items():
            didx = didx_by_ticker[ticker]
            if date_iso not in didx:
                continue  # ticker had no bar this day — not in the denominator
            n_with_bar += 1
            client = clients[ticker]
            client.set_asof(date_iso)
            try:
                result = signal.compute(ticker, date_iso, client)
            except Exception:
                # Signals must never raise; treat a rogue raise as missing data.
                logger.debug(
                    "signal %s raised for %s @ %s",
                    getattr(signal, "name", signal),
                    ticker,
                    date_iso,
                    exc_info=True,
                )
                continue
            if _is_usable(result):
                usable_values[ticker] = float(result.value)

        if n_with_bar:
            coverage_fracs.append(len(usable_values) / n_with_bar)

        # Per-horizon cross-section: need both a usable value and a fwd return.
        for h in horizons:
            vals: list[float] = []
            rets: list[float] = []
            for ticker, v in usable_values.items():
                i = didx_by_ticker[ticker].get(date_iso)
                if i is None:
                    continue
                r = forward_return(closes_by_ticker[ticker], i, h)  # UNCLAMPED
                if r is None:
                    continue
                vals.append(v)
                rets.append(r)
            if len(vals) >= MIN_CROSS_SECTION:
                ic = pd.Series(vals).corr(pd.Series(rets), method="spearman")
                if ic is not None and not math.isnan(ic):
                    ics_by_h[h].append(float(ic))

    coverage = float(np.mean(coverage_fracs)) if coverage_fracs else 0.0

    rows = []
    for h in horizons:
        ics = ics_by_h[h]
        n_dates = len(ics)
        mean_ic = float(np.mean(ics)) if ics else 0.0
        ic_t = 0.0
        if n_dates >= 2:
            sd = float(np.std(ics, ddof=1))
            if sd > 0:
                ic_t = mean_ic / sd * math.sqrt(n_dates)
        rows.append(
            {
                "signal": signal.name,
                "regime": regime.name,
                "regime_label": regime.label,
                "horizon": h,
                "mean_ic": mean_ic,
                "ic_t": ic_t,
                "n_dates": n_dates,
                "coverage": round(coverage, 3),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# score_all_signals
# ---------------------------------------------------------------------------


def score_all_signals(signals, regimes, bundles_by_ticker, **kw) -> list[dict]:
    """Flat list of IC rows over (signal x regime).

    Each (signal, regime) pair yields ``len(horizons)`` rows. A failure in one
    ``score_signal`` call is logged and skipped — it appends nothing and never
    aborts the rest of the sweep, so one broken signal can't lose the report.
    """
    rows: list[dict] = []
    for signal in signals:
        for regime in regimes:
            try:
                rows.extend(score_signal(signal, regime, bundles_by_ticker, **kw))
            except Exception:
                logger.exception(
                    "score_signal failed for signal=%s regime=%s — skipping",
                    getattr(signal, "name", signal),
                    getattr(regime, "name", regime),
                )
    return rows


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = (
    "signal",
    "regime",
    "regime_label",
    "horizon",
    "mean_ic",
    "ic_t",
    "n_dates",
    "coverage",
)


def write_signals_csv(rows, path) -> None:
    """Write IC rows to ``path`` as CSV with the :data:`CSV_COLUMNS` header."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
