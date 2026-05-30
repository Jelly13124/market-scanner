"""Integration tests for /notifications/* REST routes.

Pattern mirrors ``tests/test_pipeline_routes.py``: load the notifications
router via importlib to avoid pulling routes/__init__.py (which transitively
imports v1 LLM deps). The dispatcher's handlers are patched so /test
sends never actually hit Resend.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import Base, PipelineRun, User
from app.backend.repositories.notification_repository import (
    DeliveryRepository,
    SubscriptionRepository,
)


def _load_notifications_router():
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "app" / "backend" / "routes" / "notifications.py"
    spec = importlib.util.spec_from_file_location("_notif_routes_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_notif_mod = _load_notifications_router()
notifications_router = _notif_mod.router


@pytest.fixture()
def setup(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Stub Resend / webhook handlers so /test never touches the network.
    # The dispatcher imports them via factory inside _handler_for; we
    # monkeypatch the classes the dispatcher will instantiate.
    fake_email = MagicMock()
    fake_email.send.return_value = {
        "status": "ok", "http_code": 200, "message_id": "test_xyz",
        "error_text": None, "latency_ms": 7,
    }
    fake_webhook = MagicMock()
    fake_webhook.send.return_value = {
        "status": "ok", "http_code": 204,
        "error_text": None, "latency_ms": 12,
    }
    import app.backend.services.notifications.dispatcher as disp_mod
    monkeypatch.setattr(disp_mod, "EmailHandler", lambda: fake_email)
    monkeypatch.setattr(disp_mod, "WebhookHandler", lambda: fake_webhook)

    _fake_user = User(id=1, email="test@test.com", is_active=True, is_superuser=False)

    app = FastAPI()
    app.include_router(notifications_router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _fake_user
    # /test route uses SessionLocal directly; patch the route module's
    # reference at import.
    _notif_mod.SessionLocal = SessionLocal

    client = TestClient(app)
    yield client, SessionLocal, fake_email, fake_webhook
    engine.dispose()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCRUD:
    def test_create_email_subscription_minimal(self, setup):
        client, _, _, _ = setup
        r = client.post("/notifications/subscriptions", json={
            "channel": "email", "target": "user@example.com",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["id"] >= 1
        assert body["channel"] == "email"
        assert body["target"] == "user@example.com"
        assert body["enabled"] is True
        assert body["has_auth_header"] is False

    def test_create_webhook_with_auth_header(self, setup):
        client, _, _, _ = setup
        r = client.post("/notifications/subscriptions", json={
            "channel": "webhook",
            "target": "https://hooks.example.com/in/abc",
            "auth_header": "Bearer sekret",
            "label": "ops slack",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["channel"] == "webhook"
        assert body["label"] == "ops slack"
        assert body["has_auth_header"] is True
        # Secret never leaks to the response.
        assert "Bearer sekret" not in r.text

    def test_create_rejects_bad_email(self, setup):
        client, _, _, _ = setup
        r = client.post("/notifications/subscriptions", json={
            "channel": "email", "target": "not-an-email",
        })
        assert r.status_code == 400

    def test_create_rejects_non_https_webhook(self, setup):
        client, _, _, _ = setup
        r = client.post("/notifications/subscriptions", json={
            "channel": "webhook", "target": "ftp://x.com/y",
        })
        assert r.status_code == 400

    def test_create_rejects_auth_header_on_email(self, setup):
        client, _, _, _ = setup
        r = client.post("/notifications/subscriptions", json={
            "channel": "email", "target": "x@y.com",
            "auth_header": "Bearer xyz",
        })
        assert r.status_code == 400

    def test_get_returns_404_for_missing(self, setup):
        client, _, _, _ = setup
        r = client.get("/notifications/subscriptions/9999")
        assert r.status_code == 404

    def test_list_includes_created_row(self, setup):
        client, _, _, _ = setup
        client.post("/notifications/subscriptions",
                    json={"channel": "email", "target": "a@x.com"})
        r = client.get("/notifications/subscriptions")
        assert r.status_code == 200
        body = r.json()
        assert any(s["target"] == "a@x.com" for s in body)

    def test_patch_updates_enabled_flag(self, setup):
        client, _, _, _ = setup
        created = client.post("/notifications/subscriptions",
                              json={"channel": "email", "target": "x@y.com"}).json()
        r = client.patch(f"/notifications/subscriptions/{created['id']}",
                         json={"enabled": False, "label": "renamed"})
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["label"] == "renamed"

    def test_patch_404_for_missing(self, setup):
        client, _, _, _ = setup
        r = client.patch("/notifications/subscriptions/9999",
                         json={"enabled": False})
        assert r.status_code == 404

    def test_delete_removes_row(self, setup):
        client, _, _, _ = setup
        created = client.post("/notifications/subscriptions",
                              json={"channel": "email", "target": "x@y.com"}).json()
        r = client.delete(f"/notifications/subscriptions/{created['id']}")
        assert r.status_code == 204
        # Subsequent GET returns 404.
        assert client.get(f"/notifications/subscriptions/{created['id']}").status_code == 404


# ---------------------------------------------------------------------------
# /test endpoint
# ---------------------------------------------------------------------------


class TestSendTest:
    def _seeded_run(self, SessionLocal):
        with SessionLocal() as s:
            run = PipelineRun(
                id="run00000000000000000000000000aa",
                scan_date="2026-05-18", template="quick",
                selected_analysts=["scanner_signal"], top_n=1,
                universe="nasdaq100", status="COMPLETE", duration_seconds=10.0,
                agent_decisions_json={"AAPL": {"action": "buy", "quantity": 1}},
                analyst_signals_json={},
            )
            s.add(run)
            s.commit()
            return run.id

    def test_returns_delivery_row_with_status_ok(self, setup):
        client, SessionLocal, fake_email, _ = setup
        self._seeded_run(SessionLocal)
        sub = client.post("/notifications/subscriptions",
                          json={"channel": "email", "target": "x@y.com"}).json()
        r = client.post(f"/notifications/subscriptions/{sub['id']}/test")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["http_code"] == 200
        fake_email.send.assert_called_once()

    def test_works_even_when_subscription_disabled(self, setup):
        client, SessionLocal, fake_email, _ = setup
        self._seeded_run(SessionLocal)
        sub = client.post("/notifications/subscriptions",
                          json={"channel": "email", "target": "x@y.com",
                                "enabled": False}).json()
        r = client.post(f"/notifications/subscriptions/{sub['id']}/test")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_uses_synthetic_run_when_no_real_runs(self, setup):
        client, _, fake_email, _ = setup
        # No PipelineRun seeded — dispatcher fabricates a sample.
        sub = client.post("/notifications/subscriptions",
                          json={"channel": "email", "target": "x@y.com"}).json()
        r = client.post(f"/notifications/subscriptions/{sub['id']}/test")
        assert r.status_code == 200
        # The synthetic run's id was passed to the handler.
        run_arg = fake_email.send.call_args.args[1]
        assert "DEMO" in (run_arg.agent_decisions_json or {})

    def test_404_for_missing_subscription(self, setup):
        client, _, _, _ = setup
        r = client.post("/notifications/subscriptions/9999/test")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# /deliveries listing
# ---------------------------------------------------------------------------


class TestDeliveries:
    def test_returns_recent_after_test_send(self, setup):
        client, SessionLocal, _, _ = setup
        sub = client.post("/notifications/subscriptions",
                          json={"channel": "email", "target": "x@y.com"}).json()
        # Two test sends → two delivery rows.
        client.post(f"/notifications/subscriptions/{sub['id']}/test")
        client.post(f"/notifications/subscriptions/{sub['id']}/test")
        r = client.get(f"/notifications/subscriptions/{sub['id']}/deliveries")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        assert all(d["status"] == "ok" for d in body)

    def test_404_for_missing_subscription(self, setup):
        client, _, _, _ = setup
        r = client.get("/notifications/subscriptions/9999/deliveries")
        assert r.status_code == 404
