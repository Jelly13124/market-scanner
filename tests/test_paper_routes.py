"""HTTP route tests for the read-only paper-trading panel.

Uses FastAPI TestClient over an in-memory SQLite DB. The routes are
superuser-only (the paper book is the host's, no per-user scoping), so the
tests assert both the superuser-200 path and the non-superuser-403 gate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.auth.dependencies import get_current_user
from app.backend.database.connection import Base, get_db
from app.backend.database.models import PaperEquityMark, PaperSleeve, User
from app.backend.main import app


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _client_for(user: User, engine):
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def engine():
    eng = _make_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def superuser_client(engine):
    user = User(id=1, email="host@test.com", is_active=True, is_superuser=True)
    client = _client_for(user, engine)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def non_superuser_client(engine):
    user = User(id=2, email="user@test.com", is_active=True, is_superuser=False)
    client = _client_for(user, engine)
    yield client
    app.dependency_overrides.clear()


class TestPerformanceRoute:
    def test_superuser_empty_book_returns_200(self, superuser_client):
        resp = superuser_client.get("/paper/performance")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "sleeves" in body
        assert body["sleeves"] == {}
        assert "graduation" in body
        assert body["graduation"]["passed"] is False

    def test_superuser_with_sleeve_data(self, superuser_client, engine):
        # Seed one sleeve with two marks so metrics populate (not just empty).
        Session = sessionmaker(bind=engine)
        s = Session()
        try:
            sleeve = PaperSleeve(name="scanner_agent", starting_cash=100_000.0)
            s.add(sleeve)
            s.flush()
            s.add(PaperEquityMark(sleeve_id=sleeve.id, date="2026-01-01", equity=100_000.0))
            s.add(PaperEquityMark(sleeve_id=sleeve.id, date="2026-01-02", equity=101_000.0))
            s.commit()
        finally:
            s.close()

        resp = superuser_client.get("/paper/performance")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "scanner_agent" in body["sleeves"]
        assert body["sleeves"]["scanner_agent"]["n_marks"] == 2

    def test_non_superuser_forbidden(self, non_superuser_client):
        resp = non_superuser_client.get("/paper/performance")
        assert resp.status_code == 403, resp.text


class TestEquityChartRoute:
    def test_returns_png_on_empty_book(self, superuser_client):
        # Chart is open-read and returns a placeholder PNG on empty input.
        resp = superuser_client.get("/paper/equity-chart.png")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
