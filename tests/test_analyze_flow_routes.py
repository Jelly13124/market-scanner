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


def _token(client):
    r = client.post("/auth/register", json={"email": "af@test.com", "password": "pw123456"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


class TestAnalyzeFlowRoutes:
    def test_create_then_list_then_get(self, client):
        tok = _token(client)
        resp = client.post("/analyze-flows", json={
            "name": "balanced",
            "included_sections": ["data_health", "executive_summary"],
            "use_personas": True,
            "persona_overrides": {"valuation": "graham"},
        }, headers=_hdr(tok))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        flow_id = body["id"]
        assert body["name"] == "balanced"
        assert body["persona_overrides"] == {"valuation": "graham"}

        # list shows it
        resp_list = client.get("/analyze-flows", headers=_hdr(tok))
        assert resp_list.status_code == 200
        rows = resp_list.json()
        assert any(r["id"] == flow_id for r in rows)

        # get by id
        resp_get = client.get(f"/analyze-flows/{flow_id}", headers=_hdr(tok))
        assert resp_get.status_code == 200
        assert resp_get.json()["name"] == "balanced"

    def test_create_duplicate_name_409(self, client):
        tok = _token(client)
        client.post("/analyze-flows", json={
            "name": "dupe", "included_sections": ["data_health"],
        }, headers=_hdr(tok))
        resp = client.post("/analyze-flows", json={
            "name": "dupe", "included_sections": ["macro"],
        }, headers=_hdr(tok))
        assert resp.status_code == 409

    def test_patch_updates_fields(self, client):
        tok = _token(client)
        c = client.post("/analyze-flows", json={
            "name": "tweak", "included_sections": ["data_health"],
        }, headers=_hdr(tok))
        flow_id = c.json()["id"]
        resp = client.patch(f"/analyze-flows/{flow_id}", json={
            "included_sections": ["macro", "sector"],
            "use_personas": True,
        }, headers=_hdr(tok))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["included_sections"] == ["macro", "sector"]
        assert body["use_personas"] is True
        # name not in PATCH body → unchanged
        assert body["name"] == "tweak"

    def test_delete_404_after_delete(self, client):
        tok = _token(client)
        c = client.post("/analyze-flows", json={
            "name": "gone", "included_sections": [],
        }, headers=_hdr(tok))
        flow_id = c.json()["id"]
        d = client.delete(f"/analyze-flows/{flow_id}", headers=_hdr(tok))
        assert d.status_code == 204
        g = client.get(f"/analyze-flows/{flow_id}", headers=_hdr(tok))
        assert g.status_code == 404
