"""Integration tests for Phase 5C — scanner config can target a UserWatchlist.

Three tests:

1. Round-trip via API — POST a config with universe_kind=watchlist +
   user_watchlist_id, GET it back, assert the FK survives the round trip.
2. Universe resolution — load_universe('watchlist', watchlist_tickers=[...])
   returns the deduped/uppercased list; raises ValueError when the kwarg is
   missing.
3. Pydantic validation — ScannerConfigCreateRequest with
   universe_kind=watchlist + user_watchlist_id=None raises ValidationError.

Mirrors the importlib-based route loader from test_watchlist_routes.py so we
can mount the scanner router without dragging in routes/__init__.py's full
import graph (which transitively loads v1 LLM deps that aren't in this
test environment).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import get_db
from app.backend.database.models import Base
from app.backend.models.scanner_schemas import ScannerConfigCreateRequest
from app.backend.repositories.watchlist_repository import UserWatchlistRepository
from app.backend.services.scheduler_service import get_scheduler_service
from v2.scanner.universes.loader import load_universe


def _load_route(module_name: str):
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "app" / "backend" / "routes" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"_scanner_watchlist_routes_under_test_{module_name}", p
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_scanner_mod = _load_route("scanner")
_watchlists_mod = _load_route("watchlists")
scanner_router = _scanner_mod.router
watchlists_router = _watchlists_mod.router


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    app = FastAPI()
    app.include_router(scanner_router)
    app.include_router(watchlists_router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # The /scanner/configs routes depend on SchedulerService for cron
    # register/reschedule/unregister — stub it out so we don't need
    # APScheduler running in the test env.
    fake_scheduler = MagicMock()
    fake_scheduler.register_config = MagicMock()
    fake_scheduler.reschedule_config = MagicMock()
    fake_scheduler.unregister_config = MagicMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_scheduler_service] = lambda: fake_scheduler

    # Expose the session factory so tests can seed watchlist rows.
    client_obj = TestClient(app)
    client_obj._session_local = SessionLocal  # type: ignore[attr-defined]
    yield client_obj
    engine.dispose()


class TestRoundTripViaAPI:
    def test_create_with_watchlist_preserves_fk(self, client):
        # Seed a watchlist row directly so we control the id.
        SessionLocal = client._session_local  # type: ignore[attr-defined]
        with SessionLocal() as db:
            wl = UserWatchlistRepository(db).create("Mega Caps")
            wl = UserWatchlistRepository(db).update(
                wl.id, tickers=["NVDA", "AAPL", "MSFT"],
            )
            watchlist_id = wl.id

        body = {
            "name": "scan-megas",
            "universe_kind": "watchlist",
            "user_watchlist_id": watchlist_id,
            "cron_expr": "0 21 * * 1-5",
            "is_enabled": True,
            "top_n": 5,
        }
        r = client.post("/scanner/configs", json=body)
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["universe_kind"] == "watchlist"
        assert created["user_watchlist_id"] == watchlist_id

        cfg_id = created["id"]
        g = client.get(f"/scanner/configs/{cfg_id}")
        assert g.status_code == 200
        fetched = g.json()
        assert fetched["user_watchlist_id"] == watchlist_id
        assert fetched["universe_kind"] == "watchlist"


class TestUniverseResolution:
    def test_load_universe_watchlist_uppercases_and_dedupes(self):
        result = load_universe(
            "watchlist", watchlist_tickers=["nvda", "AAPL", "nvda", " msft "],
        )
        assert result == ["NVDA", "AAPL", "MSFT"]

    def test_load_universe_watchlist_requires_kwarg(self):
        with pytest.raises(ValueError, match="watchlist_tickers"):
            load_universe("watchlist", watchlist_tickers=None)

    def test_load_universe_watchlist_rejects_empty_list(self):
        with pytest.raises(ValueError, match="watchlist_tickers"):
            load_universe("watchlist", watchlist_tickers=[])


class TestPydanticValidation:
    def test_watchlist_kind_without_id_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ScannerConfigCreateRequest(
                name="bad",
                universe_kind="watchlist",
                user_watchlist_id=None,
            )
        assert "user_watchlist_id" in str(exc_info.value)

    def test_watchlist_kind_with_id_accepted(self):
        # Sanity-check that the validator only fires on the missing-id case.
        cfg = ScannerConfigCreateRequest(
            name="ok",
            universe_kind="watchlist",
            user_watchlist_id=42,
        )
        assert cfg.user_watchlist_id == 42

    def test_non_watchlist_kind_does_not_require_id(self):
        # Existing 'sp500' kind should keep working with no FK.
        cfg = ScannerConfigCreateRequest(
            name="sp500-nightly",
            universe_kind="sp500",
        )
        assert cfg.user_watchlist_id is None
