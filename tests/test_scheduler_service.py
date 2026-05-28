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
            ScannerConfigRepository(session).create(name="a", universe_kind="sp500", is_enabled=True)
            ScannerConfigRepository(session).create(name="b", universe_kind="sp500", is_enabled=False)
            ScannerConfigRepository(session).create(name="c", universe_kind="sp500", is_enabled=True)
        svc.start()
        # 2 enabled scanner configs + 1 singleton daily pipeline job + 1 daily research job + 1 screener snapshot job
        assert svc._scheduler.add_job.call_count == 5
        job_ids = {call.kwargs.get("id") for call in svc._scheduler.add_job.call_args_list}
        assert "daily-pipeline" in job_ids
        assert "research_daily" in job_ids

    def test_start_registers_daily_pipeline_even_with_no_scanner_configs(self, svc):
        """Pipeline and research jobs are independent of scanner configs —
        both must register even when no scanner configs exist."""
        svc.start()
        # No configs, but daily pipeline + daily research + screener snapshot still registered
        assert svc._scheduler.add_job.call_count == 3
        job_ids = {call.kwargs.get("id") for call in svc._scheduler.add_job.call_args_list}
        assert "daily-pipeline" in job_ids
        assert "research_daily" in job_ids
        # Verify pipeline job properties
        pipeline_call = next(
            c for c in svc._scheduler.add_job.call_args_list
            if c.kwargs.get("id") == "daily-pipeline"
        )
        assert pipeline_call.kwargs["max_instances"] == 1
        assert pipeline_call.kwargs["misfire_grace_time"] == 600


# ---------------------------------------------------------------------------
# register / unregister / reschedule
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_adds_job(self, svc, session_factory):
        with session_factory() as session:
            cfg = ScannerConfigRepository(session).create(
                name="x", universe_kind="sp500", cron_expr="0 21 * * 1-5",
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
                name="x", universe_kind="sp500", is_enabled=False,
            )
        svc.register_config(cfg)
        # Disabled config -> should call remove_job (idempotently), not add_job.
        svc._scheduler.add_job.assert_not_called()
        svc._scheduler.remove_job.assert_called_once_with(f"scanner-config-{cfg.id}")

    def test_invalid_cron_raises(self, svc, session_factory):
        with session_factory() as session:
            cfg = ScannerConfigRepository(session).create(
                name="x", universe_kind="sp500", cron_expr="this is not cron",
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
                name="x", universe_kind="sp500", cron_expr="0 21 * * 1-5",
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
        scanner.execute_async.assert_called_once_with(7)
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
    gets from the Alembic migration."""
    from app.backend.database.models import PipelineSchedule
    with session_factory() as session:
        session.add(PipelineSchedule(
            id=1, enabled=False, top_n=5, template="balanced",
            universe="nasdaq100", model_name="gpt-4.1", model_provider="OpenAI",
        ))
        session.commit()
    return session_factory


class TestDailyPipelineJob:
    def test_skips_when_disabled(self, svc, schedule_singleton):
        # enabled=False is the seeded default — pipeline body should log
        # and return without calling run_pipeline.
        with patch("v2.pipeline.run_pipeline") as mock_run:
            svc._run_pipeline_job()
            mock_run.assert_not_called()

    def test_skips_when_schedule_row_missing(self, svc, session_factory):
        # No seed row — body should bail without raising.
        with patch("v2.pipeline.run_pipeline") as mock_run:
            svc._run_pipeline_job()
            mock_run.assert_not_called()

    def test_skips_when_template_unknown(self, svc, session_factory):
        from app.backend.database.models import PipelineSchedule
        with session_factory() as session:
            session.add(PipelineSchedule(
                id=1, enabled=True, top_n=5, template="bogus_template",
                universe="nasdaq100", model_name="gpt-4.1",
                model_provider="OpenAI",
            ))
            session.commit()
        with patch("v2.pipeline.run_pipeline") as mock_run:
            svc._run_pipeline_job()
            mock_run.assert_not_called()

    def test_runs_pipeline_and_marks_complete_when_enabled(
        self, svc, schedule_singleton,
    ):
        from app.backend.database.models import PipelineRun, PipelineSchedule
        from v2.pipeline.orchestrator import PipelineResult

        # Flip the singleton to enabled.
        with schedule_singleton() as session:
            row = session.query(PipelineSchedule).filter(PipelineSchedule.id == 1).first()
            row.enabled = True
            row.template = "quick"
            row.top_n = 3
            session.commit()

        fake_result = PipelineResult(
            run_id="ignored",
            scan_date="2024-08-01",
            template="quick",
            selected_analysts=["scanner_signal", "fundamentals_analyst"],
            universe="nasdaq100", top_n=3,
            watchlist=[{"ticker": "AAPL"}],
            agent_decisions={"AAPL": {"action": "buy"}},
            analyst_signals={"scanner_signal_agent": {"AAPL": {"signal": "bullish"}}},
            duration_seconds=12.5,
        )
        with patch("v2.pipeline.run_pipeline", return_value=fake_result) as mock_run:
            svc._run_pipeline_job()
            mock_run.assert_called_once()
            # Schedule values flowed through to run_pipeline kwargs.
            kw = mock_run.call_args.kwargs
            assert kw["template"] == "quick"
            assert kw["top_n"] == 3
            assert kw["universe"] == "nasdaq100"
            assert kw["persist"] is False  # job persists via repo

        # A COMPLETE row should now exist in pipeline_runs.
        with schedule_singleton() as session:
            rows = session.query(PipelineRun).all()
            assert len(rows) == 1
            assert rows[0].status == "COMPLETE"
            assert rows[0].duration_seconds == 12.5
            assert rows[0].agent_decisions_json == {"AAPL": {"action": "buy"}}
            assert rows[0].template == "quick"

    def test_marks_error_when_pipeline_raises(self, svc, schedule_singleton):
        from app.backend.database.models import PipelineRun, PipelineSchedule
        with schedule_singleton() as session:
            row = session.query(PipelineSchedule).filter(PipelineSchedule.id == 1).first()
            row.enabled = True
            row.template = "quick"
            session.commit()

        def boom(**kw):
            raise RuntimeError("simulated upstream failure")

        with patch("v2.pipeline.run_pipeline", side_effect=boom):
            svc._run_pipeline_job()

        with schedule_singleton() as session:
            rows = session.query(PipelineRun).all()
            assert len(rows) == 1
            assert rows[0].status == "ERROR"
            assert "simulated upstream failure" in rows[0].error
