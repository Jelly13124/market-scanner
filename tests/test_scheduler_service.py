"""Unit tests for SchedulerService.

Avoids actually starting BackgroundScheduler — we mock the underlying scheduler
to verify register / unregister / reschedule semantics deterministically.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base
from app.backend.repositories.scanner_repository import ScannerConfigRepository
from app.backend.services.scanner_service import ScannerService
from app.backend.services.scheduler_service import (
    DEFAULT_TIMEZONE,
    SchedulerService,
    get_scheduler_service,
    init_scheduler_service,
)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield SessionLocal
    engine.dispose()


@pytest.fixture()
def scanner_service(session_factory):
    return ScannerService(session_factory)


@pytest.fixture()
def svc(session_factory, scanner_service):
    """A SchedulerService with the APScheduler instance replaced by a MagicMock."""
    with patch("app.backend.services.scheduler_service.BackgroundScheduler") as ctor:
        ctor.return_value = MagicMock()
        s = SchedulerService(session_factory, scanner_service)
        s._scheduler = ctor.return_value  # ensure tests can interrogate the mock
        yield s


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_marks_started(self, svc):
        svc.start()
        assert svc.is_started is True
        svc._scheduler.start.assert_called_once()

    def test_start_idempotent(self, svc):
        svc.start()
        svc.start()
        svc._scheduler.start.assert_called_once()

    def test_shutdown_marks_stopped(self, svc):
        svc.start()
        svc.shutdown()
        assert svc.is_started is False
        svc._scheduler.shutdown.assert_called_once_with(wait=False)

    def test_shutdown_before_start_is_noop(self, svc):
        svc.shutdown()
        svc._scheduler.shutdown.assert_not_called()

    def test_start_registers_enabled_configs(self, svc, session_factory):
        with session_factory() as session:
            ScannerConfigRepository(session).create(name="a", universe_kind="sp500", is_enabled=True, user_id=1)
            ScannerConfigRepository(session).create(name="b", universe_kind="sp500", is_enabled=False, user_id=1)
            ScannerConfigRepository(session).create(name="c", universe_kind="sp500", is_enabled=True, user_id=1)
        svc.start()
        # 2 enabled scanner configs + the screener snapshot. Host paper jobs
        # are disabled by default. Screener presets
        # now register PER-PRESET crons on demand; none are enabled here, so the old
        # single global preset job is gone.
        assert svc._scheduler.add_job.call_count == 3
        job_ids = {call.kwargs.get("id") for call in svc._scheduler.add_job.call_args_list}
        assert "daily-pipeline" not in job_ids
        assert "research_daily" not in job_ids
        assert "paper_weekly" not in job_ids
        assert "paper_daily_marks" not in job_ids

    def test_start_excludes_retired_pipeline_with_no_scanner_configs(self, svc):
        """Active scheduled jobs register; retired pipeline does not."""
        svc.start()
        # Only the screener snapshot registers by default.
        # (Screener presets register per-preset;
        # none enabled here.)
        assert svc._scheduler.add_job.call_count == 1
        job_ids = {call.kwargs.get("id") for call in svc._scheduler.add_job.call_args_list}
        assert "daily-pipeline" not in job_ids
        assert "research_daily" not in job_ids
        assert "paper_weekly" not in job_ids
        assert "paper_daily_marks" not in job_ids


# ---------------------------------------------------------------------------
# register / unregister / reschedule
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_adds_job(self, svc, session_factory):
        with session_factory() as session:
            cfg = ScannerConfigRepository(session).create(
                name="x",
                universe_kind="sp500",
                cron_expr="0 21 * * 1-5",
                user_id=1,
            )
        svc.register_config(cfg)
        assert svc._scheduler.add_job.called
        kwargs = svc._scheduler.add_job.call_args.kwargs
        assert kwargs["id"] == f"scanner-config-{cfg.id}"
        assert kwargs["replace_existing"] is True
        assert kwargs["max_instances"] == 1
        assert kwargs["args"] == [cfg.id]

    def test_register_disabled_unregisters(self, svc, session_factory):
        with session_factory() as session:
            cfg = ScannerConfigRepository(session).create(
                name="x",
                universe_kind="sp500",
                is_enabled=False,
                user_id=1,
            )
        svc.register_config(cfg)
        # Disabled config -> should call remove_job (idempotently), not add_job.
        svc._scheduler.add_job.assert_not_called()
        svc._scheduler.remove_job.assert_called_once_with(f"scanner-config-{cfg.id}")

    def test_invalid_cron_raises(self, svc, session_factory):
        with session_factory() as session:
            cfg = ScannerConfigRepository(session).create(
                name="x",
                universe_kind="sp500",
                cron_expr="this is not cron",
                user_id=1,
            )
        with pytest.raises(ValueError, match="Invalid cron"):
            svc.register_config(cfg)
        svc._scheduler.add_job.assert_not_called()

    def test_unregister_is_idempotent_when_missing(self, svc):
        # APScheduler raises if the job doesn't exist; SchedulerService swallows it.
        svc._scheduler.remove_job.side_effect = Exception("JobLookupError")
        svc.unregister_config(999)  # should not raise

    def test_reschedule_is_register(self, svc, session_factory):
        with session_factory() as session:
            cfg = ScannerConfigRepository(session).create(
                name="x",
                universe_kind="sp500",
                cron_expr="0 21 * * 1-5",
                user_id=1,
            )
        svc.reschedule_config(cfg)
        assert svc._scheduler.add_job.called


# ---------------------------------------------------------------------------
# Manual run_now passes through to ScannerService
# ---------------------------------------------------------------------------


class TestRunNow:
    def test_run_now_calls_execute_async(self, session_factory, monkeypatch):
        # run_now must dispatch via execute_async (returns immediately with run_id)
        # — execute() would block on the entire scan, breaking the REST UX.
        scanner = MagicMock()
        scanner.execute_async.return_value = 42
        with patch("app.backend.services.scheduler_service.BackgroundScheduler") as ctor:
            ctor.return_value = MagicMock()
            svc = SchedulerService(session_factory, scanner)
        result = svc.run_now(7)
        assert result == 42
        scanner.execute_async.assert_called_once_with(7, deliver_emails=True)
        scanner.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Process-wide singleton helpers
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_before_init_raises(self):
        # Reset module state to ensure a clean check.
        import app.backend.services.scheduler_service as mod

        mod._scheduler_service = None
        with pytest.raises(RuntimeError, match="not initialized"):
            get_scheduler_service()

    def test_init_returns_instance(self, session_factory, scanner_service):
        with patch("app.backend.services.scheduler_service.BackgroundScheduler"):
            svc = init_scheduler_service(session_factory, scanner_service)
        assert isinstance(svc, SchedulerService)
        assert get_scheduler_service() is svc


# ---------------------------------------------------------------------------
# Timezone default
# ---------------------------------------------------------------------------


class TestTimezone:
    def test_default_is_new_york(self, session_factory, scanner_service):
        with patch("app.backend.services.scheduler_service.BackgroundScheduler") as ctor:
            SchedulerService(session_factory, scanner_service)
        # Constructor called with timezone kwarg.
        kwargs = ctor.call_args.kwargs
        assert kwargs.get("timezone") == DEFAULT_TIMEZONE


# ---------------------------------------------------------------------------
# Daily pipeline job body
# ---------------------------------------------------------------------------


@pytest.fixture()
def schedule_singleton(session_factory):
    """Seed the singleton pipeline_schedule row that production normally
    gets from the Alembic migration. Also seeds a superuser (id=1) so the
    cron's seed-owner resolution stamps the produced PipelineRun (required
    now that pipeline_runs.user_id is NOT NULL)."""
    from app.backend.database.models import PipelineSchedule, User

    with session_factory() as session:
        session.add(User(id=1, email="owner@local", is_active=True, is_superuser=True))
        session.add(
            PipelineSchedule(
                id=1,
                enabled=False,
                top_n=5,
                template="balanced",
                universe="nasdaq100",
                model_name="gpt-4.1",
                model_provider="OpenAI",
                user_id=1,
            )
        )
        session.commit()
    return session_factory


class TestDailyPipelineJob:
    def test_stale_enabled_schedule_cannot_create_runs(self, svc, schedule_singleton):
        from app.backend.database.models import PipelineRun, PipelineSchedule

        with schedule_singleton() as session:
            session.query(PipelineSchedule).first().enabled = True
            session.commit()
        with patch("v2.pipeline.run_pipeline") as run:
            svc._run_pipeline_job()
            run.assert_not_called()
        with schedule_singleton() as session:
            assert session.query(PipelineRun).count() == 0
