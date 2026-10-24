"""Integration tests for /scanner/* REST routes.

Uses FastAPI TestClient against a minimal app composed JUST of the scanner
router — avoids pulling in the full main.py (which would initialize Ollama,
the real DB, etc.).

NOTE: ``app/backend/routes/__init__.py`` eagerly imports all routers, which
in turn pulls v1 LLM dependencies (``langchain_deepseek``, etc.) that aren't
installed in the test env. We sidestep this by loading ``scanner.py`` via
``importlib`` so the routes package's ``__init__`` is never executed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import Base, User
from app.backend.repositories.scanner_repository import (
    ScanRunRepository,
    ScannerConfigRepository,
    WatchlistEntryRepository,
)
from app.backend.services.scan_broadcaster import ScanBroadcaster, get_broadcaster
from app.backend.services.scheduler_service import (
    SchedulerService,
    get_scheduler_service,
)


def _load_scanner_router():
    """Load app/backend/routes/scanner.py without triggering routes/__init__.py."""
    repo_root = Path(__file__).resolve().parents[1]
    scanner_path = repo_root / "app" / "backend" / "routes" / "scanner.py"
    spec = importlib.util.spec_from_file_location(
        "_scanner_routes_under_test", scanner_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.router


scanner_router = _load_scanner_router()


@pytest.fixture()
def setup():
    # StaticPool keeps the single in-memory DB connection alive across sessions
    # — without it, each new session would create its own (empty) :memory: DB.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Stub the scheduler so we don't actually start APScheduler in tests.
    fake_scheduler = MagicMock(spec=SchedulerService)
    fake_scheduler.run_now.return_value = 1
    # Fresh broadcaster per test so subscriber state doesn't leak.
    fake_broadcaster = ScanBroadcaster()

    # Fake authenticated user injected into every scanner route that calls
    # get_current_user. id=1 so repo scoping filters ScannerConfig.user_id == 1.
    _fake_user = User(id=1, email="test@test.com", is_active=True, is_superuser=False)

    # FastAPI needs the override to be a generator function itself (so it can
    # iterate yield/finally). A lambda wrapping a generator function returns
    # the generator OBJECT — which FastAPI then injects raw, breaking
    # ``db.add(...)`` in the repository.
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(scanner_router)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_scheduler_service] = lambda: fake_scheduler
    app.dependency_overrides[get_broadcaster] = lambda: fake_broadcaster
    app.dependency_overrides[get_current_user] = lambda: _fake_user

    client = TestClient(app)
    yield client, SessionLocal, fake_scheduler, fake_broadcaster
    engine.dispose()


# ---------------------------------------------------------------------------
# Detector metadata (GET /scanner/detectors)
# ---------------------------------------------------------------------------


class TestListDetectors:
    def test_returns_all_registered_detectors(self, setup):
        from v2.scanner.detectors import ALL_DETECTORS

        client, _, _, _ = setup
        r = client.get("/scanner/detectors")
        assert r.status_code == 200
        data = r.json()
        # One entry per registered detector
        names = {item["name"] for item in data}
        expected = {c().name for c in ALL_DETECTORS}
        assert names == expected

    def test_response_shape(self, setup):
        client, _, _, _ = setup
        r = client.get("/scanner/detectors")
        data = r.json()
        for item in data:
            assert set(item.keys()) == {"name", "label", "default_mult", "description"}
            assert isinstance(item["name"], str) and item["name"]
            assert isinstance(item["label"], str) and item["label"]
            assert isinstance(item["default_mult"], (int, float))
            assert 0.0 <= item["default_mult"] <= 5.0
            assert isinstance(item["description"], str) and item["description"]

    def test_order_matches_all_detectors(self, setup):
        from v2.scanner.detectors import ALL_DETECTORS

        client, _, _, _ = setup
        r = client.get("/scanner/detectors")
        names = [item["name"] for item in r.json()]
        expected = [c().name for c in ALL_DETECTORS]
        assert names == expected


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------


class TestConfigsCRUD:
    def test_create_then_get(self, setup):
        client, _, scheduler, _ = setup
        body = {
            "name": "nightly_sp500",
            "universe_kind": "sp500",
            "cron_expr": "0 21 * * 1-5",
        }
        r = client.post("/scanner/configs", json=body)
        assert r.status_code == 201
        created = r.json()
        assert created["name"] == "nightly_sp500"
        assert created["universe_kind"] == "sp500"
        # Scheduler should have been notified.
        scheduler.register_config.assert_called_once()

        # GET it back.
        r = client.get(f"/scanner/configs/{created['id']}")
        assert r.status_code == 200
        assert r.json()["name"] == "nightly_sp500"

    def test_list_all(self, setup):
        client, SessionLocal, _, _ = setup
        with SessionLocal() as s:
            # user_id=1 matches the fake authenticated user in the route.
            ScannerConfigRepository(s).create(name="a", universe_kind="sp500", user_id=1)
            ScannerConfigRepository(s).create(name="b", universe_kind="nasdaq100", user_id=1)
        r = client.get("/scanner/configs")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_update_reschedules(self, setup):
        client, SessionLocal, scheduler, _ = setup
        with SessionLocal() as s:
            cfg = ScannerConfigRepository(s).create(name="x", universe_kind="sp500", user_id=1)
            cid = cfg.id
        r = client.patch(f"/scanner/configs/{cid}", json={"name": "renamed", "top_n": 30})
        assert r.status_code == 200
        assert r.json()["name"] == "renamed"
        assert r.json()["top_n"] == 30
        scheduler.reschedule_config.assert_called_once()

    def test_delete_unregisters(self, setup):
        client, SessionLocal, scheduler, _ = setup
        with SessionLocal() as s:
            cfg = ScannerConfigRepository(s).create(name="x", universe_kind="sp500", user_id=1)
            cid = cfg.id
        r = client.delete(f"/scanner/configs/{cid}")
        assert r.status_code == 204
        scheduler.unregister_config.assert_called_once_with(cid)

    def test_get_missing_404(self, setup):
        client, _, _, _ = setup
        assert client.get("/scanner/configs/9999").status_code == 404

    def test_delete_missing_404(self, setup):
        client, _, _, _ = setup
        assert client.delete("/scanner/configs/9999").status_code == 404

    def test_create_with_invalid_cron_400(self, setup):
        client, _, _, _ = setup
        r = client.post("/scanner/configs", json={
            "name": "bad", "universe_kind": "sp500", "cron_expr": "totally not cron",
        })
        assert r.status_code == 400
        assert "Invalid cron" in r.json()["detail"]

    def test_custom_universe_requires_tickers(self, setup):
        client, _, _, _ = setup
        # Missing universe_tickers when kind=custom should 422 (pydantic validator).
        r = client.post("/scanner/configs", json={
            "name": "custom", "universe_kind": "custom",
        })
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Manual run + status
# ---------------------------------------------------------------------------


class TestRunNow:
    def test_run_dispatches_and_returns_run_id(self, setup):
        client, SessionLocal, scheduler, _ = setup
        with SessionLocal() as s:
            cfg = ScannerConfigRepository(s).create(name="x", universe_kind="sp500", user_id=1)
            cid = cfg.id
        # Configure stub to return a fake run_id quickly.
        scheduler.run_now.return_value = 42
        r = client.post(f"/scanner/configs/{cid}/run")
        assert r.status_code == 202
        # The route now also reports already_running on the response.
        assert r.json() == {"run_id": 42, "status": "RUNNING", "already_running": False}
        # Default manual run is opt-out of email delivery (send_email=false).
        scheduler.run_now.assert_called_once_with(cid, deliver_emails=False)

    def test_run_for_unknown_config_404(self, setup):
        client, _, _, _ = setup
        assert client.post("/scanner/configs/999/run").status_code == 404


class TestRunStatus:
    def test_get_run_404_when_missing(self, setup):
        client, _, _, _ = setup
        assert client.get("/scanner/runs/9999").status_code == 404

    def test_get_run_and_entries(self, setup):
        client, SessionLocal, _, _ = setup
        with SessionLocal() as s:
            cfg = ScannerConfigRepository(s).create(name="x", universe_kind="sp500", user_id=1)
            run = ScanRunRepository(s).create_pending(cfg.id)
            ScanRunRepository(s).mark_running(run.id, universe_size=10)
            WatchlistEntryRepository(s).bulk_insert(run.id, [
                {"ticker": "AAPL", "composite_score": 85.0, "direction": "bullish",
                 "event_score": 85.0, "quant_score": None, "triggers": [
                     {"detector": "insider_cluster", "triggered": True,
                      "severity_z": 2.5, "direction": "bullish",
                      "reason": "cluster", "components": {}, "asof_date": "2026-05-13"}
                 ], "rank": 1},
            ])
            ScanRunRepository(s).mark_complete(run.id)
            rid = run.id

        # Summary
        r = client.get(f"/scanner/runs/{rid}")
        assert r.status_code == 200
        assert r.json()["status"] == "COMPLETE"

        # Full entries
        r = client.get(f"/scanner/runs/{rid}/entries")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "COMPLETE"
        assert len(body["entries"]) == 1
        assert body["entries"][0]["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# GET /runs/{id}/quotes
# ---------------------------------------------------------------------------


class TestRunQuotes:
    """The /quotes endpoint batch-fetches live quotes via the configured
    DataClient. We monkey-patch ``make_data_client`` so no real HTTP fires."""

    def _seed_run(self, SessionLocal, tickers: list[str]) -> int:
        with SessionLocal() as s:
            cfg = ScannerConfigRepository(s).create(name="x", universe_kind="sp500", user_id=1)
            run = ScanRunRepository(s).create_pending(cfg.id)
            ScanRunRepository(s).mark_running(run.id, universe_size=len(tickers))
            rows = [
                {"ticker": t, "composite_score": 80.0, "direction": "bullish",
                 "event_score": 80.0, "quant_score": None, "triggers": [],
                 "rank": i + 1}
                for i, t in enumerate(tickers)
            ]
            WatchlistEntryRepository(s).bulk_insert(run.id, rows)
            ScanRunRepository(s).mark_complete(run.id)
            return run.id

    def test_returns_404_for_missing_run(self, setup):
        client, _, _, _ = setup
        assert client.get("/scanner/runs/9999/quotes").status_code == 404

    def test_returns_empty_dict_for_run_with_no_entries(self, setup, monkeypatch):
        client, SessionLocal, _, _ = setup
        run_id = self._seed_run(SessionLocal, [])
        r = client.get(f"/scanner/runs/{run_id}/quotes")
        assert r.status_code == 200
        assert r.json() == {}

    def test_returns_all_none_when_client_lacks_get_quote(self, setup, monkeypatch):
        client, SessionLocal, _, _ = setup
        run_id = self._seed_run(SessionLocal, ["AAPL", "MSFT"])
        # Stub client WITHOUT get_quote.
        class _NoQuote:
            pass
        import importlib
        scanner_mod = sys.modules["_scanner_routes_under_test"]
        monkeypatch.setattr(scanner_mod, "make_data_client", lambda: _NoQuote())
        r = client.get(f"/scanner/runs/{run_id}/quotes")
        assert r.status_code == 200
        body = r.json()
        assert body == {"AAPL": None, "MSFT": None}

    def test_returns_quotes_when_client_provides_them(self, setup, monkeypatch):
        client, SessionLocal, _, _ = setup
        run_id = self._seed_run(SessionLocal, ["AAPL", "MSFT", "FAIL"])
        from v2.data.models import Quote

        class _Client:
            def get_quote(self, ticker):
                if ticker == "FAIL":
                    raise RuntimeError("quote provider down")
                return Quote(
                    ticker=ticker, current_price=100.0 + len(ticker),
                    prev_close=99.0, percent_change=1.0, asof_timestamp=1000,
                )
            def close(self):
                pass

        scanner_mod = sys.modules["_scanner_routes_under_test"]
        monkeypatch.setattr(scanner_mod, "make_data_client", lambda: _Client())
        r = client.get(f"/scanner/runs/{run_id}/quotes")
        assert r.status_code == 200
        body = r.json()
        assert body["AAPL"]["current_price"] == 104.0  # 100 + len("AAPL")
        assert body["MSFT"]["current_price"] == 104.0  # 100 + len("MSFT")
        assert body["MSFT"]["percent_change"] == 1.0
        # FAIL ticker's exception isolated — entry is None, not 500.
        assert body["FAIL"] is None
