"""Scanner orchestrator.

Runs the 4 event detectors across a universe of tickers, optionally evaluates
quant signals on tickers that triggered at least one event, computes a
composite score, and returns the Top-N ranked ``ScoredEntry`` list.

Concurrency model:
    A ``ThreadPoolExecutor`` of ``max_workers`` threads is fed all tickers.
    Each worker checks an ``FDClient`` out of a ``queue.Queue`` of pre-built
    clients, runs all detectors for one ticker, returns the client. This
    avoids the well-known thread-safety hole around ``requests.Session``.

Failure isolation:
    Any exception inside a single ticker's pipeline is logged and counted;
    the run continues. The runner only raises if the entire pool fails to
    start (e.g. ``fd_factory`` throws).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Callable, Iterable

from pydantic import BaseModel, Field

from v2.data.protocol import DataClient
from v2.models import SignalResult
from v2.scanner.detectors import ALL_DETECTORS
from v2.scanner.detectors.base import EventDetector
from v2.scanner.models import ScanContext, ScannerWeights, ScoredEntry, ScanOutcome
from v2.scanner.scoring import compute_composite

logger = logging.getLogger(__name__)


class ScanProgress(BaseModel):
    """Snapshot of an in-flight scan. Emitted via ``progress_cb``."""

    processed: int = 0
    total: int = 0
    triggered: int = 0
    skipped: int = 0
    errors: int = 0
    current_ticker: str | None = None
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None


def _resolve_detectors(
    detectors: Iterable[EventDetector] | None,
) -> list[EventDetector]:
    if detectors is not None:
        return list(detectors)
    return [cls() for cls in ALL_DETECTORS]


def _evaluate_quant(
    ticker: str,
    end_date: str,
    fd: DataClient,
    quant_signals: list,
) -> dict[str, SignalResult]:
    """Compute v2 quant signals for one ticker, returning a name->result map.

    Each ``BaseSignal`` exposes ``.name`` (class attr) and
    ``.compute(ticker, end_date, fd)``. Failures are isolated per-signal so
    a single broken factor doesn't blow up the ticker.
    """
    out: dict[str, SignalResult] = {}
    for sig in quant_signals:
        try:
            result = sig.compute(ticker, end_date, fd)
            out[sig.name] = result
        except Exception as e:
            logger.warning("Quant signal %r failed for %s: %s", getattr(sig, "name", "?"), ticker, e)
    return out


def _scan_one_ticker(
    ticker: str,
    end_date: str,
    detectors: list[EventDetector],
    quant_signals: list,
    fd_pool: queue.Queue,
    weights: ScannerWeights,
    benchmark_prices: list | None = None,
    benchmark_cvo_gap_by_date: dict[str, tuple[float, float]] | None = None,
    target_snapshots: list | None = None,
    upcoming_earnings_days_to: dict[str, int] | None = None,
) -> ScanOutcome:
    """Return one explicit outcome, including every enabled detector."""
    fd = fd_pool.get()
    evidence_start = len(getattr(fd, 'evidence', []))
    quality_start = len(getattr(fd, 'quality', []))
    try:
        ctx = ScanContext(ticker=ticker, end_date=end_date, benchmark_prices=benchmark_prices,
            benchmark_cvo_gap_by_date=benchmark_cvo_gap_by_date, target_snapshots=target_snapshots,
            upcoming_earnings_days_to=upcoming_earnings_days_to)
        triggers, results = [], []
        for det in detectors:
            item = {'detector': det.name, 'version': '1', 'status': 'no_data'}
            try:
                trigger = det.detect(ticker, end_date, fd, ctx=ctx)
                if trigger is not None:
                    triggers.append(trigger)
                    item.update(status='triggered' if trigger.triggered else 'no_event',
                        severity=float(trigger.severity_z), direction=trigger.direction,
                        reason=trigger.reason, components=trigger.components)
            except Exception as error:
                logger.warning('Detector %s failed for %s (%s)', det.name, ticker, type(error).__name__)
                item.update(status='error', reason=type(error).__name__)
            results.append(item)
        valid = any(item['status'] in ('triggered', 'no_event') for item in results)
        outcome = 'evaluated' if valid else ('error' if any(item['status'] == 'error' for item in results) else 'no_data')
        entry = None
        if any(trigger.triggered for trigger in triggers):
            quant = _evaluate_quant(ticker, end_date, fd, quant_signals) if quant_signals else {}
            entry = compute_composite(ticker, triggers, quant, weights)
        return ScanOutcome(ticker=ticker, outcome=outcome, entry=entry, detector_results=results,
            evidence=getattr(fd, 'evidence', [])[evidence_start:],
            quality={'inputs': getattr(fd, 'quality', [])[quality_start:],
                     'partial': any(item['status'] in ('error', 'no_data') for item in results),
                     'target_snapshots': [{k: getattr(x, k, None) for k in ('asof_date', 'target_median', 'target_mean', 'target_high', 'target_low')} for x in (target_snapshots or [])],
                     'upcoming_earnings_days_to': (upcoming_earnings_days_to or {}).get(ticker)})
    finally:
        fd_pool.put(fd)


def run_scan(
    *,
    tickers: list[str],
    end_date: str,
    top_n: int = 20,
    weights: ScannerWeights | None = None,
    detectors: Iterable[EventDetector] | None = None,
    quant_signals: Iterable | None = None,
    max_workers: int = 16,
    provider_factory: Callable[[], DataClient] | None = None,
    fd_factory: Callable[[], DataClient] | None = None,
    progress_cb: Callable[[ScanProgress], None] | None = None,
    progress_every: int = 10,
    benchmark_ticker: str | None = None,
    target_snapshots: dict[str, list] | None = None,
    upcoming_earnings: dict[str, int] | None = None,
    outcome_cb: Callable[[ScanOutcome], None] | None = None,
) -> list[ScoredEntry]:
    """Scan a universe of tickers and return the Top-N ranked candidates.

    Args:
        tickers:          Universe to scan.
        end_date:         As-of date in YYYY-MM-DD.
        top_n:            Maximum entries to return (sorted by composite desc).
        weights:          ScannerWeights override; defaults to ``ScannerWeights()``.
        detectors:        Override the default 4 detectors (useful for tests).
        quant_signals:    Optional iterable of v2.signals.BaseSignal instances to
                          evaluate on triggered tickers.
        max_workers:      Thread-pool size; also the number of DataClient instances created.
        provider_factory: Callable returning a new ``DataClient``. Defaults to the
                          env-driven factory (``SCANNER_DATA_PROVIDER`` → FD or Finnhub).
        fd_factory:       **Deprecated** alias for ``provider_factory``.
        progress_cb:      Optional callback receiving ``ScanProgress`` snapshots.
        progress_every:   Emit progress every N tickers (plus at start and end).

    Returns:
        Top-N ScoredEntries sorted by composite_score desc, with ``rank`` filled in.
    """
    if fd_factory is not None and provider_factory is None:
        warnings.warn(
            "fd_factory is deprecated; use provider_factory",
            DeprecationWarning,
            stacklevel=2,
        )
        provider_factory = fd_factory

    if provider_factory is None:
        # Resolve via the env-driven factory (defaults to FD).
        from v2.data.factory import get_provider_factory
        provider_factory = get_provider_factory()

    weights = weights or ScannerWeights()
    det_list = _resolve_detectors(detectors)
    quant_list = list(quant_signals) if quant_signals else []
    universe = list(dict.fromkeys(tickers))
    total = len(universe)
    if total == 0:
        return []

    if len({det.name for det in det_list}) != len(det_list):
        raise ValueError("Detector names must be unique")
    worker_count = max(1, min(max_workers, total))

    # Build one DataClient per worker (per-thread session avoids requests.Session
    # thread-safety issues — see DataClient implementations for details).
    fd_pool: queue.Queue = queue.Queue()
    clients: list[DataClient] = []
    try:
        for _ in range(worker_count):
            client = provider_factory()
            clients.append(client)
            fd_pool.put(client)

        # Pre-fetch the benchmark series ONCE before workers start consuming
        # the pool. The same list reference is then injected into every
        # per-ticker ScanContext (read-only after construction). On any
        # failure we log and fall back to no adjustment (downstream detectors
        # use raw values).
        benchmark_prices: list | None = None
        benchmark_cvo_gap_by_date: dict[str, tuple[float, float]] = {}
        if benchmark_ticker is not None:
            try:
                bench_client = clients[0]
                bench_lookback_days = 90
                bench_start = (
                    date.fromisoformat(end_date) - timedelta(days=bench_lookback_days)
                ).isoformat()
                fetched = bench_client.get_prices(benchmark_ticker, bench_start, end_date)
                if fetched and len(fetched) >= 30:
                    benchmark_prices = list(fetched)
                    logger.info(
                        "Benchmark %s returned %d bars for IDAY adjustment",
                        benchmark_ticker, len(benchmark_prices),
                    )
                else:
                    logger.warning(
                        "Benchmark %s returned only %d bars — disabling adjustment",
                        benchmark_ticker, len(fetched) if fetched else 0,
                    )
            except Exception as e:
                logger.warning(
                    "Benchmark %s fetch failed: %s — falling back to raw IDAY",
                    benchmark_ticker, e,
                )

        # Precompute benchmark same-day (cvo, gap) per date once. Without
        # this the IDAY detector rebuilt the date dict AND recomputed cvo/gap
        # per historical bar inside its inner loop (N tickers × 60 bars =
        # 6000-180000 redundant float ops per scan).
        if benchmark_prices:
            sorted_bench = sorted(benchmark_prices, key=lambda p: p.time[:10])
            prev: object | None = None
            for p in sorted_bench:
                if p.open is None or p.open <= 0:
                    prev = p
                    continue
                op = float(p.open)
                cl = float(p.close) if p.close is not None else op
                bcvo = (cl - op) / op
                bgap = 0.0
                if prev is not None and getattr(prev, "close", None) is not None:
                    pc = float(prev.close)
                    if pc > 0:
                        bgap = (op - pc) / pc
                benchmark_cvo_gap_by_date[p.time[:10]] = (bcvo, bgap)
                prev = p

        benchmark_evidence = list(getattr(clients[0], 'evidence', []))
        scored: list[ScoredEntry] = []
        outcomes: list[ScanOutcome] = []
        processed = 0
        triggered = 0
        skipped = 0
        errors = 0
        started = time.monotonic()
        lock = threading.Lock()

        def _emit_progress(current: str | None = None, force: bool = False) -> None:
            if progress_cb is None:
                return
            if not force and processed % progress_every != 0:
                return
            elapsed = time.monotonic() - started
            eta = None
            if processed > 0:
                per_ticker = elapsed / processed
                eta = max(0.0, per_ticker * (total - processed))
            progress_cb(ScanProgress(
                processed=processed,
                total=total,
                triggered=triggered,
                skipped=skipped,
                errors=errors,
                current_ticker=current,
                elapsed_seconds=elapsed,
                eta_seconds=eta,
            ))

        _emit_progress(force=True)

        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            ts_map = target_snapshots or {}
            future_to_ticker = {
                pool.submit(
                    _scan_one_ticker, t, end_date, det_list, quant_list, fd_pool, weights,
                    benchmark_prices,
                    benchmark_cvo_gap_by_date,
                    ts_map.get(t),
                    upcoming_earnings,
                ): t
                for t in universe
            }
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    outcome = future.result()
                    entry = outcome.entry
                except Exception as e:
                    logger.warning("Unhandled error scanning %s: %s", ticker, e)
                    entry = None
                    outcome = ScanOutcome(ticker=ticker, outcome='error', quality={'error': type(e).__name__})
                    with lock:
                        errors += 1
                outcomes.append(outcome)
                with lock:
                    processed += 1
                    if entry is not None:
                        scored.append(entry)
                        triggered += 1
                    else:
                        skipped += 1
                _emit_progress(current=ticker)
        _emit_progress(force=True)

        # Sort by composite first, then by raw severity. The secondary key
        # breaks ties at composite=100 (where the 5σ clip flattens
        # everything from z=5 to z=43 to the same score) so MRVL's
        # z=-43 outranks PAYX's z=-3 even though both are "100".
        scored.sort(key=lambda e: (e.composite_score, e.event_severity), reverse=True)
        for i, entry in enumerate(scored, start=1):
            entry.rank = i
        top = scored[:max(0, top_n)]
        selected = {entry.ticker for entry in top}
        if outcome_cb:
            from v2.scanner.detectors import RETIRED_DETECTORS
            retired = set(weights.enabled_detectors or []) & RETIRED_DETECTORS
            for outcome in outcomes:
                outcome.detector_results.extend({'detector': name, 'version': 'retired', 'status': 'retired'} for name in sorted(retired))
                outcome.evidence = benchmark_evidence + outcome.evidence
                outcome.selected = outcome.ticker in selected
                outcome_cb(outcome)
        return top
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
