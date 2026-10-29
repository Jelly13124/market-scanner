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
import os
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

# Daily research cron: 16:35 ET weekdays. Reads available watchlist entries.
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

# Paper-trading forward test (Task 8).
#   Weekly rebalance: Mondays 17:00 ET, after the prior week's close has settled.
#   Daily marks:      every weekday 17:05 ET, after the US close.
# Both job bodies live in src.paper_trading.run as zero-arg callables and are
# idempotent (run_week per (sleeve, week_key); mark_all upserts per (sleeve, day)).
PAPER_WEEKLY_CRON_EXPR = "0 17 * * 1"
PAPER_WEEKLY_JOB_ID = "paper_weekly"
PAPER_MARKS_CRON_EXPR = "5 17 * * 1-5"
PAPER_MARKS_JOB_ID = "paper_daily_marks"


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

        # Register the singleton daily screener-snapshot cron — 22:00 ET
        # every day, after both US and CN markets have closed.
        try:
            self._register_snapshot_job()
        except Exception as e:
            logger.warning("Failed to register screener snapshot job: %s", e)

        # Register the paper-trading forward-test crons (weekly rebalance +
        # daily marks). Both bodies are zero-arg callables in
        # src.paper_trading.run and are idempotent, so retries are safe.
        try:
            if os.getenv("ENABLE_HOST_PAPER_JOBS", "false").lower() == "true":
                self._register_paper_trading_jobs()
        except Exception as e:
            logger.warning("Failed to register paper-trading jobs: %s", e)

        # Register a per-preset cron for each enabled screener preset (each in
        # its owner's timezone). Replaces the old single global 22:05 preset
        # cron so users can pick a per-preset frequency/time; the snapshot cron
        # above still rebuilds the rows the presets filter.
        try:
            with self._session_factory() as session:
                presets = ScreenerPresetRepository(session).list_enabled()
            for p in presets:
                try:
                    self.register_screener_preset(p)
                except Exception as e:
                    logger.warning("Failed to register screener preset %s: %s", p.id, e)
        except Exception as e:
            logger.warning("Failed to load screener presets: %s", e)

        # Register each user's enabled report-delivery schedules (Stage 3).
        try:
            from app.backend.database.models import ReportSchedule

            with self._session_factory() as session:
                schedules = session.query(ReportSchedule).filter(ReportSchedule.is_enabled.is_(True)).all()
            for s in schedules:
                try:
                    self.register_report_schedule(s)
                except Exception as e:
                    logger.warning("Failed to register report schedule %s: %s", s.id, e)
        except Exception as e:
            logger.warning("Failed to load report schedules: %s", e)

        logger.info(
            "SchedulerService started (tz=%s); registered %d/%d enabled scanner configs + daily pipeline + daily research",
            self._tz,
            registered,
            len(configs),
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

    def reregister_user_jobs(self, user_id) -> None:
        """Re-register every cron owned by ``user_id`` (enabled scanner configs
        + enabled report schedules) so a timezone change takes effect without a
        restart. Each ``_register`` / ``register_report_schedule`` re-resolves
        the user's tz via ``_user_tz``. Per-job failures are logged, not raised,
        so one bad cron can't abort the rest."""
        from app.backend.database.models import ReportSchedule, ScreenerPreset

        with self._session_factory() as session:
            configs = ScannerConfigRepository(session).list_for_user(user_id, enabled_only=True)
            schedules = session.query(ReportSchedule).filter(ReportSchedule.user_id == user_id, ReportSchedule.is_enabled.is_(True)).all()
            presets = session.query(ScreenerPreset).filter(ScreenerPreset.user_id == user_id, ScreenerPreset.schedule_enabled.is_(True)).all()

        for cfg in configs:
            try:
                self._register(cfg)
            except Exception as e:
                logger.warning("reregister_user_jobs: scanner config %s failed: %s", cfg.id, e)
        for sched in schedules:
            try:
                self.register_report_schedule(sched)
            except Exception as e:
                logger.warning("reregister_user_jobs: report schedule %s failed: %s", sched.id, e)
        for preset in presets:
            try:
                self.register_screener_preset(preset)
            except Exception as e:
                logger.warning("reregister_user_jobs: screener preset %s failed: %s", preset.id, e)

    def run_now(self, config_id: int, *, deliver_emails: bool = True) -> int:
        """Trigger a manual scan; return the new ``run_id`` immediately.

        The scan runs on a background daemon thread inside ``ScannerService``;
        clients subscribe to ``/scanner/runs/{run_id}/stream`` for live
        progress.

        ``deliver_emails`` is forwarded to ``execute_async`` — when False the
        post-scan workflow skips emailing the watchlist/reports. Manual runs
        opt in via the route's ``send_email`` query param (default off); cron
        keeps the True default so scheduled scans always deliver.
        """
        return self._scanner_service.execute_async(config_id, deliver_emails=deliver_emails)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _job_id(config_id: int) -> str:
        return f"scanner-config-{config_id}"

    def _user_tz(self, user_id) -> str:
        """Resolve a user's preferred IANA timezone, falling back to the
        global default when the user (or their tz) is missing. APScheduler's
        ``from_crontab`` accepts a tz-name string, so we return one."""
        from app.backend.database.models import User

        with self._session_factory() as s:
            u = s.query(User).filter(User.id == user_id).first()
            return (u.timezone if u and u.timezone else None) or self._tz

    def _register(self, config: ScannerConfig) -> None:
        tz = self._user_tz(config.user_id)
        try:
            trigger = CronTrigger.from_crontab(config.cron_expr, timezone=tz)
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
            coalesce=True,  # collapse missed fires into one
        )
        logger.info(
            "Registered scanner job %s (cron=%r, tz=%s)",
            job_id,
            config.cron_expr,
            tz,
        )

    def _run_job(self, config_id: int) -> None:
        """Job body — invoked by APScheduler on a worker thread."""
        try:
            logger.info("Cron trigger: starting scan for config %s", config_id)
            from datetime import datetime, timezone
            slot = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
            run_id = self._scanner_service.execute(config_id, execution_key=f'scheduled:{config_id}:{slot}')
            logger.info("Cron scan for config %s completed (run_id=%s)", config_id, run_id)
        except Exception:
            # Exceptions inside cron jobs would otherwise vanish into APScheduler's
            # error log — log them explicitly for visibility.
            logger.exception("Cron scan for config %s failed", config_id)

    # ------------------------------------------------------------------
    # Report-delivery schedules (Stage 3) — called by REST routes after CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _report_schedule_job_id(schedule_id: int) -> str:
        return f"report-schedule-{schedule_id}"

    def register_report_schedule(self, schedule) -> None:
        """(Re)register a report schedule's cron. No-op when disabled."""
        self.unregister_report_schedule(schedule.id)
        if not schedule.is_enabled:
            return
        tz = self._user_tz(schedule.user_id)
        try:
            trigger = CronTrigger.from_crontab(schedule.cron_expr, timezone=tz)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid cron expression {schedule.cron_expr!r}: {e}") from e
        job_id = self._report_schedule_job_id(schedule.id)
        self._scheduler.add_job(
            _run_report_schedule_job,
            trigger=trigger,
            id=job_id,
            args=[schedule.id],
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=300,
            coalesce=True,
        )
        logger.info("Registered report-schedule job %s (cron=%r, tz=%s)", job_id, schedule.cron_expr, tz)

    def unregister_report_schedule(self, schedule_id: int) -> None:
        job_id = self._report_schedule_job_id(schedule_id)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("Unregistered report-schedule job %s", job_id)

    # ------------------------------------------------------------------
    # Per-preset screener crons — called by REST routes after preset CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _screener_preset_job_id(preset_id: int) -> str:
        return f"screener-preset-{preset_id}"

    def register_screener_preset(self, preset) -> None:
        """(Re)register a screener preset's per-preset cron in the owner's tz.
        No-op (and removes any existing job) when the preset's schedule is
        disabled. Mirrors register_report_schedule."""
        self.unregister_screener_preset(preset.id)
        if not preset.schedule_enabled:
            return
        tz = self._user_tz(preset.user_id)
        try:
            trigger = CronTrigger.from_crontab(preset.cron_expr, timezone=tz)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid cron expression {preset.cron_expr!r}: {e}") from e
        job_id = self._screener_preset_job_id(preset.id)
        self._scheduler.add_job(
            _run_single_preset_job,
            trigger=trigger,
            id=job_id,
            args=[preset.id],
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
            coalesce=True,
        )
        logger.info("Registered screener-preset job %s (cron=%r, tz=%s)", job_id, preset.cron_expr, tz)

    def unregister_screener_preset(self, preset_id: int) -> None:
        job_id = self._screener_preset_job_id(preset_id)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("Unregistered screener-preset job %s", job_id)

    # ------------------------------------------------------------------
    # Daily scanner→agent pipeline job
    # ------------------------------------------------------------------

    def _register_pipeline_job(self) -> None:
        """Compatibility hook: legacy Analyze cron is no longer registered."""
        return

    def _register_research_job(self) -> None:
        """Retired legacy research cron; user report schedules use run_sop."""
        return

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
            SCREENER_SNAPSHOT_JOB_ID,
            SCREENER_SNAPSHOT_CRON_EXPR,
            self._tz,
        )

    def _register_paper_trading_jobs(self) -> None:
        """Register the paper-trading weekly-rebalance + daily-marks crons.

        The job bodies are zero-arg callables imported lazily inside this method
        (``src.paper_trading.run``) so the scheduler module doesn't pull the
        scanner/agent/data stack in at import time — same lazy-body discipline as
        the other singleton crons here.
        """
        from src.paper_trading.run import paper_daily_marks_job, paper_weekly_job

        weekly_trigger = CronTrigger.from_crontab(PAPER_WEEKLY_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            paper_weekly_job,
            trigger=weekly_trigger,
            id=PAPER_WEEKLY_JOB_ID,
            max_instances=1,
            misfire_grace_time=3600,
            coalesce=True,
            replace_existing=True,
        )
        marks_trigger = CronTrigger.from_crontab(PAPER_MARKS_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            paper_daily_marks_job,
            trigger=marks_trigger,
            id=PAPER_MARKS_JOB_ID,
            max_instances=1,
            misfire_grace_time=3600,
            coalesce=True,
            replace_existing=True,
        )
        logger.info(
            "Registered paper-trading jobs %s (cron=%r) + %s (cron=%r), tz=%s",
            PAPER_WEEKLY_JOB_ID,
            PAPER_WEEKLY_CRON_EXPR,
            PAPER_MARKS_JOB_ID,
            PAPER_MARKS_CRON_EXPR,
            self._tz,
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
            SCREENER_PRESET_JOB_ID,
            SCREENER_PRESET_CRON_EXPR,
            self._tz,
        )

    def _run_pipeline_job(self) -> None:
        """Compatibility hook for stale scheduler callbacks; performs no work."""
        logger.info("Legacy LangGraph Analyze pipeline is retired; skipping scheduled run")


# ----------------------------------------------------------------------
# Daily research job — module-level function so tests can patch
# SessionLocal, run_research, and render_html at this module's namespace.
# ----------------------------------------------------------------------


def _run_report_schedule_job(schedule_id: int) -> None:
    """Body of a per-user scheduled-report cron: run the SOP for each ticker with
    the owner's keys and email each rendered report to their verified recipients.

    Runs on an APScheduler worker thread — must never let an exception escape.
    Skips entirely when the schedule is disabled/missing, has no tickers, or the
    owner has no verified recipients (nothing to deliver to). Mirrors the
    /research/analyze route's per-user-key + run_sop + render_sop flow.
    """
    _logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        from app.backend.database.models import ReportSchedule

        sched = db.query(ReportSchedule).filter(ReportSchedule.id == schedule_id).first()
        if sched is None or not sched.is_enabled:
            return
        user_id = sched.user_id
        tickers = [t for t in (sched.tickers or []) if t]
        if not tickers:
            return

        from app.backend.services.report_delivery import email_report_html, verified_recipients

        if not verified_recipients(db, user_id):
            _logger.info("report schedule %s: no verified recipients; skipping", schedule_id)
            return

        from app.backend.services.api_key_service import ApiKeyService
        from src.research.html_render import render_sop
        from src.research.models import AnalyzeRequest
        from src.research.sop_orchestrator import run_sop

        api_keys = ApiKeyService(db, user_id).get_api_keys_dict()
        for ticker in tickers:
            try:
                req = AnalyzeRequest(
                    ticker=ticker,
                    objective="general_research",
                    position_budget_usd=None,
                    already_holds=False,
                    cost_basis_usd=None,
                    risk_tolerance="balanced",
                    use_personas=False,
                    report_language=(sched.report_language or "en"),
                )
                report = run_sop(req, api_keys=api_keys, owner_id=user_id)
                html = render_sop(report)
                res = email_report_html(db, user_id, ticker=ticker, html=html)
                _logger.info(
                    "report schedule %s: %s sent=%s failed=%s",
                    schedule_id,
                    ticker,
                    res["sent"],
                    res["failed"],
                )
            except Exception:
                _logger.exception("report schedule %s: ticker %s failed", schedule_id, ticker)

        from datetime import datetime, timezone

        sched.last_run_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        _logger.exception("report schedule job %s crashed", schedule_id)
    finally:
        db.close()


def _run_research_job_body() -> None:
    """Compatibility callback for retired global research jobs; performs no work."""
    logger.info('Legacy global research cron is retired; use per-user Analyze schedules')


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
    notify on non-empty matches. Per-preset failures log + continue.

    Per-user tenancy: this is the one cron that iterates ALL users' enabled
    presets (each user enabling a preset is their opt-in). A match notifies
    only the matched preset's OWNER (``dispatch_screener_match(user_id=...)``
    scopes the fan-out) — never another tenant.

    Deferred dependency: per-user API-key usage is NOT yet wired. The
    snapshot the presets query is built by the global snapshot cron using
    HOST .env keys; presets only filter pre-built rows so they consume no
    per-user keys today. When key-wiring lands and presets trigger any
    paid per-user work, skip owners without keys + use each owner's keys.
    """
    from datetime import date as _date, datetime as _dt, timezone as _tz

    db = SessionLocal()
    try:
        presets = ScreenerPresetRepository(db).list_enabled()
        screener = ScreenerRepository(db)
        dispatcher = NotificationDispatcher(SessionLocal)
        for p in presets:
            try:
                market = [p.market] if p.market else None
                rows, total = screener.query(market=market, filters=p.filters_json or {}, sort_by=p.sort_by, sort_dir=p.sort_dir, limit=200)
                ScreenerPresetRepository(db).mark_run(p.id, match_count=total, when=_dt.now(_tz.utc))
                if total > 0 and (p.notify_channels or []):
                    payload = {
                        "preset_id": p.id,
                        "preset_name": p.name,
                        "match_count": total,
                        "snapshot_date": (rows[0].snapshot_date.isoformat() if rows else _date.today().isoformat()),
                        "rows": [{"ticker": r.ticker, "price": str(r.price) if r.price is not None else None, "pe_ttm": str(r.pe_ttm) if r.pe_ttm is not None else None, "change_pct": str(r.change_pct) if r.change_pct is not None else None} for r in rows[:25]],
                    }
                    # Owner-scoped: notify only this preset's owner's channels.
                    dispatcher.dispatch_screener_match(payload=payload, event_type="screener.match", user_id=p.user_id)
            except Exception as e:
                logger.exception("preset %s failed: %s", getattr(p, "id", "?"), e)
    finally:
        db.close()


def _run_single_preset_job(preset_id: int) -> None:
    """Run ONE schedule-enabled screener preset against the latest snapshot on
    its own per-preset cron; notify the owner on a non-empty match. Mirrors
    _run_preset_job_body but for a single preset (per-user cadence). Failures
    log + swallow so APScheduler never sees a raised job."""
    from datetime import date as _date, datetime as _dt, timezone as _tz

    from app.backend.database.models import ScreenerPreset

    db = SessionLocal()
    try:
        p = db.query(ScreenerPreset).filter(ScreenerPreset.id == preset_id).first()
        if p is None or not p.schedule_enabled:
            return
        screener = ScreenerRepository(db)
        market = [p.market] if p.market else None
        rows, total = screener.query(
            market=market,
            filters=p.filters_json or {},
            sort_by=p.sort_by,
            sort_dir=p.sort_dir,
            limit=200,
        )
        ScreenerPresetRepository(db).mark_run(p.id, match_count=total, when=_dt.now(_tz.utc))
        if total > 0 and (p.notify_channels or []):
            payload = {
                "preset_id": p.id,
                "preset_name": p.name,
                "match_count": total,
                "snapshot_date": (rows[0].snapshot_date.isoformat() if rows else _date.today().isoformat()),
                "rows": [
                    {
                        "ticker": r.ticker,
                        "price": str(r.price) if r.price is not None else None,
                        "pe_ttm": str(r.pe_ttm) if r.pe_ttm is not None else None,
                        "change_pct": str(r.change_pct) if r.change_pct is not None else None,
                    }
                    for r in rows[:25]
                ],
            }
            NotificationDispatcher(SessionLocal).dispatch_screener_match(
                payload=payload,
                event_type="screener.match",
                user_id=p.user_id,
            )
    except Exception as e:
        logger.exception("screener preset %s failed: %s", preset_id, e)
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
