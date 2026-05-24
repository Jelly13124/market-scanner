"""Integration tests for /watchlists/* REST routes (Phase 5B).

Pattern mirrors test_pipeline_routes.py: load the route module via importlib
to avoid pulling routes/__init__.py (which transitively imports v1 LLM deps
that aren't present in the test env).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import get_db
from app.backend.database.models import Base


def _load_route(module_name: str) -> object:
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "app" / "backend" / "routes" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"_watchlist_routes_under_test_{module_name}", p
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_watchlists_mod = _load_route("watchlists")
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
    app.include_router(watchlists_router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app)
    engine.dispose()


class TestWatchlistRoutes:
    def test_post_get_roundtrip(self, client):
        r = client.post("/watchlists", json={"name": "Tech"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Tech"
        assert body["tickers"] == []
        wid = body["id"]

        g = client.get(f"/watchlists/{wid}")
        assert g.status_code == 200
        assert g.json()["name"] == "Tech"

        lst = client.get("/watchlists")
        assert lst.status_code == 200
        assert any(row["id"] == wid for row in lst.json())

    def test_patch_renames(self, client):
        wid = client.post("/watchlists", json={"name": "Old"}).json()["id"]
        r = client.patch(f"/watchlists/{wid}", json={"name": "New"})
        assert r.status_code == 200
        assert r.json()["name"] == "New"

    def test_delete_then_get_404(self, client):
        wid = client.post("/watchlists", json={"name": "Doomed"}).json()["id"]
        d = client.delete(f"/watchlists/{wid}")
        assert d.status_code == 204
        g = client.get(f"/watchlists/{wid}")
        assert g.status_code == 404

    def test_add_ticker_reflects_in_list(self, client):
        wid = client.post("/watchlists", json={"name": "Mega"}).json()["id"]
        r = client.post(f"/watchlists/{wid}/tickers", json={"ticker": "nvda"})
        assert r.status_code == 200
        assert r.json()["tickers"] == ["NVDA"]
        # Idempotent: re-add same ticker → still single entry.
        r2 = client.post(f"/watchlists/{wid}/tickers", json={"ticker": "NVDA"})
        assert r2.json()["tickers"] == ["NVDA"]

    def test_remove_ticker(self, client):
        wid = client.post("/watchlists", json={"name": "Mix"}).json()["id"]
        client.post(f"/watchlists/{wid}/tickers", json={"ticker": "AAPL"})
        client.post(f"/watchlists/{wid}/tickers", json={"ticker": "MSFT"})
        r = client.delete(f"/watchlists/{wid}/tickers/aapl")
        assert r.status_code == 200
        assert r.json()["tickers"] == ["MSFT"]
