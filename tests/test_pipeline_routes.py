"""Integration tests for /pipeline/* REST routes.

Mirrors the pattern from ``tests/test_scanner_routes.py``: load the pipeline
router via importlib to avoid pulling routes/__init__.py (which transitively
imports v1 LLM deps not present in the test env). The retired trigger creates no work; historical reads remain available.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import Base, PipelineSchedule, User
from app.backend.repositories.pipeline_repository import PipelineRunRepository


def _load_pipeline_router():
    """Load app/backend/routes/pipeline.py without triggering routes/__init__.py."""
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "app" / "backend" / "routes" / "pipeline.py"
    spec = importlib.util.spec_from_file_location("_pipeline_routes_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_pipeline_mod = _load_pipeline_router()
pipeline_router = _pipeline_mod.router


@pytest.fixture()
def setup():
    """In-memory SQLite + an isolated FastAPI app with only the pipeline router.

    StaticPool keeps the single in-memory DB connection alive across sessions —
    otherwise each new session would create its own (empty) :memory: DB.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Seed singleton schedule row (alembic does this in production).
    s = SessionLocal()
    s.add(
        PipelineSchedule(
            id=1,
            enabled=False,
            top_n=5,
            template="balanced",
            universe="nasdaq100",
            model_name="gpt-4.1",
            model_provider="OpenAI",
            user_id=1,
        )
    )
    s.commit()
    s.close()

    app = FastAPI()
    app.include_router(pipeline_router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Fake authenticated user (id=1) for every route that calls
    # get_current_user. Runs/schedule are scoped to user_id == 1.
    _fake_user = User(id=1, email="test@test.com", is_active=True, is_superuser=False)
    app.dependency_overrides[get_current_user] = lambda: _fake_user
    client = TestClient(app)
    yield client, SessionLocal
    engine.dispose()


# ---------------------------------------------------------------------------
# GET /pipeline/templates
# ---------------------------------------------------------------------------


class TestTemplatesEndpoint:
    def test_returns_templates_default_and_agents(self, setup):
        client, _ = setup
        r = client.get("/pipeline/templates")
        assert r.status_code == 200
        body = r.json()
        assert "balanced" in body["templates"]
        assert body["default_template"] == "balanced"
        # scanner_signal is registered → it must be in agents list
        agent_keys = {a["key"] for a in body["agents"]}
        assert "scanner_signal" in agent_keys


# ---------------------------------------------------------------------------
# POST /pipeline/run
# ---------------------------------------------------------------------------


class TestRunEndpoint:
    def test_retired_run_creates_no_work(self, setup):
        client, session_factory = setup
        with patch.object(PipelineRunRepository, "create_pending") as create:
            response = client.post("/pipeline/run", json={"template": "quick"})
        assert response.status_code == 410
        assert "/research/analyze" in response.json()["detail"]
        create.assert_not_called()
        with session_factory() as db:
            assert PipelineRunRepository(db).list_runs(user_id=1) == []


# ---------------------------------------------------------------------------
# GET /pipeline/runs[/{id}]
# ---------------------------------------------------------------------------


class TestRunsListing:
    def test_list_empty(self, setup):
        client, _ = setup
        r = client.get("/pipeline/runs")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_404_for_missing_run(self, setup):
        client, _ = setup
        r = client.get("/pipeline/runs/nonexistent")
        assert r.status_code == 404

    def test_list_after_writing_rows_via_repo(self, setup):
        client, SessionLocal = setup
        with SessionLocal() as db:
            repo = PipelineRunRepository(db)
            # user_id=1 matches the fake authenticated user; the list route
            # scopes by it.
            repo.create_pending(
                run_id="aaa",
                scan_date="2024-08-01",
                template="quick",
                selected_analysts=["scanner_signal"],
                top_n=1,
                universe="nasdaq100",
                user_id=1,
            )
        r = client.get("/pipeline/runs?limit=10")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["id"] == "aaa"
        assert body[0]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# GET/PATCH /pipeline/schedule
# ---------------------------------------------------------------------------


class TestScheduleEndpoint:
    def test_get_creates_defaults_row_for_caller(self, setup):
        # No row exists for user_id=1 yet → route lazily creates one with
        # defaults (cron OFF, balanced template).
        client, _ = setup
        r = client.get("/pipeline/schedule")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["template"] == "balanced"

    def test_patch_rejects_retired_schedule_enable(self, setup):
        client, _ = setup
        r = client.patch("/pipeline/schedule", json={"enabled": True, "template": "quick"})
        assert r.status_code == 410
        assert "removed" in r.json()["detail"]

    def test_patch_unknown_template_400(self, setup):
        client, _ = setup
        r = client.patch("/pipeline/schedule", json={"template": "no_such"})
        assert r.status_code == 400
        assert "unknown template" in r.json()["detail"]
