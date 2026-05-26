"""Repositories for notification subscriptions + delivery audit log.

Same shape as ``pipeline_repository.py``: sync, Session-injected, one
commit per write, no business logic. The dispatcher and routes call into
these.
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
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get(self, sub_id: int) -> Optional[NotificationSubscription]:
        return (
            self.db.query(NotificationSubscription)
            .filter(NotificationSubscription.id == sub_id)
            .first()
        )

    def list(self) -> list[NotificationSubscription]:
        """All subs, newest-first. ``id`` is a stable tiebreaker because
        SQLite resolves ``created_at`` to seconds and bulk inserts collide."""
        return (
            self.db.query(NotificationSubscription)
            .order_by(
                desc(NotificationSubscription.created_at),
                desc(NotificationSubscription.id),
            )
            .all()
        )

    def list_enabled_for_event(self, event_type: str) -> list[NotificationSubscription]:
        """Subs the dispatcher fans out to for a given event_type."""
        return (
            self.db.query(NotificationSubscription)
            .filter(
                NotificationSubscription.enabled.is_(True),
                NotificationSubscription.event_type == event_type,
            )
            .order_by(NotificationSubscription.id.asc())
            .all()
        )

    def update(self, sub_id: int, **fields) -> Optional[NotificationSubscription]:
        """Partial update. Unknown keys ignored. Returns None if not found."""
        row = self.get(sub_id)
        if not row:
            return None
        allowed = {"enabled", "target", "label", "auth_header", "event_type", "channel"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, sub_id: int) -> bool:
        row = self.get(sub_id)
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
