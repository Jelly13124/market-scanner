"""Tenant-isolation tests for /pipeline/* routes.

User A's pipeline runs and per-user schedule are invisible to user B:

  - B's run list never contains A's runs; GET of A's run id → 404.
  - The ``pipeline_schedule`` row is per-user (it was a global id=1
    singleton). A PATCH by A does not change B's schedule, and each user's
    GET returns their own row (created lazily on first access).

POST /pipeline/run kicks off a real BackgroundTask, so these tests seed
``PipelineRun`` rows directly in the DB (via the app's get_db override)
rather than invoking the orchestrator.
"""

from __future__ import annotations

from app.backend.database import get_db
from app.backend.database.models import PipelineRun
from tests.auth.conftest import auth_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(client, token: str) -> int:
    """Resolve a token's user id via /auth/me (avoids hardcoding ids)."""
    r = client.get("/auth/me", headers=auth_header(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_run(client, run_id: str, *, user_id: int | None) -> None:
    """Insert a COMPLETE pipeline run owned by ``user_id`` straight into the DB."""
    override_fn = client.app.dependency_overrides.get(get_db)
    gen = override_fn()
    db = next(gen)
    try:
        db.add(
            PipelineRun(
                id=run_id,
                scan_date="2024-08-01",
                template="balanced",
                selected_analysts=["scanner_signal"],
                top_n=5,
                universe="nasdaq100",
                status="COMPLETE",
                user_id=user_id,
            )
        )
        db.commit()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# ---------------------------------------------------------------------------
# Pipeline run isolation
# ---------------------------------------------------------------------------


class TestPipelineRunIsolation:
    def test_b_cannot_see_a_run_in_list(self, full_client, two_users):
        tok_a, tok_b = two_users
        _seed_run(full_client, "run_a", user_id=_uid(full_client, tok_a))

        r = full_client.get("/pipeline/runs", headers=auth_header(tok_b))
        assert r.status_code == 200
        assert all(row["id"] != "run_a" for row in r.json())

    def test_a_sees_own_run_in_list(self, full_client, two_users):
        tok_a, _ = two_users
        _seed_run(full_client, "run_a", user_id=_uid(full_client, tok_a))

        r = full_client.get("/pipeline/runs", headers=auth_header(tok_a))
        assert r.status_code == 200
        assert any(row["id"] == "run_a" for row in r.json())

    def test_b_cannot_get_a_run_detail(self, full_client, two_users):
        tok_a, tok_b = two_users
        _seed_run(full_client, "run_a", user_id=_uid(full_client, tok_a))

        r = full_client.get("/pipeline/runs/run_a", headers=auth_header(tok_b))
        assert r.status_code == 404

    def test_a_can_get_own_run_detail(self, full_client, two_users):
        tok_a, _ = two_users
        _seed_run(full_client, "run_a", user_id=_uid(full_client, tok_a))

        r = full_client.get("/pipeline/runs/run_a", headers=auth_header(tok_a))
        assert r.status_code == 200
        assert r.json()["id"] == "run_a"


# ---------------------------------------------------------------------------
# Per-user schedule isolation
# ---------------------------------------------------------------------------


class TestPipelineScheduleIsolation:
    def test_schedule_is_per_user(self, full_client, two_users):
        tok_a, tok_b = two_users

        # A enables their schedule and switches template.
        ra = full_client.patch(
            "/pipeline/schedule",
            json={"enabled": True, "template": "quick", "top_n": 9},
            headers=auth_header(tok_a),
        )
        assert ra.status_code == 200
        assert ra.json()["enabled"] is True
        assert ra.json()["template"] == "quick"

        # B's schedule is untouched — lazily created with defaults.
        rb = full_client.get("/pipeline/schedule", headers=auth_header(tok_b))
        assert rb.status_code == 200
        assert rb.json()["enabled"] is False
        assert rb.json()["template"] == "balanced"
        assert rb.json()["top_n"] == 5

        # A still sees their own edits on a fresh GET.
        ra2 = full_client.get("/pipeline/schedule", headers=auth_header(tok_a))
        assert ra2.json()["enabled"] is True
        assert ra2.json()["top_n"] == 9


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


def test_pipeline_requires_auth(full_client):
    assert full_client.get("/pipeline/runs").status_code == 401
    assert full_client.get("/pipeline/runs/anything").status_code == 401
    assert full_client.get("/pipeline/schedule").status_code == 401
    assert full_client.patch("/pipeline/schedule", json={}).status_code == 401
