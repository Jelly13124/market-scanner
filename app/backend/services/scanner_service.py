"""ScannerService — orchestrates a scan run from DB config to DB results.

Lifecycle of a single ``execute()`` call:

    1. Load ScannerConfig from DB. Create a ScanRun row (PENDING).
    2. Resolve universe via ``load_universe(kind, custom)``.
    3. Mark run RUNNING, broadcast 'start' event.
    4. Invoke ``v2.scanner.runner.run_scan`` (sync, thread-pool internally).
       Progress callbacks bridge to the broadcaster.
    5. Bulk-insert WatchlistEntry rows.
    6. Mark run COMPLETE (or ERROR on exception). Broadcast 'complete' / 'error'.

The service is intentionally synchronous so it can be invoked from APScheduler
background jobs OR from a thread spawned by an async REST endpoint. The runner
itself manages its own ThreadPoolExecutor.

Concurrency guard: refuses to start a new run for a config that already has
a RUNNING row (prevents accidental double-trigger from cron + manual).
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Callable

from sqlalchemy.orm import Session

from app.backend.database.models import ScanRun
from app.backend.repositories.scanner_repository import (
    AnalystTargetSnapshotRepository,
    ScanRunRepository,
    ScannerConfigRepository,
    WatchlistEntryRepository,
)
from app.backend.repositories.watchlist_repository import UserWatchlistRepository
from app.backend.services.scan_broadcaster import ScanBroadcaster
from v2.data.factory import recommend_max_workers
from v2.data.yfinance_client import YFinanceClient
from v2.scanner.detectors import ALL_DETECTORS
from v2.scanner.models import ScannerWeights, ScoredEntry
from v2.scanner.runner import ScanProgress, run_scan
from v2.scanner.universes import load_universe
from v2.signals import ALL_SIGNALS

logger = logging.getLogger(__name__)


class ScanAlreadyRunningError(RuntimeError):
    """Raised when a scan is requested for a config that already has a RUNNING row."""


class ScannerService:
    """DB-aware wrapper around ``v2.scanner.runner.run_scan``."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        broadcaster: ScanBroadcaster | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._broadcaster = broadcaster

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        config_id: int,
        *,
        end_date: str | None = None,
        max_workers: int | None = None,
    ) -> int:
        """Run a scan synchronously to completion. Returns the new run_id.

        ``max_workers`` defaults to ``recommend_max_workers()`` for the
        active provider (16 for FD, 4 for Finnhub).

        Use this for cron-driven runs where blocking on the scan is fine.
        For REST manual runs where the HTTP response should return quickly
        with the run_id, use ``execute_async`` instead.
        """
        end_date = end_date or date.today().isoformat()
        if max_workers is None:
            max_workers = recommend_max_workers()

        # Phase 1: load config, refuse double-run, create PENDING row.
        config_payload, run_id = self._begin(config_id)
        self._run_to_completion(run_id, config_payload, end_date, max_workers)
        return run_id

    def execute_async(
        self,
        config_id: int,
        *,
        end_date: str | None = None,
        max_workers: int | None = None,
    ) -> int:
        """Create the pending run row, return ``run_id`` immediately, run on a
        daemon thread.

        The HTTP caller can subscribe to ``/scanner/runs/{run_id}/stream``
        right after the response lands — the broadcaster collects events as
        soon as the background thread starts publishing.
        """
        end_date = end_date or date.today().isoformat()
        if max_workers is None:
            max_workers = recommend_max_workers()

        config_payload, run_id = self._begin(config_id)

        def _bg() -> None:
            try:
                self._run_to_completion(run_id, config_payload, end_date, max_workers)
            except Exception:
                # _run_to_completion already logged + marked ERROR; swallow so
                # the thread exits cleanly.
                pass

        thread = threading.Thread(
            target=_bg,
            name=f"scanner-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return run_id

    def _run_to_completion(
        self,
        run_id: int,
        config_payload: dict,
        end_date: str,
        max_workers: int,
    ) -> None:
        """Phase 2 of execute(): tickers -> scan -> persist -> mark complete.

        Mirrors the original try/except/finally body. Used by both ``execute``
        and the background thread in ``execute_async``.
        """
        try:
            tickers = load_universe(
                config_payload["universe_kind"],
                custom=config_payload["universe_tickers"],
                watchlist_tickers=config_payload.get("watchlist_tickers"),
            )
            self._mark_running(run_id, len(tickers))
            self._publish(run_id, {"event": "start", "run_id": run_id, "universe_size": len(tickers)})

            weights = self._build_weights(config_payload["weights"])

            # Per-universe benchmark for IDAY's SPY-relative adjustment.
            # NDX-100 is best matched against QQQ (~95% beta); broader US
            # universes use SPY. The runner pre-fetches the series once and
            # injects it into every per-ticker ScanContext.
            BENCHMARK_BY_UNIVERSE = {
                "nasdaq100": "QQQ",
                "sp500": "SPY",
                "nasdaq100_sp500": "SPY",
                "russell3000": "SPY",
                "all_us": "SPY",
                "custom": "SPY",
                "watchlist": "SPY",
            }
            benchmark_ticker = BENCHMARK_BY_UNIVERSE.get(
                config_payload["universe_kind"],
                "SPY",
            )

            # M9.d — refresh today's analyst-target snapshot for every ticker
            # and load the trailing N days back. Done BEFORE the scan pool
            # starts so the target_shift detector sees consistent history.
            # Bootstrap: on day 1 the detector returns None (insufficient
            # snapshots); useful triggers only fire from day 2 onward.
            target_snapshots_by_ticker = self._refresh_target_snapshots(
                tickers,
                end_date,
            )

            # M9.f — load the universe-wide earnings calendar ONCE via
            # Finnhub /calendar/earnings and produce a {ticker → days_to}
            # dict the EarningsUpcomingDetector reads from ctx. Empty dict
            # when Finnhub doesn't cover the universe; None signals "no
            # calendar loaded" which makes the detector exclude tickers
            # from stats (vs returning a misleading "no upcoming" verdict).
            upcoming_earnings = self._load_earnings_calendar(
                tickers,
                end_date,
            )

            # Build the per-config detector list. None = all (preserves
            # pre-feature behavior); a non-None list filters ALL_DETECTORS
            # by .name. Validation already happened in ScannerWeights, so
            # any unknown name would have been rejected upstream — the
            # filter here is purely structural.
            if weights.enabled_detectors is None:
                det_instances = [c() for c in ALL_DETECTORS]
            else:
                enabled_set = set(weights.enabled_detectors)
                det_instances = [c() for c in ALL_DETECTORS if c().name in enabled_set]
            logger.info(
                "Scan run %s using %d/%d detectors: %s",
                run_id,
                len(det_instances),
                len(ALL_DETECTORS),
                [d.name for d in det_instances],
            )

            scored = run_scan(
                tickers=tickers,
                end_date=end_date,
                top_n=config_payload["top_n"],
                weights=weights,
                detectors=det_instances,
                quant_signals=[cls() for cls in ALL_SIGNALS],
                max_workers=max_workers,
                progress_cb=lambda p: self._publish_progress(run_id, p),
                benchmark_ticker=benchmark_ticker,
                target_snapshots=target_snapshots_by_ticker,
                upcoming_earnings=upcoming_earnings,
            )

            self._persist_results(run_id, scored)
            self._mark_complete(run_id)
            self._publish(
                run_id,
                {
                    "event": "complete",
                    "run_id": run_id,
                    "entries": len(scored),
                },
            )
        except Exception as e:
            logger.exception("Scan run %s failed", run_id)
            self._mark_error(run_id, str(e))
            self._publish(run_id, {"event": "error", "run_id": run_id, "message": str(e)})
            raise
        finally:
            if self._broadcaster is not None:
                self._broadcaster.close(run_id)

        # Phase 5E — auto-SOP follow-up runs OUTSIDE the main try/except so
        # an LLM/network/email failure here can never roll back the scan
        # persistence or re-mark the run as ERROR. Wrapped in its own
        # try/except so an exception here still leaves the scan COMPLETE.
        try:
            top_n = int(config_payload.get("auto_sop_top_n") or 0)
            if top_n > 0:
                use_personas = bool(
                    config_payload.get("auto_sop_use_personas") or False,
                )
                self._run_auto_sop_followup(
                    run_id,
                    top_n,
                    use_personas,
                    owner_user_id=config_payload.get("owner_user_id"),
                )
        except Exception:
            logger.exception(
                "auto_sop follow-up failed for scan_run %s (scan itself OK)",
                run_id,
            )

    # ------------------------------------------------------------------
    # Phase helpers
    # ------------------------------------------------------------------

    def _begin(self, config_id: int) -> tuple[dict, int]:
        """Load config, refuse double-run, create the PENDING row.

        Returns (config_payload_dict, run_id). We dehydrate config into a dict
        so subsequent phases don't hold the session open across long-running work.
        """
        with self._session_factory() as session:
            config = ScannerConfigRepository(session).get_by_id_unscoped(config_id)
            if not config:
                raise ValueError(f"No scanner config with id {config_id}")

            existing = session.query(ScanRun).filter(ScanRun.config_id == config_id, ScanRun.status == "RUNNING").first()
            if existing is not None:
                raise ScanAlreadyRunningError(f"Scanner config {config_id} already has a RUNNING run (id={existing.id})")

            # Phase 5C — when targeting a UserWatchlist, resolve the tickers
            # here (inside the same session) so the long-running scan thread
            # doesn't have to reopen a session. Fail fast with a clear message
            # if the FK points at a deleted/missing watchlist.
            watchlist_tickers: list[str] | None = None
            if config.universe_kind == "watchlist":
                if config.user_watchlist_id is None:
                    raise ValueError(f"Scanner config {config_id} has universe_kind='watchlist' " "but user_watchlist_id is null")
                wl = UserWatchlistRepository(session).get_by_id_unscoped(config.user_watchlist_id)
                if wl is None:
                    raise ValueError(f"watchlist {config.user_watchlist_id} not found " f"(referenced by scanner config {config_id})")
                watchlist_tickers = list(wl.tickers or [])
                if not watchlist_tickers:
                    raise ValueError(f"watchlist {config.user_watchlist_id} ({wl.name!r}) is empty")

            run = ScanRunRepository(session).create_pending(config_id)
            payload = {
                "universe_kind": config.universe_kind,
                "universe_tickers": config.universe_tickers,
                "watchlist_tickers": watchlist_tickers,
                "top_n": config.top_n,
                "weights": config.weights,
                # Phase 5E — auto-SOP knobs propagated through so the
                # follow-up hook at the end of _run_to_completion can read
                # them without reopening a session.
                "auto_sop_top_n": getattr(config, "auto_sop_top_n", 0) or 0,
                "auto_sop_use_personas": bool(getattr(config, "auto_sop_use_personas", False)),
                # Wave 4 — the cron/manual run path attributes any auto-SOP
                # reports to the config's OWNING user so they show up scoped
                # under that user (not as orphaned user_id=NULL rows).
                "owner_user_id": config.user_id,
            }
            return payload, run.id

    def _mark_running(self, run_id: int, universe_size: int) -> None:
        with self._session_factory() as session:
            ScanRunRepository(session).mark_running(run_id, universe_size=universe_size)

    def _mark_complete(self, run_id: int) -> None:
        with self._session_factory() as session:
            ScanRunRepository(session).mark_complete(run_id)

    def _mark_error(self, run_id: int, msg: str) -> None:
        try:
            with self._session_factory() as session:
                ScanRunRepository(session).mark_error(run_id, msg)
        except Exception:
            logger.exception("Failed to mark run %s as ERROR", run_id)

    def _persist_results(self, run_id: int, scored: list[ScoredEntry]) -> None:
        if not scored:
            return
        rows = [
            {
                "ticker": e.ticker,
                "composite_score": e.composite_score,
                "direction": e.direction,
                "event_score": e.event_score,
                "quant_score": e.quant_score,
                "event_severity": e.event_severity,
                "triggers": e.triggers,
                "rank": e.rank,
            }
            for e in scored
        ]
        with self._session_factory() as session:
            WatchlistEntryRepository(session).bulk_insert(run_id, rows)

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _build_weights(self, raw: dict | None) -> ScannerWeights:
        if not raw:
            return ScannerWeights()
        try:
            return ScannerWeights(**raw)
        except Exception as e:
            logger.warning("Bad weights JSON, falling back to defaults: %s", e)
            return ScannerWeights()

    def _refresh_target_snapshots(
        self,
        tickers: list[str],
        end_date: str,
        *,
        max_fetch_workers: int = 16,
        lookback_days: int = 14,
    ) -> dict[str, list]:
        """Upsert today's analyst-target snapshot per ticker, then load the
        trailing N days back as a dict[ticker, list[snapshot]].

        Uses ``YFinanceClient`` directly — yfinance is the only backend that
        exposes analyst price targets and has no rate limit, so we don't need
        to go through the hybrid composite (which would also pay the cost of
        instantiating EODHD + Finnhub sub-clients).

        Failures are isolated per-ticker — a single yfinance HTML change
        won't abort the scan. Bootstrap: on day 1 we just have today's row,
        so the detector reading these will return None (insufficient
        history). Useful triggers fire from day 2.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not tickers:
            return {}

        client = YFinanceClient()

        def _fetch(t: str):
            try:
                return t, client.get_analyst_targets(t, asof_date=end_date)
            except Exception as e:
                logger.warning("get_analyst_targets failed for %s: %s", t, e)
                return t, None

        targets: dict[str, object] = {}
        with ThreadPoolExecutor(max_workers=max_fetch_workers) as pool:
            futures = [pool.submit(_fetch, t) for t in tickers]
            for fut in as_completed(futures):
                t, target = fut.result()
                targets[t] = target

        # Single session: bulk upsert (no per-row commit) → one commit at the
        # end → load back in the same session. Previous code path issued
        # 100-3000 commits per scan and opened a second session for the
        # read-back.
        with self._session_factory() as session:
            repo = AnalystTargetSnapshotRepository(session)
            upserted = 0
            for t, tgt in targets.items():
                if tgt is None:
                    continue
                try:
                    repo.upsert(
                        ticker=t,
                        asof_date=end_date,
                        target_mean=tgt.target_mean,
                        target_median=tgt.target_median,
                        target_high=tgt.target_high,
                        target_low=tgt.target_low,
                        current_price=tgt.current_price,
                        n_analysts=tgt.n_analysts,
                        commit=False,
                    )
                    upserted += 1
                except Exception as e:
                    logger.warning("target snapshot upsert failed for %s: %s", t, e)
            session.commit()

            logger.info(
                "Target snapshots: fetched %d/%d tickers, upserted %d for %s",
                sum(1 for v in targets.values() if v is not None),
                len(tickers),
                upserted,
                end_date,
            )

            return repo.list_for_tickers(
                tickers,
                lookback_days=lookback_days,
                end_date=end_date,
            )

    def _load_earnings_calendar(
        self,
        tickers: list[str],
        end_date: str,
        *,
        lookahead_days: int = 5,
    ) -> dict[str, int] | None:
        """Pull the upcoming earnings calendar once and build a
        {ticker → days_to_earnings} dict bounded by lookahead.

        Uses Finnhub's /calendar/earnings via the hybrid provider (one HTTP
        call returns every covered symbol in the window — much cheaper than
        per-ticker yfinance lookups). On any failure returns ``None`` so the
        detector excludes tickers from stats rather than asserting "no
        upcoming events" (which would be a misleading verdict when we
        simply don't know).
        """
        from datetime import date as _date, datetime as _datetime, timedelta as _td
        from v2.data.factory import get_provider_factory

        if not tickers:
            return {}

        try:
            scan_day = _datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

        cal_start = scan_day.isoformat()
        cal_end = (scan_day + _td(days=lookahead_days)).isoformat()

        provider_factory = get_provider_factory()
        client = provider_factory()
        try:
            entries = client.get_earnings_calendar(
                start_date=cal_start,
                end_date=cal_end,
            )
        except Exception as e:
            logger.warning(
                "earnings calendar fetch failed (from=%s to=%s): %s",
                cal_start,
                cal_end,
                e,
            )
            return None
        finally:
            try:
                client.close()
            except Exception:
                pass

        if not entries:
            logger.info(
                "Earnings calendar: 0 events in %s..%s (universe %d tickers)",
                cal_start,
                cal_end,
                len(tickers),
            )
            return {}

        # Filter to scan universe and pick the EARLIEST event per ticker
        # (a ticker with two events in the window — rare for split/spinoff —
        # gets the closer date).
        ticker_set = set(tickers)
        per_ticker_min: dict[str, int] = {}
        for e in entries:
            sym = e.symbol.upper() if e.symbol else ""
            if sym not in ticker_set:
                continue
            try:
                event_day = _datetime.strptime(e.date[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            days_to = (event_day - scan_day).days
            if days_to < 0 or days_to > lookahead_days:
                continue
            cur = per_ticker_min.get(sym)
            if cur is None or days_to < cur:
                per_ticker_min[sym] = days_to

        logger.info(
            "Earnings calendar: %d universe tickers with events in next %dd " "(window %s..%s)",
            len(per_ticker_min),
            lookahead_days,
            cal_start,
            cal_end,
        )
        return per_ticker_min

    def _run_auto_sop_followup(
        self,
        scan_run_id: int,
        top_n: int,
        use_personas: bool,
        *,
        owner_user_id: int | None = None,
    ) -> None:
        """Phase 5E: after a scan completes, fire SOP on the top-N watchlist
        entries and dispatch one bundled email containing all reports.

        All work (SOP runs + persistence + dispatch) happens inside a
        fresh session so we don't keep a long-running transaction open
        across the LLM calls. Errors here NEVER propagate to the scan
        run — the caller wraps the entire call in try/except.
        """
        from app.backend.repositories.research_repository import (
            ResearchReportRepository,
        )
        from app.backend.services.auto_sop_runner import run_auto_sop_for_scan
        from app.backend.services.notifications.dispatcher import (
            NotificationDispatcher,
        )

        logger.info(
            "auto_sop: starting follow-up for scan_run=%s top_n=%d personas=%s",
            scan_run_id,
            top_n,
            use_personas,
        )
        with self._session_factory() as session:
            report_ids = run_auto_sop_for_scan(
                session,
                scan_run_id=scan_run_id,
                top_n=top_n,
                use_personas=use_personas,
                owner_user_id=owner_user_id,
            )
        logger.info(
            "auto_sop: produced %d reports for scan_run=%s",
            len(report_ids),
            scan_run_id,
        )

        if not report_ids:
            return

        # Reload the report rows in a fresh session so they're attached when
        # the dispatcher pre-renders the bundled HTML.
        with self._session_factory() as session:
            repo = ResearchReportRepository(session)
            reports = [repo.get_by_id_unscoped(rid) for rid in report_ids]
            reports = [r for r in reports if r is not None]
            # Detach by snapshotting the read-only fields the renderer needs;
            # the dispatcher will run in its own session that doesn't share
            # this one's transaction.
            detached = [
                _DetachedReport(
                    id=r.id,
                    ticker=r.ticker,
                    scan_date=r.scan_date,
                    rendered_html=r.rendered_html,
                    report_markdown=r.report_markdown,
                )
                for r in reports
            ]

        if not detached:
            logger.warning(
                "auto_sop: report_ids non-empty but reload returned nothing " "(scan_run=%s)",
                scan_run_id,
            )
            return

        try:
            NotificationDispatcher(self._session_factory).dispatch_bundled(
                event_type="research.bundled",
                reports=detached,
                scan_run_id=scan_run_id,
            )
        except Exception:
            logger.exception(
                "auto_sop: bundled dispatch failed for scan_run=%s",
                scan_run_id,
            )

    def _publish(self, run_id: int, event: dict) -> None:
        if self._broadcaster is not None:
            self._broadcaster.publish(run_id, event)

    def _publish_progress(self, run_id: int, p: ScanProgress) -> None:
        if self._broadcaster is None:
            return
        self._broadcaster.publish(
            run_id,
            {
                "event": "progress",
                "run_id": run_id,
                **p.model_dump(),
            },
        )


class _DetachedReport:
    """Detached snapshot of a ResearchReport carrying only the fields the
    bundled-email renderer reads. Used so the dispatch step doesn't need
    a live SQLAlchemy session attached to each row."""

    __slots__ = ("id", "ticker", "scan_date", "rendered_html", "report_markdown")

    def __init__(
        self,
        *,
        id: int,
        ticker: str,
        scan_date: str,
        rendered_html: str | None,
        report_markdown: str | None,
    ) -> None:
        self.id = id
        self.ticker = ticker
        self.scan_date = scan_date
        self.rendered_html = rendered_html or ""
        self.report_markdown = report_markdown or ""
