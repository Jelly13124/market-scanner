"""SchedulerService — wraps APScheduler's BackgroundScheduler for the scanner.

One process-wide instance. Bound to a DB session factory + ScannerService on
construction, started by FastAPI's startup hook, and shut down on app exit.

Why ``BackgroundScheduler`` (not ``AsyncIOScheduler``)?
    Our runner is thread-based already (ThreadPoolExecutor inside ``run_scan``)
    — letting APScheduler also be thread-based avoids mixing two event loops.
    Cron-triggered jobs simply call ``ScannerService.execute(config_id)`` on a
    job-pool thread, which then orchestrates its own worker pool.

Timezone:
    All cron expressions are interpreted in ``America/New_York`` so users can
    write "0 21 * * 1-5" and reason about it in market hours, regardless of
    where the server runs.

Concurrency safety:
    ``max_instances=1`` per job ensures the same config can't have two scans
    in flight at once (cron + manual race). The scheduler also misses-fire
    if the previous run hasn't finished — preferable to backing up a queue.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.backend.database import SessionLocal
from app.backend.database.models import ScannerConfig
from app.backend.repositories.pipeline_repository import PipelineRunRepository
from app.backend.repositories.research_repository import ResearchReportRepository
from app.backend.repositories.scanner_repository import ScannerConfigRepository
from app.backend.repositories.screener_repository import ScreenerRepository
from app.backend.repositories.screener_preset_repository import ScreenerPresetRepository
from app.backend.services.notifications.dispatcher import NotificationDispatcher
from src.screener.ashare_metrics import AshareMetrics
from src.screener.snapshot_builder import SnapshotBuilder
from app.backend.services.scanner_service import ScannerService
from src.research.html_render import render_html
from src.research.models import ResearchRequest
from src.research.persist import state_to_db_kwargs
from src.research.pipeline import run_research

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"

# Daily scanner→agent pipeline cron: 16:30 ET weekdays, 30 min after the
# market close so post-close data has settled. Hardcoded in v1; could be
# moved to ``pipeline_schedule.cron_expr`` if users need flexibility.
PIPELINE_CRON_EXPR = "30 16 * * 1-5"
PIPELINE_JOB_ID = "daily-pipeline"

# Daily research cron: 16:35 ET weekdays. Fires AFTER the legacy
# pipeline cron at 16:30 so the watchlist for today is persisted and
# the research job can read it without re-scanning.
RESEARCH_CRON_EXPR = "35 16 * * 1-5"
RESEARCH_JOB_ID = "research_daily"

# Daily screener-snapshot cron: 22:00 ET every day. Runs after both US
# close (16:00 ET) and CN close (15:00 CST = 03:00 ET next day → previous
# session captured by then). Weekend runs are idempotent — they re-pull
# Friday's close.
SCREENER_SNAPSHOT_CRON_EXPR = "0 22 * * *"
SCREENER_SNAPSHOT_JOB_ID = "screener_snapshot"

# Daily screener-preset cron: 22:05 ET every day, 5 min after the snapshot
# cron so fresh rows are already written when presets run.
SCREENER_PRESET_CRON_EXPR = "5 22 * * *"
SCREENER_PRESET_JOB_ID = "screener_presets"


class SchedulerService:
    """Lifecycle + CRUD for scanner cron jobs."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        scanner_service: ScannerService,
        *,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        self._session_factory = session_factory
        self._scanner_service = scanner_service
        self._tz = timezone
        self._scheduler = BackgroundScheduler(timezone=timezone)
        self._lock = threading.Lock()
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler and register all enabled configs."""
        with self._lock:
            if self._started:
                logger.debug("SchedulerService.start() called but already started")
                return
            self._scheduler.start()
            self._started = True

        # Read enabled configs and register their jobs.
        with self._session_factory() as session:
            configs = ScannerConfigRepository(session).list_all(enabled_only=True)
        registered = 0
        for cfg in configs:
            try:
                self._register(cfg)
                registered += 1
            except Exception as e:
                logger.warning("Failed to register config %s: %s", cfg.id, e)

        # Register the singleton daily-pipeline cron. The job ALWAYS fires
        # on the schedule but checks ``pipeline_schedule.enabled`` at
        # fire-time — flipping the switch in the UI takes effect on the
        # next firing without restarting the scheduler.
        try:
            self._register_pipeline_job()
        except Exception as e:
            logger.warning("Failed to register daily pipeline job: %s", e)

        # Register the singleton daily-research cron — fires 5 min after
        # the pipeline cron so the watchlist is already persisted.
        try:
            self._register_research_job()
        except Exception as e:
            logger.warning("Failed to register daily research job: %s", e)

        # Register the singleton daily screener-snapshot cron — 22:00 ET
        # every day, after both US and CN markets have closed.
        try:
            self._register_snapshot_job()
        except Exception as e:
            logger.warning("Failed to register screener snapshot job: %s", e)

        # Register the singleton daily screener-preset cron — 22:05 ET
        # every day, 5 min after the snapshot so fresh rows are available.
        try:
            self._register_preset_job()
        except Exception as e:
            logger.warning("Failed to register screener preset job: %s", e)

        logger.info(
            "SchedulerService started (tz=%s); registered %d/%d enabled scanner configs + daily pipeline + daily research",
            self._tz, registered, len(configs),
        )

    def shutdown(self, wait: bool = False) -> None:
        """Stop the scheduler. ``wait=False`` lets long scans finish detached."""
        with self._lock:
            if not self._started:
                return
            try:
                self._scheduler.shutdown(wait=wait)
            except Exception as e:
                logger.warning("Scheduler shutdown raised: %s", e)
            self._started = False
        logger.info("SchedulerService stopped (wait=%s)", wait)

    @property
    def is_started(self) -> bool:
        return self._started

    # ------------------------------------------------------------------
    # Config-level operations (called by REST routes after CRUD)
    # ------------------------------------------------------------------

    def register_config(self, config: ScannerConfig) -> None:
        """Register or re-register the cron job for *config*. No-op if disabled."""
        if not config.is_enabled:
            self.unregister_config(config.id)
            return
        self._register(config)

    def unregister_config(self, config_id: int) -> None:
        """Remove the cron job for *config_id* if present."""
        job_id = self._job_id(config_id)
        try:
            self._scheduler.remove_job(job_id)
            logger.info("Unregistered scanner job %s", job_id)
        except Exception:
            # Job didn't exist — idempotent.
            pass

    def reschedule_config(self, config: ScannerConfig) -> None:
        """Convenience: re-register with the latest cron + enabled state."""
        self.register_config(config)

    def run_now(self, config_id: int) -> int:
        """Trigger a manual scan; return the new ``run_id`` immediately.

        The scan runs on a background daemon thread inside ``ScannerService``;
        clients subscribe to ``/scanner/runs/{run_id}/stream`` for live
        progress.
        """
        return self._scanner_service.execute_async(config_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _job_id(config_id: int) -> str:
        return f"scanner-config-{config_id}"

    def _register(self, config: ScannerConfig) -> None:
        try:
            trigger = CronTrigger.from_crontab(config.cron_expr, timezone=self._tz)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid cron expression {config.cron_expr!r}: {e}") from e

        job_id = self._job_id(config.id)
        self._scheduler.add_job(
            self._run_job,
            trigger=trigger,
            id=job_id,
            args=[config.id],
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=300,  # 5 min — skip if we're more than 5 min late
            coalesce=True,            # collapse missed fires into one
        )
        logger.info(
            "Registered scanner job %s (cron=%r, tz=%s)",
            job_id, config.cron_expr, self._tz,
        )

    def _run_job(self, config_id: int) -> None:
        """Job body — invoked by APScheduler on a worker thread."""
        try:
            logger.info("Cron trigger: starting scan for config %s", config_id)
            run_id = self._scanner_service.execute(config_id)
            logger.info("Cron scan for config %s completed (run_id=%s)", config_id, run_id)
        except Exception:
            # Exceptions inside cron jobs would otherwise vanish into APScheduler's
            # error log — log them explicitly for visibility.
            logger.exception("Cron scan for config %s failed", config_id)

    # ------------------------------------------------------------------
    # Daily scanner→agent pipeline job
    # ------------------------------------------------------------------

    def _register_pipeline_job(self) -> None:
        """Register the singleton daily pipeline cron.

        The job runs on the cron whether or not the config has
        ``enabled=True`` — it just no-ops when disabled. This lets the UI
        toggle take effect on the next firing without touching the
        scheduler.
        """
        trigger = CronTrigger.from_crontab(PIPELINE_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            self._run_pipeline_job,
            trigger=trigger,
            id=PIPELINE_JOB_ID,
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=600,  # 10 min — pipeline takes longer than a scan
            coalesce=True,
        )
        logger.info(
            "Registered daily pipeline job %s (cron=%r, tz=%s)",
            PIPELINE_JOB_ID, PIPELINE_CRON_EXPR, self._tz,
        )

    def _register_research_job(self) -> None:
        """Register the singleton daily research cron."""
        trigger = CronTrigger.from_crontab(RESEARCH_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            _run_research_job_body,
            trigger=trigger,
            id=RESEARCH_JOB_ID,
            replace_existing=True,
            misfire_grace_time=600,
        )
        logger.info(
            "Registered research job (cron=%r, tz=%s)",
            RESEARCH_CRON_EXPR, self._tz,
        )

    def _register_snapshot_job(self) -> None:
        """Register the singleton daily screener-snapshot cron."""
        trigger = CronTrigger.from_crontab(SCREENER_SNAPSHOT_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            _run_snapshot_job_body,
            trigger=trigger,
            id=SCREENER_SNAPSHOT_JOB_ID,
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info(
            "Registered cron job %s with expression %s (timezone=%s)",
            SCREENER_SNAPSHOT_JOB_ID, SCREENER_SNAPSHOT_CRON_EXPR, self._tz,
        )

    def _register_preset_job(self) -> None:
        """Register the singleton daily screener-preset cron (22:05 ET)."""
        trigger = CronTrigger.from_crontab(SCREENER_PRESET_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            _run_preset_job_body,
            trigger=trigger,
            id=SCREENER_PRESET_JOB_ID,
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info(
            "Registered cron job %s with expression %s (timezone=%s)",
            SCREENER_PRESET_JOB_ID, SCREENER_PRESET_CRON_EXPR, self._tz,
        )

    def _run_pipeline_job(self) -> None:
        """Job body — invoked by APScheduler on a worker thread.

        Reads the singleton ``pipeline_schedule`` row at fire-time, skips
        cleanly when disabled, otherwise calls the orchestrator and
        persists the result via ``PipelineRunRepository`` (same path as
        the interactive POST /pipeline/run BackgroundTask).
        """
        # Lazy imports — scheduler module shouldn't drag in the v2 pipeline
        # package or the LLM stack at import time (tests routinely import
        # scheduler_service without LLM deps installed).
        import traceback
        import uuid
        from app.backend.repositories.pipeline_repository import (
            PipelineRunRepository,
            PipelineScheduleRepository,
        )
        from v2.pipeline import run_pipeline, resolve_analysts

        with self._session_factory() as session:
            cfg = PipelineScheduleRepository(session).get()
            if cfg is None:
                logger.warning("Daily pipeline: schedule singleton missing; skipping")
                return
            if not cfg.enabled:
                logger.info("Daily pipeline: schedule disabled; skipping")
                return

            # Validate template before any scan/LLM work.
            try:
                selected = resolve_analysts(template=cfg.template)
            except ValueError as e:
                logger.error("Daily pipeline: invalid template %r: %s", cfg.template, e)
                return

            run_id = uuid.uuid4().hex
            repo = PipelineRunRepository(session)
            repo.create_pending(
                run_id=run_id,
                scan_date="(deferred)",
                template=cfg.template,
                selected_analysts=selected,
                top_n=cfg.top_n,
                universe=cfg.universe,
            )
            template = cfg.template
            top_n = cfg.top_n
            universe = cfg.universe
            model_name = cfg.model_name
            model_provider = cfg.model_provider

        # Run the pipeline in this thread — APScheduler already gave us a
        # worker thread. orchestrator + LangGraph + DeepSeek roundtrips
        # are all blocking but that's fine here.
        logger.info("Daily pipeline %s: starting (template=%s, top_n=%d, universe=%s)",
                    run_id, template, top_n, universe)

        with self._session_factory() as session:
            PipelineRunRepository(session).mark_running(run_id)

        try:
            result = run_pipeline(
                universe=universe,
                top_n=top_n,
                template=template,
                model_name=model_name,
                model_provider=model_provider,
                persist=False,  # we persist via the repo below
            )
        except Exception as e:
            logger.exception("Daily pipeline %s failed", run_id)
            with self._session_factory() as session:
                PipelineRunRepository(session).mark_error(
                    run_id, f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                )
            return

        with self._session_factory() as session:
            PipelineRunRepository(session).mark_complete(
                run_id,
                watchlist=result.watchlist,
                agent_decisions=result.agent_decisions,
                analyst_signals=result.analyst_signals,
                duration_seconds=result.duration_seconds,
            )
        logger.info("Daily pipeline %s completed in %.1fs (status=%s)",
                    run_id, result.duration_seconds, result.status)

        # Fan out notifications. Dispatcher swallows handler exceptions
        # so a Resend hiccup never kills the cron; wrap once more here
        # to defend against dispatcher-init failure (lazy import).
        try:
            from app.backend.services.notifications import NotificationDispatcher
            NotificationDispatcher(self._session_factory).dispatch(run_id=run_id)
        except Exception:
            logger.exception("Daily pipeline %s: notification dispatch failed", run_id)


# ----------------------------------------------------------------------
# Daily research job — module-level function so tests can patch
# SessionLocal, run_research, and render_html at this module's namespace.
# ----------------------------------------------------------------------


def _run_research_job_body() -> None:
    """Body of the daily research cron.

    Reads the latest COMPLETE PipelineRun row for today, takes its
    watchlist tickers, runs research per ticker, persists each report.

    If no recent pipeline run exists (legacy cron disabled), logs and
    returns — Phase 3 v1 does NOT fall back to running its own scanner.
    That keeps the two cron jobs cleanly independent and limits cost
    surprises when the user has only the research cron enabled.

    Wave 4 tenancy: reports are created under the seed superuser
    (SELECT id FROM users WHERE is_superuser=1 ORDER BY id LIMIT 1).
    Wave 6 will make the cron per-user so each user's cron creates
    under their own id.
    """
    import time
    from datetime import date

    from app.backend.database.models import User as _User

    _logger = logging.getLogger(__name__)

    db = SessionLocal()
    try:
        # Resolve the seed superuser that owns cron-created reports.
        seed_user = (
            db.query(_User)
            .filter(_User.is_superuser.is_(True))
            .order_by(_User.id.asc())
            .first()
        )
        if seed_user is None:
            _logger.warning(
                "research cron: no superuser found; reports will be unowned (user_id=None). "
                "Create a superuser account to fix this."
            )
            owner_id = None
        else:
            owner_id = seed_user.id

        today = date.today().isoformat()
        pipe_repo = PipelineRunRepository(db)
        recent = pipe_repo.list_runs(status="COMPLETE", since=today, limit=1)
        if not recent:
            _logger.info(
                "research cron: no legacy pipeline run for %s - skipping", today
            )
            return
        latest = recent[0]
        tickers = []
        for entry in (latest.watchlist_json or []):
            t = entry.get("ticker") if isinstance(entry, dict) else None
            if t:
                tickers.append(t)
        if not tickers:
            _logger.warning("research cron: latest pipeline run has empty watchlist")
            return

        research_repo = ResearchReportRepository(db)
        for ticker in tickers:
            req = ResearchRequest(
                ticker=ticker,
                holding_status="watching",
                target_position_pct=0.05,
                risk_tolerance="moderate",
                report_goal="new_entry",
                use_personas=True,
                scanner_context={
                    "scan_date": latest.scan_date,
                    "triggered_detectors": [],
                },
            )
            t0 = time.monotonic()
            try:
                state = run_research(req)
            except Exception as e:
                _logger.exception(
                    "research cron: ticker %s failed: %s", ticker, e
                )
                continue
            duration = time.monotonic() - t0
            state["rendered_html"] = render_html(state)
            r_kwargs, p_kwargs = state_to_db_kwargs(state, duration_seconds=duration)
            try:
                research_repo.create_with_plan(report=r_kwargs, plan=p_kwargs, user_id=owner_id)
            except Exception as e:
                _logger.exception(
                    "research cron: persist failed for %s: %s", ticker, e
                )
                continue
            _logger.info(
                "research cron: persisted report for %s (%.1fs)", ticker, duration
            )
    finally:
        db.close()


# ----------------------------------------------------------------------
# Daily screener-snapshot job — module-level function so tests can patch
# SessionLocal, ScreenerRepository, SnapshotBuilder, and AshareMetrics
# at this module's namespace.
# ----------------------------------------------------------------------


def _run_snapshot_job_body() -> None:
    """Build US then CN snapshot; per-market failures log + continue.
    Cleanup deletes rows older than 30 days. One DB session for the whole job.
    """
    from datetime import date as _date

    db = SessionLocal()
    try:
        repo = ScreenerRepository(db)
        try:
            ashare = AshareMetrics()
        except Exception as e:
            logger.warning("AshareMetrics init failed (CN path disabled): %s", e)
            ashare = None
        builder = SnapshotBuilder(ashare_metrics=ashare)
        asof = _date.today()

        for market, kind in (("US", "sp500"), ("CN", "csi300")):
            try:
                rows = builder.build_for_universe(market, kind, asof)
                inserted = repo.bulk_upsert(rows)
                logger.info("screener snapshot %s: %d rows", market, inserted)
            except Exception as e:
                logger.exception("screener snapshot %s failed: %s", market, e)

        deleted = repo.cleanup_old_snapshots(keep_days=30)
        logger.info("screener snapshot cleanup deleted %d old rows", deleted)
    finally:
        db.close()


# ----------------------------------------------------------------------
# Daily screener-preset job — module-level function so tests can patch
# SessionLocal, ScreenerPresetRepository, ScreenerRepository, and
# NotificationDispatcher at this module's namespace.
# ----------------------------------------------------------------------


def _run_preset_job_body() -> None:
    """Run every schedule-enabled screener preset against the latest snapshot;
    notify on non-empty matches. Per-preset failures log + continue."""
    from datetime import date as _date, datetime as _dt, timezone as _tz

    db = SessionLocal()
    try:
        presets = ScreenerPresetRepository(db).list_enabled()
        screener = ScreenerRepository(db)
        dispatcher = NotificationDispatcher(SessionLocal)
        for p in presets:
            try:
                market = [p.market] if p.market else None
                rows, total = screener.query(
                    market=market, filters=p.filters_json or {},
                    sort_by=p.sort_by, sort_dir=p.sort_dir, limit=200)
                ScreenerPresetRepository(db).mark_run(
                    p.id, match_count=total, when=_dt.now(_tz.utc))
                if total > 0 and (p.notify_channels or []):
                    payload = {
                        "preset_id": p.id,
                        "preset_name": p.name,
                        "match_count": total,
                        "snapshot_date": (rows[0].snapshot_date.isoformat()
                                          if rows else _date.today().isoformat()),
                        "rows": [{"ticker": r.ticker,
                                  "price": str(r.price) if r.price is not None else None,
                                  "pe_ttm": str(r.pe_ttm) if r.pe_ttm is not None else None,
                                  "change_pct": str(r.change_pct) if r.change_pct is not None else None}
                                 for r in rows[:25]],
                    }
                    dispatcher.dispatch_screener_match(payload=payload,
                                                       event_type="screener.match")
            except Exception as e:
                logger.exception("preset %s failed: %s", getattr(p, "id", "?"), e)
    finally:
        db.close()


# ----------------------------------------------------------------------
# Process-wide singleton for FastAPI Depends() consumption
# ----------------------------------------------------------------------

_scheduler_service: SchedulerService | None = None


def init_scheduler_service(
    session_factory: Callable[[], Session],
    scanner_service: ScannerService,
) -> SchedulerService:
    """Create and store the process-wide SchedulerService."""
    global _scheduler_service
    _scheduler_service = SchedulerService(session_factory, scanner_service)
    return _scheduler_service


def get_scheduler_service() -> SchedulerService:
    """FastAPI dependency. Raises if ``init_scheduler_service`` wasn't called."""
    if _scheduler_service is None:
        raise RuntimeError("SchedulerService not initialized (call init_scheduler_service first)")
    return _scheduler_service
