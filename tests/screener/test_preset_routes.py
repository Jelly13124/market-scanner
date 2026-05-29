from __future__ import annotations
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.backend.database import get_db
from app.backend.database.models import Base
from app.backend.repositories.screener_repository import ScreenerRepository, SnapshotRow
from app.backend.routes.screener import router as screener_router


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

    app = FastAPI(); app.include_router(screener_router)
    app.dependency_overrides[get_db] = override
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


def test_crud_lifecycle(client):
    r = client.post("/screener/presets", json={"name": "cheap", "market": "US",
                    "filters": {"pe_max": 20}})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert client.get("/screener/presets").json()[0]["name"] == "cheap"
    r = client.patch(f"/screener/presets/{pid}", json={"schedule_enabled": True})
    assert r.json()["schedule_enabled"] is True
    run = client.post(f"/screener/presets/{pid}/run").json()
    assert run["total_count"] == 1 and run["rows"][0]["ticker"] == "JPM"
    assert client.delete(f"/screener/presets/{pid}").status_code == 204
    assert client.get("/screener/presets").json() == []


def test_patch_404(client):
    assert client.patch("/screener/presets/999", json={"name": "x"}).status_code == 404
