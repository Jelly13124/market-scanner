"""Unit tests for notification subscriptions + delivery audit log.

Pattern mirrors ``tests/test_pipeline_repository.py`` — in-memory SQLite,
fresh session per test, no live HTTP.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base
from app.backend.repositories.notification_repository import (
    DeliveryRepository,
    SubscriptionRepository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def subs(db_session):
    return SubscriptionRepository(db_session)


@pytest.fixture()
def deliveries(db_session):
    return DeliveryRepository(db_session)


# ---------------------------------------------------------------------------
# SubscriptionRepository
# ---------------------------------------------------------------------------


_UID = 1  # stable fake user_id for repo unit tests


class TestSubscriptionCRUD:
    def test_create_minimal_email_subscription(self, subs):
        row = subs.create(channel="email", target="user@example.com", user_id=_UID)
        assert row.id is not None
        assert row.enabled is True
        assert row.event_type == "pipeline.completed"
        assert row.channel == "email"
        assert row.target == "user@example.com"
        assert row.label is None
        assert row.auth_header is None

    def test_create_webhook_with_auth_header(self, subs):
        row = subs.create(
            channel="webhook",
            target="https://hooks.example.com/in/abc",
            user_id=_UID,
            label="ops slack",
            auth_header="Bearer sekret",
        )
        assert row.channel == "webhook"
        assert row.label == "ops slack"
        assert row.auth_header == "Bearer sekret"

    def test_create_disabled(self, subs):
        row = subs.create(channel="email", target="x@y.com", user_id=_UID, enabled=False)
        assert row.enabled is False

    def test_get_returns_none_for_missing_id(self, subs):
        assert subs.get(9999, user_id=_UID) is None

    def test_get_returns_row(self, subs):
        created = subs.create(channel="email", target="x@y.com", user_id=_UID)
        fetched = subs.get(created.id, user_id=_UID)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_wrong_user_returns_none(self, subs):
        created = subs.create(channel="email", target="x@y.com", user_id=_UID)
        assert subs.get(created.id, user_id=_UID + 1) is None

    def test_get_unscoped_returns_any_user(self, subs):
        created = subs.create(channel="email", target="x@y.com", user_id=_UID)
        assert subs.get_unscoped(created.id) is not None

    def test_list_returns_newest_first(self, subs):
        a = subs.create(channel="email", target="a@example.com", user_id=_UID)
        b = subs.create(channel="email", target="b@example.com", user_id=_UID)
        c = subs.create(channel="email", target="c@example.com", user_id=_UID)
        ids = [r.id for r in subs.list(user_id=_UID)]
        # Newest-first by created_at — SQLite resolves to seconds though, so
        # fall back to id-desc when timestamps tie. Our repo orders by
        # created_at desc; ids should still come out reverse-creation.
        assert ids[0] == c.id
        assert ids[-1] == a.id
        assert b.id in ids

    def test_list_only_shows_own_rows(self, subs):
        subs.create(channel="email", target="a@x.com", user_id=_UID)
        subs.create(channel="email", target="b@x.com", user_id=_UID + 1)
        mine = subs.list(user_id=_UID)
        assert len(mine) == 1
        assert mine[0].target == "a@x.com"

    def test_update_modifies_fields(self, subs):
        row = subs.create(channel="email", target="x@y.com", user_id=_UID, enabled=True)
        updated = subs.update(row.id, user_id=_UID, enabled=False, label="renamed")
        assert updated is not None
        assert updated.enabled is False
        assert updated.label == "renamed"
        # Untouched fields preserved.
        assert updated.target == "x@y.com"

    def test_update_ignores_unknown_keys(self, subs):
        row = subs.create(channel="email", target="x@y.com", user_id=_UID)
        # ``id`` not in allowed set — should be ignored, not raise.
        updated = subs.update(row.id, user_id=_UID, id=9999, enabled=False)
        assert updated.id == row.id
        assert updated.enabled is False

    def test_update_returns_none_for_missing_id(self, subs):
        assert subs.update(9999, user_id=_UID, enabled=False) is None

    def test_update_none_value_skipped(self, subs):
        # Patch semantics: explicit None should not overwrite existing value.
        row = subs.create(channel="email", target="x@y.com", user_id=_UID, label="keep me")
        updated = subs.update(row.id, user_id=_UID, label=None)
        assert updated.label == "keep me"

    def test_delete_removes_row(self, subs):
        row = subs.create(channel="email", target="x@y.com", user_id=_UID)
        assert subs.delete(row.id, user_id=_UID) is True
        assert subs.get(row.id, user_id=_UID) is None

    def test_delete_returns_false_for_missing(self, subs):
        assert subs.delete(9999, user_id=_UID) is False


class TestListEnabledForEvent:
    def test_filters_by_enabled_and_event(self, subs):
        # Enabled, matches event → included
        a = subs.create(channel="email", target="a@x.com", user_id=_UID, enabled=True)
        # Disabled → excluded
        subs.create(channel="email", target="b@x.com", user_id=_UID, enabled=False)
        # Different event_type → excluded
        subs.create(channel="email", target="c@x.com", user_id=_UID, enabled=True, event_type="other.event")
        # Enabled + matching (different user) → still included (unscoped)
        d = subs.create(channel="webhook", target="https://x", user_id=_UID + 1, enabled=True)

        rows = subs.list_enabled_for_event("pipeline.completed")
        ids = [r.id for r in rows]
        assert a.id in ids
        assert d.id in ids
        assert len(ids) == 2

    def test_empty_when_no_matches(self, subs):
        subs.create(channel="email", target="x@y.com", user_id=_UID, enabled=False)
        assert subs.list_enabled_for_event("pipeline.completed") == []


# ---------------------------------------------------------------------------
# DeliveryRepository
# ---------------------------------------------------------------------------


class TestDeliveryRecording:
    def test_record_ok_attempt(self, subs, deliveries):
        sub = subs.create(channel="email", target="x@y.com", user_id=_UID)
        row = deliveries.record(
            subscription_id=sub.id, run_id="abc123",
            status="ok", http_code=200, latency_ms=412,
        )
        assert row.id is not None
        assert row.subscription_id == sub.id
        assert row.run_id == "abc123"
        assert row.status == "ok"
        assert row.http_code == 200
        assert row.latency_ms == 412
        assert row.error_text is None
        assert row.attempted_at is not None

    def test_record_error_attempt(self, subs, deliveries):
        sub = subs.create(channel="webhook", target="https://x", user_id=_UID)
        row = deliveries.record(
            subscription_id=sub.id, run_id=None,
            status="error", http_code=500,
            error_text="connection refused", latency_ms=10000,
        )
        assert row.status == "error"
        assert row.http_code == 500
        assert row.error_text == "connection refused"
        assert row.run_id is None

    def test_error_text_truncated(self, subs, deliveries):
        sub = subs.create(channel="email", target="x@y.com", user_id=_UID)
        long_err = "x" * 5000
        row = deliveries.record(
            subscription_id=sub.id, run_id="r1",
            status="error", error_text=long_err,
        )
        assert len(row.error_text) <= 4001  # 4000 + ellipsis
        assert row.error_text.endswith("…")

    def test_list_recent_newest_first(self, subs, deliveries):
        sub = subs.create(channel="email", target="x@y.com", user_id=_UID)
        for i in range(5):
            deliveries.record(
                subscription_id=sub.id, run_id=f"r{i}",
                status="ok", http_code=200,
            )
        rows = deliveries.list_recent(sub.id, limit=10)
        assert len(rows) == 5
        # Newest first — last-inserted r4 should be first.
        assert rows[0].run_id == "r4"
        assert rows[-1].run_id == "r0"

    def test_list_recent_respects_limit(self, subs, deliveries):
        sub = subs.create(channel="email", target="x@y.com", user_id=_UID)
        for i in range(10):
            deliveries.record(subscription_id=sub.id, run_id=f"r{i}", status="ok")
        assert len(deliveries.list_recent(sub.id, limit=3)) == 3

    def test_list_recent_filters_by_subscription(self, subs, deliveries):
        s1 = subs.create(channel="email", target="a@x.com", user_id=_UID)
        s2 = subs.create(channel="email", target="b@x.com", user_id=_UID)
        deliveries.record(subscription_id=s1.id, run_id="r1", status="ok")
        deliveries.record(subscription_id=s2.id, run_id="r2", status="ok")
        rows = deliveries.list_recent(s1.id)
        assert len(rows) == 1
        assert rows[0].run_id == "r1"
