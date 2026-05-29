"""Integration tests for /watchlists/* REST routes (Phase 5B).

Wave 4 update: routes now require auth. We use the full api_router app from
tests/auth/conftest.py (full_client fixture) so we can register a user and
get a real bearer token. The importlib trick is no longer needed because the
full_client fixture already includes the watchlists router via api_router.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import get_db
from app.backend.database.models import Base
from app.backend.routes import api_router


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
    app.include_router(api_router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        # Register a user and attach token to the client for convenience.
        r = c.post("/auth/register", json={"email": "test@test.com", "password": "pw123456"})
        assert r.status_code == 201, r.text
        c._auth_header = {"Authorization": f"Bearer {r.json()['access_token']}"}
        yield c
    engine.dispose()


class TestWatchlistRoutes:
    def test_post_get_roundtrip(self, client):
        r = client.post("/watchlists", json={"name": "Tech"}, headers=client._auth_header)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Tech"
        assert body["tickers"] == []
        wid = body["id"]

        g = client.get(f"/watchlists/{wid}", headers=client._auth_header)
        assert g.status_code == 200
        assert g.json()["name"] == "Tech"

        lst = client.get("/watchlists", headers=client._auth_header)
        assert lst.status_code == 200
        assert any(row["id"] == wid for row in lst.json())

    def test_patch_renames(self, client):
        wid = client.post("/watchlists", json={"name": "Old"}, headers=client._auth_header).json()["id"]
        r = client.patch(f"/watchlists/{wid}", json={"name": "New"}, headers=client._auth_header)
        assert r.status_code == 200
        assert r.json()["name"] == "New"

    def test_delete_then_get_404(self, client):
        wid = client.post("/watchlists", json={"name": "Doomed"}, headers=client._auth_header).json()["id"]
        d = client.delete(f"/watchlists/{wid}", headers=client._auth_header)
        assert d.status_code == 204
        g = client.get(f"/watchlists/{wid}", headers=client._auth_header)
        assert g.status_code == 404

    def test_add_ticker_reflects_in_list(self, client):
        wid = client.post("/watchlists", json={"name": "Mega"}, headers=client._auth_header).json()["id"]
        r = client.post(f"/watchlists/{wid}/tickers", json={"ticker": "nvda"}, headers=client._auth_header)
        assert r.status_code == 200
        assert r.json()["tickers"] == ["NVDA"]
        # Idempotent: re-add same ticker → still single entry.
        r2 = client.post(f"/watchlists/{wid}/tickers", json={"ticker": "NVDA"}, headers=client._auth_header)
        assert r2.json()["tickers"] == ["NVDA"]

    def test_remove_ticker(self, client):
        wid = client.post("/watchlists", json={"name": "Mix"}, headers=client._auth_header).json()["id"]
        client.post(f"/watchlists/{wid}/tickers", json={"ticker": "AAPL"}, headers=client._auth_header)
        client.post(f"/watchlists/{wid}/tickers", json={"ticker": "MSFT"}, headers=client._auth_header)
        r = client.delete(f"/watchlists/{wid}/tickers/aapl", headers=client._auth_header)
        assert r.status_code == 200
        assert r.json()["tickers"] == ["MSFT"]
