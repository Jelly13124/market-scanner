"""Integration tests for /pipeline/* REST routes.

Mirrors the pattern from ``tests/test_scanner_routes.py``: load the pipeline
router via importlib to avoid pulling routes/__init__.py (which transitively
imports v1 LLM deps not present in the test env). The orchestrator is
patched at the module level so the routes test never actually invokes
``run_scan`` or ``run_hedge_fund``.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    # The route also imports SessionLocal directly for the background task —
    # patch it to point at our in-memory engine so background work writes
    # to the same DB as the test.
    _pipeline_mod.SessionLocal = SessionLocal

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


def _fake_pipeline_result(**_ignored):
    """Stand-in for run_pipeline(...) — accepts any kwargs the route passes."""
    from v2.pipeline.orchestrator import PipelineResult

    return PipelineResult(
        run_id="ignored",
        scan_date="2024-08-01",
        template="quick",
        selected_analysts=["scanner_signal", "fundamentals_analyst"],
        universe="custom",
        top_n=1,
        watchlist=[{"ticker": "AAPL", "rank": 1, "composite_score": 80.0}],
        agent_decisions={"AAPL": {"action": "hold", "quantity": 0}},
        analyst_signals={"scanner_signal_agent": {"AAPL": {"signal": "bullish", "confidence": 80, "reasoning": "x"}}},
        duration_seconds=1.5,
        status="complete",
    )


class TestRunEndpoint:
    def test_rejects_both_template_and_custom(self, setup):
        client, _ = setup
        r = client.post(
            "/pipeline/run",
            json={
                "template": "quick",
                "custom_analysts": ["warren_buffett"],
            },
        )
        assert r.status_code == 422  # Pydantic validation fires first

    def test_rejects_unknown_template_400_after_pydantic(self, setup):
        client, _ = setup
        # Pydantic accepts the string (no enum), then resolve_analysts raises.
        r = client.post("/pipeline/run", json={"template": "no_such_template"})
        assert r.status_code == 400
        assert "unknown template" in r.json()["detail"]

    def test_run_returns_pending_immediately(self, setup):
        client, SessionLocal = setup
        with patch.object(_pipeline_mod, "run_pipeline", side_effect=_fake_pipeline_result):
            r = client.post(
                "/pipeline/run",
                json={
                    "universe": "custom",
                    "universe_tickers": ["AAPL"],
                    "template": "quick",
                    "top_n": 1,
                },
            )
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "PENDING"
        run_id = body["run_id"]
        assert len(run_id) == 32  # uuid hex

        # Wait briefly for the BackgroundTask to settle.
        deadline = time.time() + 3.0
        with SessionLocal() as db:
            repo = PipelineRunRepository(db)
            while time.time() < deadline:
                row = repo.get_by_id(run_id)
                if row and row.status == "COMPLETE":
                    break
                time.sleep(0.05)
            row = repo.get_by_id(run_id)
        assert row is not None
        assert row.status == "COMPLETE"
        assert row.watchlist_json == [{"ticker": "AAPL", "rank": 1, "composite_score": 80.0}]
        assert row.duration_seconds == 1.5

    def test_run_error_path_marks_row_with_traceback(self, setup):
        client, SessionLocal = setup

        def boom(**kw):
            raise RuntimeError("simulated provider failure")

        with patch.object(_pipeline_mod, "run_pipeline", side_effect=boom):
            r = client.post(
                "/pipeline/run",
                json={
                    "universe": "custom",
                    "universe_tickers": ["AAPL"],
                    "template": "quick",
                    "top_n": 1,
                },
            )
        run_id = r.json()["run_id"]

        deadline = time.time() + 3.0
        with SessionLocal() as db:
            repo = PipelineRunRepository(db)
            while time.time() < deadline:
                row = repo.get_by_id(run_id)
                if row and row.status == "ERROR":
                    break
                time.sleep(0.05)
            row = repo.get_by_id(run_id)
        assert row.status == "ERROR"
        assert "simulated provider failure" in row.error
        assert "RuntimeError" in row.error


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

    def test_patch_enables_and_changes_template(self, setup):
        client, _ = setup
        r = client.patch("/pipeline/schedule", json={"enabled": True, "template": "quick"})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        assert r.json()["template"] == "quick"

    def test_patch_unknown_template_400(self, setup):
        client, _ = setup
        r = client.patch("/pipeline/schedule", json={"template": "no_such"})
        assert r.status_code == 400
        assert "unknown template" in r.json()["detail"]
