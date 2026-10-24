"""Fire-threshold sweep harness — the fire-rate vs interestingness trade-off.

Generic, detector-agnostic MEASUREMENT library. Given a ``make_detector(value)``
factory and a list of threshold values, :func:`sweep_threshold` sweeps the
fire-threshold and, for each setting, measures both the **fire-rate** (fraction
of eligible ticker-days that fire) and the **interestingness** vs a random
baseline (reusing the tested :func:`score_detector`). :func:`pick_knee`
recommends the LOOSEST threshold whose interestingness becomes significant at a
sane fire-rate, or ``None`` to retire the candidate. The scene this addresses: a
detector that fires on a large fraction of ticker-days has a "fired" set ≈ the
whole population, so its interestingness is ≈0 *by construction* — a
mis-calibrated fire threshold, not a useless signal.

The original ``gap``-sweep ``main()`` was REMOVED 2026-06-12 when ``GapDetector``
was deleted; its result is preserved in ``scanner_eval/threshold_sweep_gap.csv``
+ ``findings_scanner_round2.md``. The harness below is detector-agnostic and
tested offline by ``test_eval_threshold_sweep.py`` — re-add a ``main()`` to sweep
any threshold-tunable detector (e.g. ``intraday_move``'s gate thresholds).

THE CRITICAL CORRECTNESS RULE (same as the rest of the harness)
---------------------------------------------------------------
**Clamp for the DECISION, unclamped for the OUTCOME.** The detector is replayed
through :class:`CachedAsOfClient` with ``set_asof(asof)`` so every read it does
is clamped to ``<= asof`` (no lookahead). Forward returns that measure what
happened AFTER a fire are computed from the ticker's FULL price list — at eval
time the future is known (this is a backtest). :func:`score_detector` already
follows this rule; the light fire-rate replay here uses the IDENTICAL clamped
as-of grid, so the fire COUNT is computed under the same no-lookahead discipline.

A detector is "sweepable" iff its constructor exposes a fire-threshold knob.
Wrap that in a ``make_detector(value)`` factory and pass ascending values to
:func:`sweep_threshold`.

Output: :func:`sweep_threshold` returns one row per (value, regime);
:func:`write_csv` stamps a detector name → ``scanner_eval/threshold_sweep_<det>.csv``.
"""

from __future__ import annotations

import csv
import logging

from v2.scanner.eval.cached_asof_client import CachedAsOfClient
from v2.scanner.eval.detector_scorecard import (
    _date_index,
    _trading_days_in,
    score_detector,
)

logger = logging.getLogger(__name__)

#: A discriminating detector should fire on <= 10% of ticker-days. Above this the
#: "fired" set ≈ the population and interestingness is ≈0 by construction.
FIRE_RATE_CAP_DEFAULT = 0.10


# ---------------------------------------------------------------------------
# fire-rate replay (own light pass alongside score_detector, same as-of grid)
# ---------------------------------------------------------------------------


def _fire_rate(detector, regime, bundles_by_ticker) -> tuple[float, int, int]:
    """Replay ``detector`` over ``regime`` and count fires / eligible ticker-days.

    Uses the SAME no-lookahead as-of grid as :func:`score_detector`: for each
    ticker, the regime's trading days are the as-of dates, each served through a
    :class:`CachedAsOfClient` clamped to that date. A ticker-day is **eligible**
    (had enough data) when ``detect`` returns a non-``None`` verdict — exactly the
    ran-clean rule the scorecard uses for coverage. It **fires** when that verdict
    has ``triggered=True``.

    Returns ``(fire_rate, n_fired, n_eligible)`` where
    ``fire_rate = n_fired / n_eligible`` (0.0 when nothing was eligible). The
    detector is isolated per call — a raise is logged and the day skipped (it
    counts as neither eligible nor fired), never aborting the sweep.
    """
    n_fired = 0
    n_eligible = 0
    for ticker, bundle in bundles_by_ticker.items():
        prices = bundle.prices
        if not prices:
            continue
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
            if trig is None:
                continue  # no data — not eligible (mirrors coverage rule)
            if didx.get(asof) is None:
                continue  # belt-and-suspenders: no bar index for this day
            n_eligible += 1
            if trig.triggered:
                n_fired += 1
    fire_rate = (n_fired / n_eligible) if n_eligible else 0.0
    return fire_rate, n_fired, n_eligible


# ---------------------------------------------------------------------------
# sweep_threshold
# ---------------------------------------------------------------------------


def sweep_threshold(
    make_detector,
    values,
    bundles_by_ticker,
    spy_prices,
    regimes,
    *,
    horizon: int = 5,
    rng_seed: int = 0,
) -> list[dict]:
    """Sweep a detector's fire-threshold and measure the fire-rate vs
    interestingness trade-off, one row per (value, regime).

    ``make_detector(value)`` returns a detector instance configured with that
    threshold. For each ``value`` and each ``regime``:

      * :func:`score_detector` is reused (it already computes interestingness vs
        a seeded random baseline + ``n_fired`` + coverage, all no-lookahead) at
        the single ``horizon`` requested;
      * a light :func:`_fire_rate` replay over the IDENTICAL clamped as-of grid
        counts fires / eligible ticker-days.

    Returns rows ``{value, regime, regime_label, fire_rate, interestingness_diff,
    interestingness_t, n_fired}``. ``n_fired`` is taken from the fire-rate replay
    (one count per fired ticker-day) so it is consistent with ``fire_rate``;
    ``score_detector`` accumulates per-horizon and would double-count across
    horizons.
    """
    rows: list[dict] = []
    for value in values:
        for regime in regimes:
            detector = make_detector(value)
            # Interestingness vs random baseline (reuse the tested scorecard) at
            # the single requested horizon.
            sc_rows = score_detector(
                detector,
                regime,
                bundles_by_ticker,
                spy_prices,
                horizons=(horizon,),
                rng_seed=rng_seed,
            )
            sc = sc_rows[0] if sc_rows else {}
            # Light fire-rate replay over the same as-of grid (own pass so the
            # count is one-per-ticker-day, not per-horizon).
            fire_rate, n_fired, _n_elig = _fire_rate(detector, regime, bundles_by_ticker)
            rows.append(
                {
                    "value": value,
                    "regime": regime.name,
                    "regime_label": regime.label,
                    "fire_rate": fire_rate,
                    "interestingness_diff": sc.get("interestingness_diff", 0.0),
                    "interestingness_t": sc.get("interestingness_t", 0.0),
                    "n_fired": n_fired,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# pick_knee
# ---------------------------------------------------------------------------


def pick_knee(
    rows,
    *,
    fire_rate_cap: float = FIRE_RATE_CAP_DEFAULT,
    t_bar: float = 2.0,
    min_regimes: int = 2,
) -> float | None:
    """Pick the recommended fire-threshold from a sweep, or ``None`` to retire it.

    Decision rule — among the swept values, pick the **LOOSEST** (lowest
    threshold) that simultaneously:

      * is significant in ``>= min_regimes`` regimes (a regime counts when its
        ``interestingness_diff > 0`` AND ``interestingness_t >= t_bar``), and
      * has a mean ``fire_rate`` across its regimes ``<= fire_rate_cap``.

    Returns that value, or ``None`` ("no sane threshold" → retire candidate) when
    no swept value clears both bars.
    """
    by_value: dict[float, list[dict]] = {}
    for r in rows:
        by_value.setdefault(r["value"], []).append(r)

    qualifying: list[float] = []
    for value, vrows in by_value.items():
        n_sig = sum(1 for r in vrows if r["interestingness_diff"] > 0 and r["interestingness_t"] >= t_bar)
        if n_sig < min_regimes:
            continue
        mean_fire = sum(r["fire_rate"] for r in vrows) / len(vrows)
        if mean_fire > fire_rate_cap:
            continue
        qualifying.append(value)

    if not qualifying:
        return None
    return min(qualifying)  # loosest = lowest threshold


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = (
    "detector",
    "value",
    "regime",
    "regime_label",
    "fire_rate",
    "interestingness_diff",
    "interestingness_t",
    "n_fired",
)


def write_csv(rows, path, detector: str) -> None:
    """Write sweep rows to ``path`` as CSV with the :data:`CSV_COLUMNS` header.

    The ``detector`` name is stamped onto every row (the sweep rows themselves
    are detector-agnostic — they carry the threshold ``value``, not the name).
    """
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({"detector": detector, **{k: row[k] for k in CSV_COLUMNS[1:]}})


# The real-data ``main()`` (a ``gap``-threshold sweep) was removed 2026-06-12
# when ``GapDetector`` was deleted. The harness above is detector-agnostic and
# offline-tested; re-add a ``main()`` to sweep any threshold-tunable detector.
