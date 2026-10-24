"""Integration tests for ScannerService.

Uses an in-memory SQLite engine with all tables created from the SQLAlchemy
models. The scanner runner is monkeypatched to return predictable results so
this test doesn't hit FD or do any real scanning — that's covered by
``v2/scanner/test_runner.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, ScanRun
from app.backend.repositories.scanner_repository import (
    ScannerConfigRepository,
    ScanRunRepository,
    WatchlistEntryRepository,
)
from app.backend.services.scan_broadcaster import ScanBroadcaster
from app.backend.services.scanner_service import ScanAlreadyRunningError, ScannerService
from v2.scanner.models import ScoredEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal


@pytest.fixture()
def config(session_factory):
    with session_factory() as session:
        cfg = ScannerConfigRepository(session).create(
            name="test_cfg",
            universe_kind="custom",
            universe_tickers=["AAPL", "MSFT", "NVDA"],
            top_n=2,
            user_id=1,
        )
        return cfg.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _stub_runner(scored: list[ScoredEntry]):
    """Return a fake run_scan that ignores inputs and returns *scored*."""

    def _fake(*args, **kwargs):
        # Mirror the runner's contract: assign ranks before returning.
        for i, e in enumerate(scored, start=1):
            e.rank = i
        return scored

    return _fake


class TestScannerServiceExecute:
    def test_persists_top_n_watchlist(self, session_factory, config, monkeypatch):
        scored = [
            ScoredEntry(ticker="MSFT", composite_score=88.0, direction="bullish",
                        event_score=88.0, quant_score=None, triggers=[{"detector": "x"}]),
            ScoredEntry(ticker="AAPL", composite_score=72.0, direction="bearish",
                        event_score=72.0, quant_score=None, triggers=[]),
        ]
        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan",
            _stub_runner(scored),
        )

        svc = ScannerService(session_factory)
        run_id = svc.execute(config)

        with session_factory() as session:
            run = ScanRunRepository(session).get_by_id(run_id)
            assert run.status == "COMPLETE"
            assert run.universe_size == 3
            assert run.completed_at is not None

            entries = WatchlistEntryRepository(session).list_for_run(run_id)
            assert [e.ticker for e in entries] == ["MSFT", "AAPL"]
            assert [e.rank for e in entries] == [1, 2]
            assert entries[0].composite_score == 88.0

    def test_empty_results_still_marks_complete(self, session_factory, config, monkeypatch):
        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan",
            _stub_runner([]),
        )
        svc = ScannerService(session_factory)
        run_id = svc.execute(config)

        with session_factory() as session:
            run = ScanRunRepository(session).get_by_id(run_id)
            assert run.status == "COMPLETE"
            assert WatchlistEntryRepository(session).list_for_run(run_id) == []

    def test_runner_exception_marks_error(self, session_factory, config, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic failure")

        monkeypatch.setattr("app.backend.services.scanner_service.run_scan", _boom)

        svc = ScannerService(session_factory)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            svc.execute(config)

        with session_factory() as session:
            runs = ScanRunRepository(session).list_for_config(config)
            assert len(runs) == 1
            assert runs[0].status == "ERROR"
            assert "synthetic failure" in runs[0].error_message

    def test_refuses_double_run(self, session_factory, config, monkeypatch):
        # Manually create a RUNNING row to simulate an in-flight scan.
        with session_factory() as session:
            run = ScanRunRepository(session).create_pending(config)
            ScanRunRepository(session).mark_running(run.id, universe_size=10)

        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan",
            _stub_runner([]),
        )
        svc = ScannerService(session_factory)
        with pytest.raises(ScanAlreadyRunningError):
            svc.execute(config)

    def test_unknown_config_raises(self, session_factory, monkeypatch):
        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan",
            _stub_runner([]),
        )
        svc = ScannerService(session_factory)
        with pytest.raises(ValueError, match="No scanner config"):
            svc.execute(99999)

    def test_broadcaster_receives_lifecycle_events(self, session_factory, config, monkeypatch):
        scored = [
            ScoredEntry(ticker="AAPL", composite_score=70.0, direction="bullish",
                        event_score=70.0, triggers=[]),
        ]
        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan",
            _stub_runner(scored),
        )

        captured: list[dict] = []

        class _CaptureBroadcaster(ScanBroadcaster):
            def publish(self, run_id, event):
                captured.append({"run_id": run_id, **event})

            def close(self, run_id):
                captured.append({"run_id": run_id, "event": "_closed"})

        b = _CaptureBroadcaster()
        svc = ScannerService(session_factory, broadcaster=b)
        run_id = svc.execute(config)

        kinds = [e["event"] for e in captured]
        assert "start" in kinds
        assert "complete" in kinds
        assert kinds[-1] == "_closed"
        complete = next(e for e in captured if e["event"] == "complete")
        assert complete["entries"] == 1
        assert complete["run_id"] == run_id

    def test_enabled_detectors_filters_run_scan_detectors(self, session_factory, monkeypatch):
        """When weights.enabled_detectors is set, scanner_service must filter
        ALL_DETECTORS down to that subset before calling run_scan."""
        # Create config with enabled_detectors set
        with session_factory() as session:
            cfg = ScannerConfigRepository(session).create(
                name="filtered",
                universe_kind="custom",
                universe_tickers=["AAPL"],
                top_n=1,
                user_id=1,
                weights={
                    "enabled_detectors": ["earnings_surprise", "intraday_move"],
                },
            )
            cfg_id = cfg.id

        captured: dict = {}

        def _capture_runner(*args, **kwargs):
            captured["detectors"] = kwargs.get("detectors")
            captured["weights"] = kwargs.get("weights")
            return []

        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan", _capture_runner,
        )
        svc = ScannerService(session_factory)
        svc.execute(cfg_id)

        det_names = [d.name for d in captured["detectors"]]
        assert sorted(det_names) == sorted(["earnings_event", "intraday_move"])
        # Sanity: weights round-tripped correctly via _build_weights; legacy alias
        # "earnings_surprise" is rewritten to canonical "earnings_event" by validation
        assert captured["weights"].enabled_detectors == ["earnings_event", "intraday_move"]

    def test_no_enabled_detectors_means_all_run(self, session_factory, config, monkeypatch):
        """Existing configs without weights.enabled_detectors should run all 7
        detectors (preserves pre-feature behavior)."""
        from v2.scanner.detectors import ALL_DETECTORS

        captured: dict = {}

        def _capture_runner(*args, **kwargs):
            captured["detectors"] = kwargs.get("detectors")
            return []

        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan", _capture_runner,
        )
        svc = ScannerService(session_factory)
        svc.execute(config)

        det_names = sorted(d.name for d in captured["detectors"])
        expected = sorted(c().name for c in ALL_DETECTORS)
        assert det_names == expected
