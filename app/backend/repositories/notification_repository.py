"""Repositories for notification subscriptions + delivery audit log.

Same shape as ``pipeline_repository.py``: sync, Session-injected, one
commit per write, no business logic. The dispatcher and routes call into
these.

Wave 4 (Task 4.3): HTTP-facing methods (create/get/list/update/delete)
are scoped by ``user_id``.  ``list_enabled_for_event`` intentionally
stays UNSCOPED so the dispatcher can see every user's active subscriptions
when fanning out a cron event.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import (
    NotificationDelivery,
    NotificationSubscription,
)


class SubscriptionRepository:
    """CRUD for ``NotificationSubscription``."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        channel: str,
        target: str,
        user_id: int,
        label: str | None = None,
        enabled: bool = True,
        event_type: str = "pipeline.completed",
        auth_header: str | None = None,
    ) -> NotificationSubscription:
        row = NotificationSubscription(
            channel=channel,
            target=target,
            label=label,
            enabled=enabled,
            event_type=event_type,
            auth_header=auth_header,
            user_id=user_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get(self, sub_id: int, *, user_id: int) -> Optional[NotificationSubscription]:
        """Scoped lookup — returns None for cross-tenant access (404 in routes)."""
        return (
            self.db.query(NotificationSubscription)
            .filter(
                NotificationSubscription.id == sub_id,
                NotificationSubscription.user_id == user_id,
            )
            .first()
        )

    def get_unscoped(self, sub_id: int) -> Optional[NotificationSubscription]:
        """Unscoped lookup — for internal callers (dispatcher /test route)."""
        return (
            self.db.query(NotificationSubscription)
            .filter(NotificationSubscription.id == sub_id)
            .first()
        )

    def list(self, *, user_id: int) -> list[NotificationSubscription]:
        """Caller's subs, newest-first. ``id`` is a stable tiebreaker because
        SQLite resolves ``created_at`` to seconds and bulk inserts collide."""
        return (
            self.db.query(NotificationSubscription)
            .filter(NotificationSubscription.user_id == user_id)
            .order_by(
                desc(NotificationSubscription.created_at),
                desc(NotificationSubscription.id),
            )
            .all()
        )

    def list_enabled_for_event(self, event_type: str) -> list[NotificationSubscription]:
        """Subs the dispatcher fans out to for a given event_type.

        INTENTIONALLY UNSCOPED — the dispatcher must fan out to ALL users'
        active subscriptions when processing a cron event.  Do NOT add a
        user_id filter here.
        """
        return (
            self.db.query(NotificationSubscription)
            .filter(
                NotificationSubscription.enabled.is_(True),
                NotificationSubscription.event_type == event_type,
            )
            .order_by(NotificationSubscription.id.asc())
            .all()
        )

    def update(
        self, sub_id: int, *, user_id: int, **fields
    ) -> Optional[NotificationSubscription]:
        """Partial update, scoped to ``user_id``. Unknown keys ignored.
        Returns None if not found or cross-tenant."""
        row = self.get(sub_id, user_id=user_id)
        if not row:
            return None
        allowed = {"enabled", "target", "label", "auth_header", "event_type", "channel"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, sub_id: int, *, user_id: int) -> bool:
        """Delete scoped to ``user_id``. Returns False when not found or
        cross-tenant."""
        row = self.get(sub_id, user_id=user_id)
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True


class DeliveryRepository:
    """Append-only audit log of dispatch attempts."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        subscription_id: int,
        run_id: str | None,
        status: str,
        http_code: int | None = None,
        error_text: str | None = None,
        latency_ms: int | None = None,
    ) -> NotificationDelivery:
        # Cap error_text so a giant traceback can't bloat the DB.
        if error_text and len(error_text) > 4000:
            error_text = error_text[:4000] + "…"
        row = NotificationDelivery(
            subscription_id=subscription_id,
            run_id=run_id,
            status=status,
            http_code=http_code,
            error_text=error_text,
            latency_ms=latency_ms,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_recent(
        self, subscription_id: int, *, limit: int = 20,
    ) -> list[NotificationDelivery]:
        return (
            self.db.query(NotificationDelivery)
            .filter(NotificationDelivery.subscription_id == subscription_id)
            .order_by(
                desc(NotificationDelivery.attempted_at),
                desc(NotificationDelivery.id),
            )
            .limit(limit)
            .all()
        )
