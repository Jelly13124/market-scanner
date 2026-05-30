"""NotificationDispatcher tests — handlers stubbed.

Exercises:
  * dispatch() fans out to all enabled subs matching event_type
  * Each attempt is recorded in NotificationDelivery
  * Handler exceptions are caught + logged + recorded (don't propagate)
  * dispatch_to() works for /test sends, fabricates synthetic run when empty
  * Returns None for missing subscription id
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, PipelineRun
from app.backend.repositories.notification_repository import (
    DeliveryRepository,
    SubscriptionRepository,
)
from app.backend.services.notifications.dispatcher import NotificationDispatcher


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield SessionLocal
    engine.dispose()


@pytest.fixture()
def seeded_run(session_factory):
    """Insert one PipelineRun + return its id."""
    with session_factory() as s:
        run = PipelineRun(
            id="run0000000000000000000000000001",
            scan_date="2026-05-18", template="quick",
            selected_analysts=["scanner_signal"], top_n=1,
            universe="nasdaq100", status="COMPLETE", duration_seconds=10.0,
            agent_decisions_json={"AAPL": {"action": "buy", "quantity": 1}},
            analyst_signals_json={},
        )
        s.add(run)
        s.commit()
        return run.id


def _ok_handler():
    h = MagicMock()
    h.send.return_value = {
        "status": "ok", "http_code": 200, "error_text": None, "latency_ms": 50,
    }
    return h


def _err_handler():
    h = MagicMock()
    h.send.return_value = {
        "status": "error", "http_code": 500,
        "error_text": "boom", "latency_ms": 100,
    }
    return h


class TestDispatch:
    def test_zero_subscriptions_returns_zero(self, session_factory, seeded_run):
        d = NotificationDispatcher(
            session_factory,
            email_handler=_ok_handler(), webhook_handler=_ok_handler(),
        )
        n = d.dispatch(run_id=seeded_run)
        assert n == 0

    def test_fans_out_to_enabled_subs_only(self, session_factory, seeded_run):
        with session_factory() as s:
            subs = SubscriptionRepository(s)
            sub1 = subs.create(channel="email", target="a@x.com", user_id=1, enabled=True)
            sub2 = subs.create(channel="email", target="b@x.com", user_id=1, enabled=False)
            sub3 = subs.create(channel="webhook", target="https://x", user_id=1, enabled=True)
            ids = (sub1.id, sub2.id, sub3.id)

        email = _ok_handler()
        webhook = _ok_handler()
        d = NotificationDispatcher(session_factory,
                                   email_handler=email, webhook_handler=webhook)
        n = d.dispatch(run_id=seeded_run)
        assert n == 2
        assert email.send.call_count == 1
        assert webhook.send.call_count == 1

    def test_records_attempt_per_subscription(self, session_factory, seeded_run):
        with session_factory() as s:
            sub = SubscriptionRepository(s).create(channel="email", target="x@y.com", user_id=1)
            sub_id = sub.id

        d = NotificationDispatcher(
            session_factory,
            email_handler=_ok_handler(), webhook_handler=_ok_handler(),
        )
        d.dispatch(run_id=seeded_run)

        with session_factory() as s:
            rows = DeliveryRepository(s).list_recent(sub_id)
        assert len(rows) == 1
        assert rows[0].status == "ok"
        assert rows[0].http_code == 200
        assert rows[0].run_id == seeded_run

    def test_missing_run_skips_dispatch(self, session_factory):
        with session_factory() as s:
            SubscriptionRepository(s).create(channel="email", target="x@y.com", user_id=1)
        email = _ok_handler()
        d = NotificationDispatcher(session_factory, email_handler=email)
        n = d.dispatch(run_id="nonexistent_run_id_xxxxxxxxxxxx")
        assert n == 0
        email.send.assert_not_called()

    def test_handler_exception_recorded_as_error(self, session_factory, seeded_run):
        with session_factory() as s:
            sub = SubscriptionRepository(s).create(channel="email", target="x@y.com", user_id=1)
            sub_id = sub.id

        bad = MagicMock()
        bad.send.side_effect = RuntimeError("kaboom")
        d = NotificationDispatcher(session_factory, email_handler=bad)
        # Must not raise.
        d.dispatch(run_id=seeded_run)
        with session_factory() as s:
            rows = DeliveryRepository(s).list_recent(sub_id)
        assert len(rows) == 1
        assert rows[0].status == "error"
        assert "kaboom" in rows[0].error_text

    def test_unknown_channel_recorded_as_error(self, session_factory, seeded_run):
        with session_factory() as s:
            sub = SubscriptionRepository(s).create(
                channel="carrier-pigeon", target="coop", user_id=1, enabled=True,
            )
            sub_id = sub.id
        d = NotificationDispatcher(session_factory)
        d.dispatch(run_id=seeded_run)
        with session_factory() as s:
            rows = DeliveryRepository(s).list_recent(sub_id)
        assert len(rows) == 1
        assert rows[0].status == "error"
        assert "carrier-pigeon" in rows[0].error_text


class TestDispatchTo:
    def test_returns_none_for_unknown_subscription(self, session_factory):
        d = NotificationDispatcher(session_factory, email_handler=_ok_handler())
        assert d.dispatch_to(subscription_id=9999, run_id=None) is None

    def test_uses_latest_run_when_run_id_omitted(self, session_factory, seeded_run):
        with session_factory() as s:
            sub = SubscriptionRepository(s).create(channel="email", target="x@y.com", user_id=1)
            sub_id = sub.id
        email = _ok_handler()
        d = NotificationDispatcher(session_factory, email_handler=email)
        result = d.dispatch_to(subscription_id=sub_id, run_id=None)
        assert result["status"] == "ok"
        # The run handed to the handler was the seeded one.
        run_passed = email.send.call_args.args[1]
        assert run_passed.id == seeded_run

    def test_synthetic_run_when_no_real_runs(self, session_factory):
        with session_factory() as s:
            sub = SubscriptionRepository(s).create(channel="email", target="x@y.com", user_id=1)
            sub_id = sub.id
        email = _ok_handler()
        d = NotificationDispatcher(session_factory, email_handler=email)
        result = d.dispatch_to(subscription_id=sub_id, run_id=None)
        assert result["status"] == "ok"
        run_passed = email.send.call_args.args[1]
        assert "DEMO" in (run_passed.agent_decisions_json or {})

    def test_dispatch_to_ignores_disabled_flag(self, session_factory, seeded_run):
        # /test endpoint must work even when sub is currently disabled,
        # so the user can validate config before enabling.
        with session_factory() as s:
            sub = SubscriptionRepository(s).create(
                channel="email", target="x@y.com", user_id=1, enabled=False,
            )
            sub_id = sub.id
        d = NotificationDispatcher(session_factory, email_handler=_ok_handler())
        result = d.dispatch_to(subscription_id=sub_id, run_id=seeded_run)
        assert result["status"] == "ok"
