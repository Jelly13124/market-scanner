from __future__ import annotations
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.backend.database import get_db
from app.backend.database.models import Base
from app.backend.repositories.screener_repository import ScreenerRepository, SnapshotRow
from app.backend.routes.auth import router as auth_router
from app.backend.routes.screener import router as screener_router
from app.backend.services.scheduler_service import get_scheduler_service


@pytest.fixture()
def client():
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    def override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(screener_router)
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_scheduler_service] = lambda: MagicMock()
    db = TS()
    ScreenerRepository(db).bulk_upsert([
        SnapshotRow(ticker="AAPL", market="US", snapshot_date=date(2026, 5, 28),
                    price=Decimal("210"), market_cap=Decimal("3.2e12"),
                    pe_ttm=Decimal("32"), sector="Technology", data_source="t"),
        SnapshotRow(ticker="JPM", market="US", snapshot_date=date(2026, 5, 28),
                    price=Decimal("180"), market_cap=Decimal("5e11"),
                    pe_ttm=Decimal("11"), sector="Financial Services", data_source="t"),
    ])
    db.close()
    return TestClient(app)


def _token(client):
    r = client.post("/auth/register", json={"email": "u@test.com", "password": "pw123456"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def test_crud_lifecycle(client):
    tok = _token(client)
    r = client.post("/screener/presets", json={"name": "cheap", "market": "US",
                    "filters": {"pe_max": 20}}, headers=_hdr(tok))
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert client.get("/screener/presets", headers=_hdr(tok)).json()[0]["name"] == "cheap"
    r = client.patch(f"/screener/presets/{pid}", json={"schedule_enabled": True},
                     headers=_hdr(tok))
    assert r.json()["schedule_enabled"] is True
    run = client.post(f"/screener/presets/{pid}/run", headers=_hdr(tok)).json()
    assert run["total_count"] == 1 and run["rows"][0]["ticker"] == "JPM"
    assert client.delete(f"/screener/presets/{pid}", headers=_hdr(tok)).status_code == 204
    assert client.get("/screener/presets", headers=_hdr(tok)).json() == []


def test_patch_404(client):
    tok = _token(client)
    assert client.patch("/screener/presets/999", json={"name": "x"},
                        headers=_hdr(tok)).status_code == 404
