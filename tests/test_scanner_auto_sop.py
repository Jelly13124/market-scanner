"""Phase 5E: auto-SOP runner tests.

Four tests:
  1. top_n=0 short-circuits — run_sop never called.
  2. top_n=3 with 5 watchlist entries → run_sop called on top-3 by rank.
  3. One failed run_sop doesn't abort the loop — remaining tickers still run.
  4. NotificationDispatcher.dispatch_bundled fires once with the correct
     event_type + scan_run_id and the right ticker count in the payload.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.models import (
    Base, ResearchReport, ScannerConfig, ScanRun, WatchlistEntry,
)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_scan_with_entries(session, *, n: int = 5) -> int:
    """Insert a ScannerConfig + ScanRun + N WatchlistEntry rows.

    Tickers labeled T0, T1, ... TN-1 with rank == index+1 so the top-N
    slice is deterministic.
    """
    cfg = ScannerConfig(name="t", universe_kind="sp500", user_id=1)
    session.add(cfg)
    session.commit()
    run = ScanRun(config_id=cfg.id, status="COMPLETE")
    session.add(run)
    session.commit()
    entries = [
        WatchlistEntry(
            scan_run_id=run.id,
            ticker=f"T{i}",
            composite_score=100.0 - i,
            direction="bullish",
            event_score=0.0,
            event_severity=0.0,
            triggers=[],
            rank=i + 1,
        )
        for i in range(n)
    ]
    session.add_all(entries)
    session.commit()
    return run.id


def _fake_sop_report(ticker: str):
    """Mock run_sop return value matching the AnalyzeReport TypedDict
    shape that auto_sop_runner reads (.sections, .persona_assignments)."""
    section = SimpleNamespace(
        markdown=f"## {ticker}\n\nMock body.",
        structured=None,
        skipped=False,
        persona_used=None,
        skip_reason=None,
    )
    return {
        "sections": {"executive_summary": section},
        "persona_assignments": None,
    }


class TestTopNZeroSkips:
    @patch("src.research.sop_orchestrator.run_sop")
    def test_top_n_zero_returns_empty_without_calling_sop(
        self, mock_run_sop, db_session,
    ):
        from app.backend.services.auto_sop_runner import run_auto_sop_for_scan

        scan_run_id = _seed_scan_with_entries(db_session, n=3)
        result = run_auto_sop_for_scan(
            db_session, scan_run_id=scan_run_id,
            top_n=0, use_personas=False,
        )
        assert result == []
        mock_run_sop.assert_not_called()


class TestTopNLimit:
    @patch("app.backend.services.auto_sop_runner.render_sop")
    @patch("app.backend.services.auto_sop_runner.run_sop")
    def test_only_top_n_tickers_processed(
        self, mock_run_sop, mock_render, db_session,
    ):
        from app.backend.services.auto_sop_runner import run_auto_sop_for_scan

        scan_run_id = _seed_scan_with_entries(db_session, n=5)
        mock_run_sop.side_effect = lambda req, **kwargs: _fake_sop_report(req.ticker)
        mock_render.return_value = "<html><body>mock</body></html>"

        result = run_auto_sop_for_scan(
            db_session, scan_run_id=scan_run_id,
            top_n=3, use_personas=False, owner_user_id=1,
        )
        assert len(result) == 3
        # run_sop called exactly 3 times on the top-3 tickers (by rank). The
        # analyses run concurrently now, so the call ORDER isn't deterministic.
        assert mock_run_sop.call_count == 3
        tickers_processed = sorted(c.args[0].ticker for c in mock_run_sop.call_args_list)
        assert tickers_processed == ["T0", "T1", "T2"]

        # Each persisted as a ResearchReport row
        reports = db_session.query(ResearchReport).all()
        assert len(reports) == 3
        assert {r.ticker for r in reports} == {"T0", "T1", "T2"}


class TestFailedSopDoesNotAbortLoop:
    @patch("app.backend.services.auto_sop_runner.render_sop")
    @patch("app.backend.services.auto_sop_runner.run_sop")
    def test_one_failed_run_sop_does_not_abort_others(
        self, mock_run_sop, mock_render, db_session,
    ):
        from app.backend.services.auto_sop_runner import run_auto_sop_for_scan

        scan_run_id = _seed_scan_with_entries(db_session, n=3)

        def _side_effect(req, **kwargs):
            if req.ticker == "T1":
                raise RuntimeError("simulated LLM blow-up")
            return _fake_sop_report(req.ticker)

        mock_run_sop.side_effect = _side_effect
        mock_render.return_value = "<html><body>mock</body></html>"

        result = run_auto_sop_for_scan(
            db_session, scan_run_id=scan_run_id,
            top_n=3, use_personas=False, owner_user_id=1,
        )
        # T0 and T2 succeed, T1 fails -> 2 reports persisted
        assert len(result) == 2
        reports = db_session.query(ResearchReport).all()
        assert {r.ticker for r in reports} == {"T0", "T2"}


class TestBundledDispatchFiresOnce:
    @patch("app.backend.services.notifications.dispatcher.NotificationDispatcher")
    @patch("app.backend.services.auto_sop_runner.render_sop")
    @patch("app.backend.services.auto_sop_runner.run_sop")
    def test_dispatch_bundled_called_once_with_reports(
        self, mock_run_sop, mock_render, mock_dispatcher_cls, db_session,
    ):
        from app.backend.services.scanner_service import ScannerService

        scan_run_id = _seed_scan_with_entries(db_session, n=3)
        mock_run_sop.side_effect = lambda req, **kwargs: _fake_sop_report(req.ticker)
        mock_render.return_value = "<html><body>mock</body></html>"

        # Single-session factory so the test can inspect rows after.
        # _run_auto_sop_followup opens 2 sessions (runner + reload); both
        # bind to the same connection so we just hand back the same one.
        SessionLocal = sessionmaker(bind=db_session.get_bind())

        def factory():
            return SessionLocal()

        mock_dispatch_instance = MagicMock()
        mock_dispatch_instance.dispatch_bundled.return_value = 1
        mock_dispatcher_cls.return_value = mock_dispatch_instance

        svc = ScannerService(session_factory=factory)
        # Call the hook directly — bypasses the scan-pipeline machinery.
        svc._run_auto_sop_followup(
            scan_run_id=scan_run_id, top_n=2, use_personas=False, owner_user_id=1,
        )

        # One bundled dispatch call total
        mock_dispatch_instance.dispatch_bundled.assert_called_once()
        kwargs = mock_dispatch_instance.dispatch_bundled.call_args.kwargs
        assert kwargs["event_type"] == "research.bundled"
        assert kwargs["scan_run_id"] == scan_run_id
        # Two reports (top_n=2) handed to the dispatcher
        assert len(kwargs["reports"]) == 2
        tickers = [r.ticker for r in kwargs["reports"]]
        assert tickers == ["T0", "T1"]
