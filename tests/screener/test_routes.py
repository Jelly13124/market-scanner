"""Screener route tests — TestClient against an in-memory SQLite DB."""
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
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(screener_router)
    app.dependency_overrides[get_db] = override_get_db

    db = TestingSession()
    repo = ScreenerRepository(db)
    repo.bulk_upsert([
        SnapshotRow(ticker="AAPL", market="US", snapshot_date=date(2026, 5, 27),
                    price=Decimal("210"), market_cap=Decimal("3.2e12"),
                    pe_ttm=Decimal("32"), sector="Technology",
                    analyst_rating="buy", data_source="yfinance"),
        SnapshotRow(ticker="JPM", market="US", snapshot_date=date(2026, 5, 27),
                    price=Decimal("180"), market_cap=Decimal("5.0e11"),
                    pe_ttm=Decimal("11"), sector="Financial Services",
                    analyst_rating="neutral", data_source="yfinance"),
        SnapshotRow(ticker="600519.SH", market="CN", snapshot_date=date(2026, 5, 27),
                    price=Decimal("1700"), market_cap=Decimal("2.1e12"),
                    pe_ttm=Decimal("28"), sector="白酒",
                    data_source="mootdx+akshare"),
    ])
    db.close()

    yield TestClient(app), TestingSession


def test_get_columns_returns_16_chips(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/columns")
    assert r.status_code == 200
    body = r.json()
    assert len(body["columns"]) == 16


def test_get_status_reports_counts(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/status")
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == 3
    assert body["by_market"] == {"US": 2, "CN": 1}


def test_get_latest_no_filter_returns_all(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 3
    assert len(body["rows"]) == 3


def test_get_latest_market_filter(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?market=CN")
    body = r.json()
    assert body["total_count"] == 1
    assert body["rows"][0]["ticker"] == "600519.SH"


def test_get_latest_range_filter(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?market=US&pe_max=20")
    body = r.json()
    assert body["total_count"] == 1
    assert body["rows"][0]["ticker"] == "JPM"


def test_get_latest_multi_select_filter(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?sector_in=Technology,Financial%20Services")
    body = r.json()
    assert {row["ticker"] for row in body["rows"]} == {"AAPL", "JPM"}


def test_get_latest_sort_desc(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?sort_by=market_cap&sort_dir=desc&limit=10")
    body = r.json()
    tickers = [row["ticker"] for row in body["rows"]]
    assert tickers[0] in ("AAPL", "600519.SH")  # both 2T+ mcap


def test_get_latest_invalid_market_returns_422(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?market=XX")
    assert r.status_code == 422


def test_get_latest_empty_db_returns_empty(client_and_db):
    client, TestingSession = client_and_db
    db = TestingSession()
    from app.backend.database.models import TickerSnapshot
    db.query(TickerSnapshot).delete()
    db.commit()
    db.close()
    r = client.get("/screener/snapshot/latest")
    assert r.status_code == 200
    assert r.json()["total_count"] == 0
