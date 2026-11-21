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


@pytest.fixture(autouse=True)
def offline_providers(monkeypatch):
    from src.storage import mongo

    monkeypatch.setenv("MONGODB_URI", "")
    monkeypatch.setattr(mongo, "_STORE", mongo.MongoStore())
    monkeypatch.setattr("v2.data.yfinance_client.YFinanceClient.get_analyst_targets", lambda *args, **kwargs: None)
    monkeypatch.setattr(ScannerService, "_load_earnings_calendar", lambda *args, **kwargs: {})


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
            assert set(runs[0].outcomes) == {"AAPL", "MSFT", "NVDA"}
            for outcome in runs[0].outcomes.values():
                assert outcome["outcome"] == "unrecorded"
                assert outcome["selected"] is None
                assert outcome["detector_results"] == []

    @pytest.mark.parametrize("status", ["PENDING", "RUNNING"])
    def test_refuses_double_run(self, session_factory, config, monkeypatch, status):
        # The first request has acquired its run ID, with or without a started worker.
        with session_factory() as session:
            run = ScanRunRepository(session).create_pending(config)
            if status == "RUNNING":
                ScanRunRepository(session).mark_running(run.id, universe_size=10)
            original = run.id

        monkeypatch.setattr(
            "app.backend.services.scanner_service.run_scan",
            _stub_runner([]),
        )
        svc = ScannerService(session_factory)
        with pytest.raises(ScanAlreadyRunningError) as caught:
            svc.execute(config)
        assert caught.value.run_id == original
        with session_factory() as session:
            assert len(ScanRunRepository(session).list_for_config(config)) == 1

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


@pytest.mark.parametrize('stored_key', ['', 'test-owner-key'])
def test_scanner_uses_owner_key_for_workers_and_calendar(session_factory, config, monkeypatch, stored_key):
    from unittest.mock import Mock, patch
    from app.backend.database.models import ApiKey
    monkeypatch.setenv('FINNHUB_API_KEY', 'test-host-key-must-not-be-used')
    if stored_key:
        with session_factory() as session:
            session.add(ApiKey(user_id=1, provider='FINNHUB_API_KEY', key_value=stored_key, is_active=True))
            session.commit()
    service = ScannerService(session_factory)
    factory = Mock(return_value=Mock())
    calendar = Mock(return_value={})
    monkeypatch.setattr(service, '_refresh_target_snapshots', Mock(return_value={}))
    monkeypatch.setattr(service, '_load_earnings_calendar', calendar)
    runner = Mock(return_value=[])
    monkeypatch.setattr('app.backend.services.scanner_service.run_scan', runner)
    with patch('v2.data.factory.get_provider_factory', return_value=factory) as build:
        service.execute(config, deliver_emails=False)
    build.assert_called_once_with(finnhub_api_key=stored_key)
    assert runner.call_args.kwargs['provider_factory'] is factory
    assert calendar.call_args.kwargs['finnhub_api_key'] == stored_key


def test_freezes_execution_universe_and_observed_signals(session_factory, monkeypatch):
    from datetime import date
    from app.backend.database.models import UniverseSnapshot
    from app.backend.repositories.screener_repository import ScreenerRepository, SnapshotRow
    from app.backend.repositories.watchlist_repository import UserWatchlistRepository
    from v2.scanner.test_daily_momentum import bars, client

    with session_factory() as session:
        watchlists = UserWatchlistRepository(session)
        watchlist = watchlists.create("Tech", user_id=1)
        screener = ScreenerRepository(session)
        selection_date = date(2026, 10, 29)
        screener.bulk_upsert([SnapshotRow(
            ticker="AAPL", market="US", snapshot_date=selection_date, sector="Technology",
        )])
        source = screener.save_selection(
            user_id=1, market="US", snapshot_date=selection_date,
            filters={"sector_in": ["Technology"]}, tickers=["AAPL"],
            watchlist_id=watchlist.id, new_watchlist_name=None,
        )
        watchlists.update(watchlist.id, user_id=1, tickers=["AAPL", "MSFT", "NVDA"])
        cfg = ScannerConfigRepository(session).create(
            name="Volume", user_id=1, universe_kind="watchlist",
            user_watchlist_id=watchlist.id, top_n=1,
            weights={"enabled_detectors": ["relative_volume"]},
        )
        config_id, source_id, list_id = cfg.id, source.id, watchlist.id

    fd = client()
    daily = {"AAPL": bars(volume=250), "MSFT": bars(volume=100)}
    fd.get_prices.side_effect = lambda ticker, *_: daily.get(ticker, [])
    monkeypatch.setattr("v2.data.factory.get_provider_factory", lambda **_: lambda: fd)
    service = ScannerService(session_factory)
    monkeypatch.setattr("app.backend.services.scanner_service.ALL_SIGNALS", ())
    run_id = service.execute(config_id, end_date="2026-10-31", max_workers=1,
                             deliver_emails=False)
    with session_factory() as session:
        UserWatchlistRepository(session).update(list_id, user_id=1, tickers=["NEW"])
        run = ScanRunRepository(session).get_by_id_for_user(run_id, user_id=1)
        frozen = session.get(UniverseSnapshot, run.universe_snapshot_id)
        assert frozen.tickers == ["AAPL", "MSFT", "NVDA"]
        assert frozen.origin == "scanner"
        assert frozen.source_snapshot_id == source_id
        original = session.get(UniverseSnapshot, source_id)
        assert original.filters == {"sector_in": ["Technology"]}
        assert original.tickers == ["AAPL"]
        assert original.screener_snapshot_date == selection_date
        assert frozen.source_watchlist_id == list_id
        assert run.detector_config["source_watchlist_id"] == list_id
        assert run.detector_config["source_watchlist_name"] == "Tech"
        assert run.detector_config["as_of"] == "2026-10-31"
        definition, = run.detector_config["detectors"]
        assert definition["name"] == "relative_volume"
        assert definition["parameters"] == {"window": 20, "threshold": 2.0}
        assert run.outcomes["AAPL"]["selected"]
        decision, = run.outcomes["AAPL"]["detector_results"]
        assert decision["version"] == definition["version"]
        assert decision["signal_session"] == "2026-10-30"
        assert decision["components"]["relative_volume"] == 2.5
        assert run.outcomes["MSFT"]["detector_results"][0]["status"] == "no_event"
        assert run.outcomes["NVDA"]["outcome"] == "no_data"
        assert not run.outcomes["NVDA"]["selected"]
        entry, = WatchlistEntryRepository(session).list_for_run(run_id)
        assert entry.triggers[0]["signal_session"] == "2026-10-30"


def test_historical_scan_does_not_backdate_live_consensus(session_factory, config, monkeypatch):
    from types import SimpleNamespace
    from app.backend.repositories.scanner_repository import AnalystTargetSnapshotRepository

    live = SimpleNamespace(target_mean=990., target_median=990., target_high=990.,
                           target_low=990., current_price=500., n_analysts=4)
    monkeypatch.setattr("v2.data.yfinance_client.YFinanceClient.get_analyst_targets",
                        lambda *args, **kwargs: live)
    monkeypatch.setattr("app.backend.services.scanner_service.run_scan", _stub_runner([]))
    with session_factory() as session:
        AnalystTargetSnapshotRepository(session).upsert(
            ticker="AAPL", asof_date="2001-01-05", target_median=30.,
        )
    ScannerService(session_factory).execute(config, end_date="2001-01-05")
    with session_factory() as session:
        rows = AnalystTargetSnapshotRepository(session).list_for_tickers(
            ["AAPL", "MSFT"], lookback_days=1, end_date="2001-01-05",
        )
        assert [r.target_median for r in rows["AAPL"]] == [30.]
        assert not rows.get("MSFT")


def test_saved_invalid_daily_group_cannot_fall_back_to_default_detectors(session_factory):
    with session_factory() as session:
        cfg = ScannerConfigRepository(session).create(
            name="Invalid", universe_kind="custom", universe_tickers=["AAA"], user_id=1,
            weights={"rule_group": {"combiner": "or", "signals": [{"type": "unknown"}]}},
        )
        config_id = cfg.id

    with pytest.raises(ValueError):
        ScannerService(session_factory)._begin(config_id, "2026-10-30")
    with session_factory() as session:
        assert not ScanRunRepository(session).list_for_config(config_id)


def test_group_run_freezes_selected_parameters_and_uses_only_daily_inputs(session_factory, monkeypatch):
    from v2.scanner.test_daily_momentum import bars, client

    with session_factory() as session:
        cfg = ScannerConfigRepository(session).create(
            name="Volume or breakdown", universe_kind="custom", universe_tickers=["AAA"],
            user_id=1,
            weights={
                "rule_group": {"combiner": "or", "signals": [
                    {"type": "relative_volume", "window": 2, "threshold": 1.5},
                    {"type": "range_breakout", "window": 2, "direction": "bearish"},
                ]},
                "detector_severity_mult": {"relative_volume": 2, "range_breakout": 5},
                "enabled_detectors": ["earnings_event"],
                "quant_weight": 0.8, "event_weight": 0.2,
            },
        )
        config_id = cfg.id

    fd = client(bars(n=3, volume=150))
    monkeypatch.setattr("v2.data.factory.get_provider_factory", lambda **_: lambda: fd)

    def unexpected(*args, **kwargs):
        pytest.fail("A daily group requested fundamental data")

    service = ScannerService(session_factory)
    monkeypatch.setattr(service, "_refresh_target_snapshots", unexpected)
    monkeypatch.setattr(service, "_load_earnings_calendar", unexpected)
    monkeypatch.setattr("v2.scanner.runner._evaluate_quant", unexpected)
    run_id = service.execute(config_id, end_date="2026-10-30", max_workers=1, deliver_emails=False)
    with session_factory() as session:
        run = session.get(ScanRun, run_id)
        definitions = run.detector_config["detectors"]
        assert [(d["name"], d["version"], d["parameters"]) for d in definitions] == [
            ("relative_volume", "1", {"window": 2, "threshold": 1.5}),
            ("range_breakout", "1", {"window": 2}),
        ]
        effective = run.detector_config["weights"]["rule_group"]["signals"]
        assert [signal["direction"] for signal in effective] == ["bullish", "bearish"]
        entry, = WatchlistEntryRepository(session).list_for_run(run_id)
        assert [trigger["detector"] for trigger in entry.triggers] == ["relative_volume"]
        assert entry.composite_score == pytest.approx(60)
        assert entry.quant_score is None
        outcome = run.outcomes["AAA"]
        assert outcome["quality"]["rule_group"] == {
            "match": True, "incomplete": False,
            "matches": {"relative_volume": True, "range_breakout": False},
        }
        assert [result["status"] for result in outcome["detector_results"]] == ["triggered", "triggered"]
    assert {call.args[0] for call in fd.get_prices.call_args_list} == {"AAA"}


def test_pre_group_config_with_malformed_legacy_json_keeps_default_profile(session_factory):
    from v2.scanner.detectors import ALL_DETECTORS

    with session_factory() as session:
        cfg = ScannerConfigRepository(session).create(
            name="Legacy", universe_kind="custom", universe_tickers=["AAA"], user_id=1,
            weights=["old-format"],
        )
        config_id = cfg.id
    payload, _ = ScannerService(session_factory)._begin(config_id, "2026-10-30")
    assert [d["name"] for d in payload["detector_config"]["detectors"]] == [cls.name for cls in ALL_DETECTORS]
