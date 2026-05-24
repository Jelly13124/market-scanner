"""REST tests for /analyze-flows (Phase 5D)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base, get_db
from app.backend.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


class TestAnalyzeFlowRoutes:
    def test_create_then_list_then_get(self, client):
        resp = client.post("/analyze-flows", json={
            "name": "balanced",
            "included_sections": ["data_health", "executive_summary"],
            "use_personas": True,
            "persona_overrides": {"valuation": "graham"},
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        flow_id = body["id"]
        assert body["name"] == "balanced"
        assert body["persona_overrides"] == {"valuation": "graham"}

        # list shows it
        resp_list = client.get("/analyze-flows")
        assert resp_list.status_code == 200
        rows = resp_list.json()
        assert any(r["id"] == flow_id for r in rows)

        # get by id
        resp_get = client.get(f"/analyze-flows/{flow_id}")
        assert resp_get.status_code == 200
        assert resp_get.json()["name"] == "balanced"

    def test_create_duplicate_name_409(self, client):
        client.post("/analyze-flows", json={
            "name": "dupe", "included_sections": ["data_health"],
        })
        resp = client.post("/analyze-flows", json={
            "name": "dupe", "included_sections": ["macro"],
        })
        assert resp.status_code == 409

    def test_patch_updates_fields(self, client):
        c = client.post("/analyze-flows", json={
            "name": "tweak", "included_sections": ["data_health"],
        })
        flow_id = c.json()["id"]
        resp = client.patch(f"/analyze-flows/{flow_id}", json={
            "included_sections": ["macro", "sector"],
            "use_personas": True,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["included_sections"] == ["macro", "sector"]
        assert body["use_personas"] is True
        # name not in PATCH body → unchanged
        assert body["name"] == "tweak"

    def test_delete_404_after_delete(self, client):
        c = client.post("/analyze-flows", json={
            "name": "gone", "included_sections": [],
        })
        flow_id = c.json()["id"]
        d = client.delete(f"/analyze-flows/{flow_id}")
        assert d.status_code == 204
        g = client.get(f"/analyze-flows/{flow_id}")
        assert g.status_code == 404
