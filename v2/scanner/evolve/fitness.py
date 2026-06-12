"""Bridge from a :class:`ScannerEvolveConfig` to live detector instances + the
A/B-vs-random fitness scorer.

The scanner self-evolve loop tunes detector thresholds inside the bounded
:class:`~v2.scanner.evolve.config.ScannerEvolveConfig`. To measure a config's
fitness, the engine needs the *live* detectors those thresholds describe
(:func:`_detectors_from_config`) and a scorer that replays the real scanner over
a regime window and compares the fired Top-N's forward returns against a random
same-universe baseline (:func:`scanner_fitness`).

No-lookahead is load-bearing (CLAUDE.md scanner invariant): the replay only ever
feeds detectors data dated ``<= asof`` via a per-ticker
:class:`~v2.scanner.eval.cached_asof_client.CachedAsOfClient`. Forward returns
and SPY alpha are read from the FULL ascending close series — that is the
*outcome* the detectors are graded against, NOT an input they saw.
"""

from __future__ import annotations

import random

from v2.scanner.detectors import (
    EventDetector,
    GapDetector,
    HighBreakoutDetector,
    MaCrossDetector,
    RsiDivergenceDetector,
)
from v2.scanner.detectors.base import close_of
from v2.scanner.eval.cached_asof_client import CachedAsOfClient, TickerBundle
from v2.scanner.eval.detector_ab import evaluate_detector, forward_return
from v2.scanner.evolve.config import ScannerEvolveConfig
from v2.scanner.models import ScannerWeights
from v2.scanner.runner import run_scan


def _detectors_from_config(config: ScannerEvolveConfig) -> list[EventDetector]:
    """Construct one detector per key in ``config.detectors``, tuned to its params.

    The ``high_breakout`` and ``ma_cross`` lookback windows are *derived* from
    the tuned param rather than left at the detector default: high_breakout
    needs ``window + 2`` trading bars and ma_cross needs ``slow + 2``. At the
    top of their adjustable ranges (window=300, slow=300) the detectors' default
    400-calendar-day fetch yields too few bars and the detector would silently
    return ``None``. ``max(400, param * 2 + 100)`` calendar days guarantees
    enough bars across the whole range.

    An unrecognized detector name raises :class:`ValueError` (the config layer
    already guarantees the 4 names, but fail loud).
    """
    detectors: list[EventDetector] = []
    for name, params in config.detectors.items():
        if name == "high_breakout":
            window = params["window"]
            detectors.append(HighBreakoutDetector(window=window, lookback_days=max(400, window * 2 + 100)))
        elif name == "ma_cross":
            fast = params["fast"]
            slow = params["slow"]
            detectors.append(MaCrossDetector(fast=fast, slow=slow, lookback_days=max(400, slow * 2 + 100)))
        elif name == "gap":
            detectors.append(GapDetector(threshold=params["threshold"]))
        elif name == "rsi_divergence":
            detectors.append(RsiDivergenceDetector(div_window=params["div_window"]))
        else:
            raise ValueError(f"unknown detector name in config.detectors: {name!r}")
    return detectors


# ---------------------------------------------------------------------------
# Universe-level as-of client
# ---------------------------------------------------------------------------


class _UniverseAsOfClient:
    """Serve a whole universe through one no-lookahead client.

    A :class:`CachedAsOfClient` wraps a SINGLE ticker's bundle and ignores the
    ``ticker`` arg. ``run_scan`` scans the whole universe, so we hold one
    per-ticker client and route :meth:`get_prices` to the right one. The 4
    evolve detectors only ever call ``get_prices``; we delegate that plus
    :meth:`set_asof` / :meth:`close`.

    The same instance is shared (read-only) across all worker threads in a
    single scan; ``set_asof`` is always called BEFORE the scan, never during,
    so concurrent ``get_prices`` reads are safe.
    """

    def __init__(self, bundles: dict[str, TickerBundle]) -> None:
        self._clients = {ticker: CachedAsOfClient(bundle) for ticker, bundle in bundles.items()}

    def set_asof(self, date_iso: str) -> None:
        for client in self._clients.values():
            client.set_asof(date_iso)

    def get_prices(self, ticker: str, start_date: str, end_date: str, **kwargs):
        client = self._clients.get(ticker)
        if client is None:
            return []
        return client.get_prices(ticker, start_date, end_date, **kwargs)

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# scanner_fitness helpers
# ---------------------------------------------------------------------------


def _asof_dates(
    bundles: dict[str, TickerBundle],
    start: str,
    end: str,
    rebalance_step: int,
) -> list[str]:
    """Sorted-unique price dates within ``[start, end]``, stepped by ``rebalance_step``.

    Deterministic: collects every distinct ``price.time[:10]`` across all
    bundles that falls in the inclusive window, sorts, and takes every
    ``rebalance_step``-th date.
    """
    start10, end10 = start[:10], end[:10]
    dates: set[str] = set()
    for bundle in bundles.values():
        for p in bundle.prices:
            t = getattr(p, "time", None)
            if not t:
                continue
            d = t[:10]
            if start10 <= d <= end10:
                dates.add(d)
    ordered = sorted(dates)
    step = max(1, rebalance_step)
    return ordered[::step]


def _parse_bundle_series(bundle: TickerBundle) -> tuple[list[float], dict[str, int]] | None:
    """Parse a bundle into ``(ascending_closes, time_to_idx)`` ONCE.

    Sorts the bundle's prices ascending by date, extracts each close (mirroring
    :func:`close_of`), and builds a ``{time[:10]: idx}`` map (the
    ``detector_ab.run_ab`` idiom) for O(1) as-of lookups. Returns ``None`` if any
    close is invalid — that whole-series invalidity is what the old
    ``_closes_and_index`` signalled, preserved here so a failed parse memoizes
    too.

    The returned series is the FULL series (post-asof bars included): it is the
    outcome the detectors are graded against, not an input they saw.
    """
    prices_sorted = sorted(bundle.prices, key=lambda p: (getattr(p, "time", "") or "")[:10])
    closes: list[float] = []
    time_to_idx: dict[str, int] = {}
    for i, p in enumerate(prices_sorted):
        c = close_of(p)
        if c is None:
            return None
        closes.append(c)
        time_to_idx[(getattr(p, "time", "") or "")[:10]] = i
    return closes, time_to_idx


def _closes_and_index(
    bundle: TickerBundle,
    date_iso: str,
    *,
    cache: dict | None = None,
    cache_key: str | None = None,
) -> tuple[list[float], int] | None:
    """Build the FULL ascending close series and the index of ``date_iso``.

    Returns ``None`` if the date isn't in the series or any close is invalid.
    Uses the WHOLE series (post-asof bars included) — this is the outcome the
    detectors are graded against, not an input they saw.

    The parsed ``(closes, time_to_idx)`` is memoized in ``cache[cache_key]`` when
    a ``cache`` dict is supplied; bundles are immutable for a run, so the parse
    is a pure function of the bundle and reusing it never changes results — only
    the per-date ``idx`` lookup varies. A ``None`` cache parses fresh each call.
    """
    parsed = None
    if cache is not None and cache_key is not None and cache_key in cache:
        parsed = cache[cache_key]
    else:
        parsed = _parse_bundle_series(bundle)
        if cache is not None and cache_key is not None:
            cache[cache_key] = parsed
    if parsed is None:
        return None
    closes, time_to_idx = parsed
    idx = time_to_idx.get(date_iso[:10], -1)
    if idx < 0:
        return None
    return closes, idx


def _forward_from(
    bundle: TickerBundle,
    date_iso: str,
    horizon: int,
    *,
    cache: dict | None = None,
    cache_key: str | None = None,
) -> float | None:
    """``horizon``-bar forward return of ``bundle`` measured from ``date_iso``."""
    cl = _closes_and_index(bundle, date_iso, cache=cache, cache_key=cache_key)
    if cl is None:
        return None
    closes, idx = cl
    return forward_return(closes, idx, horizon)


# ---------------------------------------------------------------------------
# scanner_fitness
# ---------------------------------------------------------------------------


def scanner_fitness(
    bundles: dict[str, TickerBundle],
    config: ScannerEvolveConfig,
    sample,
    *,
    window_of=None,
    spy_bundle: TickerBundle | None = None,
    horizon: int = 5,
    rebalance_step: int = 5,
    baseline_per_date: int = 20,
    rng_seed: int = 0,
    max_workers: int = 8,
    cache: dict | None = None,
) -> dict:
    """A/B-vs-random fitness of a scanner config over a sample's regime window(s).

    Replays the real :func:`~v2.scanner.runner.run_scan` Top-N at each rebalance
    date inside ``window_of(sample)``, no-lookahead (detectors see only
    ``<= asof``). For every fired ticker it accumulates the ``horizon``-bar
    forward return; a seeded random same-universe baseline is accumulated in
    parallel.

    The PRIMARY metric is INTERESTINGNESS (magnitude vs random): the mean
    |forward return| of the fired Top-N MINUS the random baseline's. WHY: the
    scanner is an LLM-cost PRE-FILTER — its job is to flag stocks that will MOVE
    more than chance so the agent spends its budget on them; DIRECTION is the
    agent's job, not the scanner's. The SIGNED diff (mean signed return vs
    baseline) is retained only as secondary directional colour.

    Returns ``{"fitness", "interestingness_diff", "interestingness_t",
    "n_fired", "signed_diff", "signed_t", "alpha_5d"}`` where ``fitness ==
    interestingness_diff``. Never raises on bad data: a config that fires nothing
    → graceful zero edge; a bundle with too few bars simply contributes no fired
    return.

    ``cache`` is an OPTIONAL ``{ticker: parsed_series}`` dict for the
    forward-return path: each bundle's ascending closes + time→idx map is parsed
    ONCE and reused across as-of dates AND across calls that share the same dict
    (e.g. successive iterations of the evolve loop over immutable bundles). Pass
    a run-scoped ``{}`` to memoize across iterations; leave it ``None`` for a
    throwaway per-call cache. It is a PURE performance optimization — keyed by
    ticker with immutable values, it never changes the returned dict.
    """
    if cache is None:
        # Throwaway per-call cache so standalone calls still memoize within the
        # call (parse each bundle once per call), without persisting across calls.
        cache = {}

    if window_of is None:
        # Task 5 module; imported lazily so Task 3 can land first.
        from v2.scanner.evolve.samples import window_of

    dets_unused = _detectors_from_config(config)  # validate config early; fail loud on a bad name
    del dets_unused

    weights = ScannerWeights(
        event_weight=1.0,
        quant_weight=0.0,
        detector_severity_mult=dict(config.severity_mult),
    )

    client = _UniverseAsOfClient(bundles)
    universe = sorted(bundles)

    fire_returns: list[float] = []
    baseline_returns: list[float] = []
    alpha_accum: list[float] = []

    # Seed ONCE before the whole loop so the full run is deterministic.
    rng = random.Random(rng_seed)

    for start, end in window_of(sample):
        for date_iso in _asof_dates(bundles, start, end, rebalance_step):
            client.set_asof(date_iso)
            scored = run_scan(
                tickers=universe,
                end_date=date_iso,
                top_n=config.top_n,
                weights=weights,
                detectors=_detectors_from_config(config),
                quant_signals=None,
                max_workers=max_workers,
                provider_factory=lambda: client,
            )

            spy_ret = None
            if spy_bundle is not None:
                spy_ret = _forward_from(spy_bundle, date_iso, horizon, cache=cache, cache_key="__spy__")

            for entry in scored:
                try:
                    ret = _forward_from(bundles[entry.ticker], date_iso, horizon, cache=cache, cache_key=entry.ticker)
                except Exception:
                    ret = None
                if ret is None:
                    continue
                fire_returns.append(ret)
                if spy_bundle is not None and spy_ret is not None:
                    alpha_accum.append(ret - spy_ret)

            # Random same-universe baseline (mirrors detector_ab.run_ab's seeded baseline).
            k = min(baseline_per_date, len(universe))
            if k > 0:
                for ticker in rng.sample(universe, k):
                    try:
                        ret = _forward_from(bundles[ticker], date_iso, horizon, cache=cache, cache_key=ticker)
                    except Exception:
                        ret = None
                    if ret is not None:
                        baseline_returns.append(ret)

    metrics = evaluate_detector(
        fire_returns=fire_returns,
        baseline_returns=baseline_returns,
        horizon=horizon,
    )

    if metrics["n_fired"] == 0:
        return {
            "fitness": 0.0,
            "interestingness_diff": 0.0,
            "interestingness_t": 0.0,
            "n_fired": 0,
            "signed_diff": 0.0,
            "signed_t": 0.0,
            "alpha_5d": None,
        }

    alpha_5d = None
    if spy_bundle is not None:
        alpha_5d = sum(alpha_accum) / len(alpha_accum) if alpha_accum else None

    return {
        "fitness": metrics["interestingness_diff"],  # PRIMARY = the pre-filter metric
        "interestingness_diff": metrics["interestingness_diff"],
        "interestingness_t": metrics["interestingness_t"],
        "n_fired": metrics["n_fired"],
        "signed_diff": metrics["diff"],  # SECONDARY (directional colour, retained)
        "signed_t": metrics["t_stat"],
        "alpha_5d": alpha_5d,
    }
