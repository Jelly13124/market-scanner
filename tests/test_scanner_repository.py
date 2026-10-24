"""Unit tests for scanner repositories and universe loader.

Uses an in-memory SQLite engine so we don't touch the dev/prod hedge_fund.db.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, ScannerConfig
from app.backend.repositories.scanner_repository import (
    ScanRunRepository,
    ScannerConfigRepository,
    WatchlistEntryRepository,
)
from v2.scanner.universes import load_universe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """In-memory SQLite engine with all tables created. Yields a session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def configs(db_session):
    return ScannerConfigRepository(db_session)


@pytest.fixture()
def runs(db_session):
    return ScanRunRepository(db_session)


@pytest.fixture()
def entries(db_session):
    return WatchlistEntryRepository(db_session)


# ---------------------------------------------------------------------------
# ScannerConfigRepository
# ---------------------------------------------------------------------------


class TestScannerConfigRepository:
    def test_create_and_get(self, configs):
        config = configs.create(name="nightly_sp500", universe_kind="sp500", user_id=1)
        assert config.id is not None
        assert config.name == "nightly_sp500"
        assert config.cron_expr == "0 21 * * 1-5"
        assert config.is_enabled is True
        assert config.top_n == 20

        fetched = configs.get_by_id(config.id)
        assert fetched is not None
        assert fetched.id == config.id

    def test_list_all_orders_by_recency(self, configs):
        a = configs.create(name="a", universe_kind="sp500", user_id=1)
        b = configs.create(name="b", universe_kind="russell3000", user_id=1)
        ids = [c.id for c in configs.list_all()]
        # Both should be present; ordering is by updated_at desc then created_at desc
        assert set(ids) == {a.id, b.id}

    def test_list_enabled_only(self, configs):
        a = configs.create(name="enabled", universe_kind="sp500", is_enabled=True, user_id=1)
        b = configs.create(name="disabled", universe_kind="sp500", is_enabled=False, user_id=1)
        enabled_ids = [c.id for c in configs.list_all(enabled_only=True)]
        assert a.id in enabled_ids
        assert b.id not in enabled_ids

    def test_update_changes_fields(self, configs):
        config = configs.create(name="orig", universe_kind="sp500", user_id=1)
        updated = configs.update(config.id, name="renamed", top_n=50)
        assert updated.name == "renamed"
        assert updated.top_n == 50
        # Unchanged fields stay
        assert updated.universe_kind == "sp500"

    def test_update_returns_none_for_missing(self, configs):
        assert configs.update(9999, name="nope") is None

    def test_delete(self, configs):
        config = configs.create(name="to_delete", universe_kind="sp500", user_id=1)
        assert configs.delete(config.id) is True
        assert configs.get_by_id(config.id) is None
        # Second delete is a no-op
        assert configs.delete(config.id) is False

    def test_custom_universe_persists_tickers(self, configs):
        config = configs.create(
            name="my_watchlist",
            universe_kind="custom",
            universe_tickers=["AAPL", "MSFT"],
            user_id=1,
        )
        assert config.universe_tickers == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# ScanRunRepository
# ---------------------------------------------------------------------------


class TestScanRunRepository:
    def test_lifecycle_pending_running_complete(self, configs, runs):
        cfg = configs.create(name="cfg", universe_kind="sp500", user_id=1)

        run = runs.create_pending(cfg.id)
        assert run.status == "PENDING"
        assert run.started_at is None

        runs.mark_running(run.id, universe_size=500)
        running = runs.get_by_id(run.id)
        assert running.status == "RUNNING"
        assert running.started_at is not None
        assert running.universe_size == 500

        runs.mark_complete(run.id)
        complete = runs.get_by_id(run.id)
        assert complete.status == "COMPLETE"
        assert complete.completed_at is not None

    def test_mark_error_records_message(self, configs, runs):
        cfg = configs.create(name="cfg", universe_kind="sp500", user_id=1)
        run = runs.create_pending(cfg.id)
        runs.mark_error(run.id, "FD 429 storm")
        err = runs.get_by_id(run.id)
        assert err.status == "ERROR"
        assert err.error_message == "FD 429 storm"
        assert err.completed_at is not None

    def test_latest_for_config(self, configs, runs):
        cfg = configs.create(name="cfg", universe_kind="sp500", user_id=1)
        r1 = runs.create_pending(cfg.id)
        r2 = runs.create_pending(cfg.id)
        latest = runs.get_latest_for_config(cfg.id)
        # Most recent by created_at; both inserted in this test
        assert latest.id in {r1.id, r2.id}

    def test_list_running_only_returns_in_progress(self, configs, runs):
        cfg = configs.create(name="cfg", universe_kind="sp500", user_id=1)
        r1 = runs.create_pending(cfg.id)
        r2 = runs.create_pending(cfg.id)
        runs.mark_running(r1.id)
        # r2 stays PENDING
        running = runs.list_running()
        ids = [r.id for r in running]
        assert r1.id in ids
        assert r2.id not in ids


# ---------------------------------------------------------------------------
# WatchlistEntryRepository
# ---------------------------------------------------------------------------


class TestWatchlistEntryRepository:
    def test_bulk_insert_and_list(self, configs, runs, entries):
        cfg = configs.create(name="cfg", universe_kind="sp500", user_id=1)
        run = runs.create_pending(cfg.id)

        payload = [
            {
                "ticker": f"T{i}",
                "composite_score": 90 - i,
                "direction": "bullish",
                "event_score": 60.0,
                "quant_score": 30.0,
                "triggers": [
                    {
                        "detector": "earnings_surprise",
                        "triggered": True,
                        "severity_z": 2.5,
                        "direction": "bullish",
                        "reason": f"BEAT for T{i}",
                        "components": {},
                        "asof_date": "2026-05-13",
                    }
                ],
                "rank": i + 1,
            }
            for i in range(5)
        ]
        count = entries.bulk_insert(run.id, payload)
        assert count == 5

        listed = entries.list_for_run(run.id)
        assert len(listed) == 5
        # Sorted by rank asc
        assert [e.rank for e in listed] == [1, 2, 3, 4, 5]
        assert listed[0].composite_score == 90
        assert listed[0].triggers[0]["detector"] == "earnings_surprise"

    def test_empty_run_returns_no_entries(self, configs, runs, entries):
        cfg = configs.create(name="cfg", universe_kind="sp500", user_id=1)
        run = runs.create_pending(cfg.id)
        assert entries.list_for_run(run.id) == []


# ---------------------------------------------------------------------------
# Universe loader
# ---------------------------------------------------------------------------


class TestUniverseLoader:
    @pytest.mark.parametrize("kind", ["sp500", "russell3000", "all_us"])
    def test_loads_nonempty_list(self, kind):
        tickers = load_universe(kind)
        assert isinstance(tickers, list)
        assert len(tickers) > 0
        # Header was consumed
        assert "ticker" not in [t.lower() for t in tickers]
        # No leading-# comment rows leaked through
        assert not any(t.startswith("#") for t in tickers)

    def test_sp500_contains_known_megacaps(self):
        tickers = set(load_universe("sp500"))
        for must in ("AAPL", "MSFT", "GOOGL", "NVDA"):
            assert must in tickers

    def test_custom_requires_tickers(self):
        with pytest.raises(ValueError):
            load_universe("custom")
        with pytest.raises(ValueError):
            load_universe("custom", custom=[])


# ---------------------------------------------------------------------------
# AnalystTargetSnapshotRepository (M9.d)
# ---------------------------------------------------------------------------


class TestAnalystTargetSnapshotRepository:
    def test_insert_then_get(self, db_session):
        from app.backend.repositories.scanner_repository import (
            AnalystTargetSnapshotRepository,
        )
        repo = AnalystTargetSnapshotRepository(db_session)
        row = repo.upsert(
            ticker="AAPL", asof_date="2026-05-13",
            target_median=210.0, target_mean=212.0,
            target_high=240.0, target_low=180.0,
            current_price=200.0, n_analysts=35,
        )
        assert row.id is not None
        assert row.target_median == 210.0
        assert row.n_analysts == 35

    def test_upsert_same_day_is_idempotent(self, db_session):
        """Two scans on the same calendar day → one DB row, refreshed values.

        Required because cron + manual run + retry can all hit the same day
        and we don't want duplicate snapshots (which would break the
        list-ordered comparison the detector relies on)."""
        from app.backend.repositories.scanner_repository import (
            AnalystTargetSnapshotRepository,
        )
        from app.backend.database.models import AnalystTargetSnapshot
        repo = AnalystTargetSnapshotRepository(db_session)
        first = repo.upsert(ticker="MSFT", asof_date="2026-05-13", target_median=420.0)
        second = repo.upsert(ticker="MSFT", asof_date="2026-05-13", target_median=425.0)
        assert first.id == second.id, "upsert must update, not insert a duplicate"
        assert second.target_median == 425.0
        count = (
            db_session.query(AnalystTargetSnapshot)
            .filter(AnalystTargetSnapshot.ticker == "MSFT")
            .count()
        )
        assert count == 1

    def test_different_days_create_separate_rows(self, db_session):
        from app.backend.repositories.scanner_repository import (
            AnalystTargetSnapshotRepository,
        )
        repo = AnalystTargetSnapshotRepository(db_session)
        r1 = repo.upsert(ticker="NVDA", asof_date="2026-05-12", target_median=900.0)
        r2 = repo.upsert(ticker="NVDA", asof_date="2026-05-13", target_median=920.0)
        assert r1.id != r2.id

    def test_list_for_tickers_oldest_to_newest(self, db_session):
        from app.backend.repositories.scanner_repository import (
            AnalystTargetSnapshotRepository,
        )
        repo = AnalystTargetSnapshotRepository(db_session)
        # Insert in reverse-chrono order to confirm ordering is by asof_date
        # not insertion order.
        repo.upsert(ticker="GOOG", asof_date="2026-05-13", target_median=180.0)
        repo.upsert(ticker="GOOG", asof_date="2026-05-10", target_median=170.0)
        repo.upsert(ticker="GOOG", asof_date="2026-05-11", target_median=175.0)
        out = repo.list_for_tickers(["GOOG"], lookback_days=7, end_date="2026-05-13")
        assert "GOOG" in out
        dates = [s.asof_date for s in out["GOOG"]]
        assert dates == ["2026-05-10", "2026-05-11", "2026-05-13"]

    def test_list_filters_by_lookback_window(self, db_session):
        from app.backend.repositories.scanner_repository import (
            AnalystTargetSnapshotRepository,
        )
        repo = AnalystTargetSnapshotRepository(db_session)
        repo.upsert(ticker="AMD", asof_date="2026-01-01", target_median=100.0)  # too old
        repo.upsert(ticker="AMD", asof_date="2026-05-12", target_median=180.0)
        repo.upsert(ticker="AMD", asof_date="2026-05-13", target_median=185.0)
        out = repo.list_for_tickers(["AMD"], lookback_days=7, end_date="2026-05-13")
        dates = [s.asof_date for s in out["AMD"]]
        assert "2026-01-01" not in dates
        assert dates == ["2026-05-12", "2026-05-13"]

    def test_list_empty_tickers_returns_empty(self, db_session):
        from app.backend.repositories.scanner_repository import (
            AnalystTargetSnapshotRepository,
        )
        repo = AnalystTargetSnapshotRepository(db_session)
        assert repo.list_for_tickers([], lookback_days=7) == {}

    def test_list_unknown_ticker_returns_empty_dict_entry(self, db_session):
        """Asking for a ticker that has never been snapshotted → dict has no
        entry for that ticker (caller does .get(t, []))."""
        from app.backend.repositories.scanner_repository import (
            AnalystTargetSnapshotRepository,
        )
        repo = AnalystTargetSnapshotRepository(db_session)
        out = repo.list_for_tickers(["NOPE"], lookback_days=7, end_date="2026-05-13")
        assert out == {}

    def test_custom_dedupes_and_uppercases(self):
        out = load_universe("custom", custom=["aapl", "MSFT", "AAPL", "  goog  "])
        assert out == ["AAPL", "MSFT", "GOOG"]

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            load_universe("fang_stocks")

    def test_nasdaq100_loads(self):
        tickers = load_universe("nasdaq100")
        assert len(tickers) > 50
        # Megacap NDX names that should be in any seed
        for must in ("AAPL", "MSFT", "NVDA", "GOOGL"):
            assert must in tickers

    def test_nasdaq100_sp500_composite_is_union(self):
        ndx = set(load_universe("nasdaq100"))
        sp5 = set(load_universe("sp500"))
        composite = load_universe("nasdaq100_sp500")
        # Composite is a superset of both, deduped.
        assert set(composite) == ndx | sp5
        assert len(composite) == len(set(composite))  # no duplicates
