"""Unit tests for v2 pipeline repositories.

Uses an in-memory SQLite engine to avoid touching the dev/prod hedge_fund.db.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, PipelineSchedule
from app.backend.repositories.pipeline_repository import (
    PipelineRunRepository,
    PipelineScheduleRepository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    # Seed singleton schedule row — the alembic migration does this in
    # production; tests start from a clean :memory: DB and need the seed.
    session.add(
        PipelineSchedule(
            id=1,
            enabled=False,
            top_n=5,
            template="balanced",
            universe="nasdaq100",
            model_name="gpt-4.1",
            model_provider="OpenAI",
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def runs(db_session):
    return PipelineRunRepository(db_session)


@pytest.fixture()
def schedule(db_session):
    return PipelineScheduleRepository(db_session)


# ---------------------------------------------------------------------------
# PipelineRunRepository — lifecycle
# ---------------------------------------------------------------------------


class TestPipelineRunLifecycle:
    def test_create_pending_persists_basic_fields(self, runs):
        run = runs.create_pending(
            run_id="abc123",
            scan_date="2024-08-01",
            template="quick",
            selected_analysts=["scanner_signal", "fundamentals_analyst"],
            top_n=5,
            universe="nasdaq100",
        )
        assert run.id == "abc123"
        assert run.status == "PENDING"
        assert run.scan_date == "2024-08-01"
        assert run.template == "quick"
        assert run.top_n == 5
        # JSON roundtrip preserves list
        assert run.selected_analysts == ["scanner_signal", "fundamentals_analyst"]
        # Created_at populated by server_default
        assert run.created_at is not None
        # No completion fields yet
        assert run.started_at is None
        assert run.completed_at is None

    def test_mark_running_sets_started_at(self, runs):
        runs.create_pending(run_id="r1", scan_date="2024-08-01", template="quick", selected_analysts=["scanner_signal"], top_n=1, universe="nasdaq100")
        updated = runs.mark_running("r1")
        assert updated.status == "RUNNING"
        assert updated.started_at is not None

    def test_mark_complete_writes_blobs_and_duration(self, runs):
        runs.create_pending(run_id="r1", scan_date="2024-08-01", template="quick", selected_analysts=["scanner_signal"], top_n=2, universe="nasdaq100")
        runs.mark_running("r1")
        watchlist = [{"ticker": "AAPL", "rank": 1, "composite_score": 87.5}]
        decisions = {"AAPL": {"action": "buy", "quantity": 10}}
        signals = {"scanner_signal_agent": {"AAPL": {"signal": "bullish", "confidence": 88, "reasoning": "x"}}}
        updated = runs.mark_complete(
            "r1",
            watchlist=watchlist,
            agent_decisions=decisions,
            analyst_signals=signals,
            duration_seconds=12.5,
        )
        assert updated.status == "COMPLETE"
        assert updated.completed_at is not None
        assert updated.duration_seconds == 12.5
        # JSON roundtrip preserves nested structure
        assert updated.watchlist_json == watchlist
        assert updated.agent_decisions_json == decisions
        assert updated.analyst_signals_json == signals

    def test_mark_error_truncates_long_messages(self, runs):
        runs.create_pending(run_id="r1", scan_date="2024-08-01", template="quick", selected_analysts=["scanner_signal"], top_n=1, universe="nasdaq100")
        big = "x" * 10_000
        updated = runs.mark_error("r1", big)
        assert updated.status == "ERROR"
        assert len(updated.error) == 5000  # capped per repo

    def test_mark_running_missing_run_returns_none(self, runs):
        assert runs.mark_running("does_not_exist") is None


# ---------------------------------------------------------------------------
# PipelineRunRepository — listing + filtering
# ---------------------------------------------------------------------------


class TestPipelineRunListing:
    def test_list_runs_newest_first(self, runs, db_session):
        # SQLite's CURRENT_TIMESTAMP has only second-precision; if we relied
        # on it we'd get arbitrary ordering for rows created in the same test
        # tick. Stamp explicit ascending created_at values so the test is
        # deterministic without sleeping for >1s.
        from datetime import datetime, timedelta
        from app.backend.database.models import PipelineRun

        base = datetime(2024, 8, 1, 10, 0, 0)
        for i, rid in enumerate(["a", "b", "c"]):
            runs.create_pending(run_id=rid, scan_date="2024-08-01", template="quick", selected_analysts=["scanner_signal"], top_n=1, universe="nasdaq100")
            db_session.query(PipelineRun).filter(PipelineRun.id == rid).update({"created_at": base + timedelta(seconds=i)})
        db_session.commit()
        listed = runs.list_runs()
        ids = [r.id for r in listed]
        assert ids == ["c", "b", "a"]

    def test_filter_by_template(self, runs):
        for i, tpl in enumerate(["quick", "balanced", "quick"]):
            runs.create_pending(run_id=f"r{i}", scan_date="2024-08-01", template=tpl, selected_analysts=["scanner_signal"], top_n=1, universe="nasdaq100")
        quick_runs = runs.list_runs(template="quick")
        assert len(quick_runs) == 2
        assert all(r.template == "quick" for r in quick_runs)

    def test_filter_by_status(self, runs):
        runs.create_pending(run_id="r1", scan_date="2024-08-01", template="quick", selected_analysts=[], top_n=1, universe="nasdaq100")
        runs.create_pending(run_id="r2", scan_date="2024-08-01", template="quick", selected_analysts=[], top_n=1, universe="nasdaq100")
        runs.mark_complete("r1", watchlist=[], agent_decisions={}, analyst_signals={}, duration_seconds=1.0)
        complete = runs.list_runs(status="COMPLETE")
        pending = runs.list_runs(status="PENDING")
        assert [r.id for r in complete] == ["r1"]
        assert [r.id for r in pending] == ["r2"]

    def test_filter_by_since_scan_date(self, runs):
        for sd, rid in [("2024-07-01", "old"), ("2024-08-01", "new")]:
            runs.create_pending(run_id=rid, scan_date=sd, template="quick", selected_analysts=[], top_n=1, universe="nasdaq100")
        recent = runs.list_runs(since="2024-08-01")
        assert [r.id for r in recent] == ["new"]

    def test_limit_caps_results(self, runs):
        for i in range(5):
            runs.create_pending(run_id=f"r{i}", scan_date="2024-08-01", template="quick", selected_analysts=[], top_n=1, universe="nasdaq100")
        assert len(runs.list_runs(limit=3)) == 3


# ---------------------------------------------------------------------------
# PipelineScheduleRepository
# ---------------------------------------------------------------------------


class TestPipelineSchedule:
    """Wave 4: schedule is per-user. ``get_or_create_for_user`` lazily creates
    a defaults row; ``update_for_user`` patches it. The legacy unscoped
    ``get()`` still returns the first row (used by the cron fallback +
    dispatcher)."""

    def test_get_or_create_returns_defaults_for_new_user(self, schedule):
        row = schedule.get_or_create_for_user(42)
        assert row is not None
        assert row.user_id == 42
        # Default opt-in OFF per implementation plan §Top risks.
        assert row.enabled is False
        assert row.top_n == 5
        assert row.template == "balanced"

    def test_get_for_user_isolated_per_user(self, schedule):
        schedule.update_for_user(1, top_n=11)
        schedule.update_for_user(2, top_n=22)
        assert schedule.get_for_user(1).top_n == 11
        assert schedule.get_for_user(2).top_n == 22
        # A user with no row yet returns None (not created by get_for_user).
        assert schedule.get_for_user(999) is None

    def test_partial_update_only_changes_provided_fields(self, schedule):
        schedule.update_for_user(7, enabled=True, top_n=10)
        row = schedule.get_for_user(7)
        assert row.enabled is True
        assert row.top_n == 10
        # template unchanged (default)
        assert row.template == "balanced"

    def test_update_ignores_unknown_fields(self, schedule):
        schedule.update_for_user(7, top_n=7, not_a_real_field="ignored")
        assert schedule.get_for_user(7).top_n == 7

    def test_update_skips_None_values(self, schedule):
        # Patch semantics: None means "leave alone".
        schedule.update_for_user(7, enabled=True)
        schedule.update_for_user(7, enabled=None, top_n=20)
        row = schedule.get_for_user(7)
        assert row.enabled is True  # not overwritten by None
        assert row.top_n == 20

    def test_unscoped_get_returns_first_row(self, schedule):
        # The db_session fixture seeds an id=1 row (user_id=None) — get()
        # returns it for the cron-fallback / dispatcher paths.
        row = schedule.get()
        assert row is not None
        assert row.id == 1
