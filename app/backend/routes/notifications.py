"""Notification subscription REST API.

Endpoints:

    GET    /notifications/subscriptions
    POST   /notifications/subscriptions
    GET    /notifications/subscriptions/{id}
    PATCH  /notifications/subscriptions/{id}
    DELETE /notifications/subscriptions/{id}
    POST   /notifications/subscriptions/{id}/test
    GET    /notifications/subscriptions/{id}/deliveries

The /test endpoint dispatches the most-recent PipelineRun (or a
synthetic sample if none exist) to a single subscription regardless of
its enabled flag — so users can validate config before flipping the
switch.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.backend.database import SessionLocal, get_db
from app.backend.models.notification_schemas import (
    DeliveryResponse,
    NotificationChannel,
    SubscriptionCreateRequest,
    SubscriptionPatchRequest,
    SubscriptionResponse,
)
from app.backend.repositories.notification_repository import (
    DeliveryRepository,
    SubscriptionRepository,
)
from app.backend.services.notifications.dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_target_for_channel(channel: str, target: str) -> None:
    """Channel-specific target shape checks. Raises HTTPException(400)."""
    if channel == "email":
        # Light email shape check — full validation belongs to the
        # email-sending provider. Just catch obvious typos here.
        if "@" not in target or " " in target or len(target) > 320:
            raise HTTPException(
                400, f"email target {target!r} doesn't look like a valid address",
            )
    elif channel == "webhook":
        try:
            parsed = urlparse(target)
        except Exception:
            raise HTTPException(400, f"webhook target {target!r} is not a URL")
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(
                400, f"webhook URL must be http or https; got scheme={parsed.scheme!r}",
            )
        if not parsed.hostname:
            raise HTTPException(400, f"webhook URL missing hostname: {target!r}")
    # Unknown channel rejected by the enum already.


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/subscriptions", response_model=list[SubscriptionResponse])
def list_subscriptions(db: Session = Depends(get_db)) -> list[SubscriptionResponse]:
    rows = SubscriptionRepository(db).list()
    return [SubscriptionResponse.from_row(r) for r in rows]


@router.post("/subscriptions", response_model=SubscriptionResponse, status_code=201)
def create_subscription(
    req: SubscriptionCreateRequest,
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    _validate_target_for_channel(req.channel.value, req.target)
    if req.channel == NotificationChannel.EMAIL and req.auth_header:
        # auth_header is meaningless for email; surface this so the UI's
        # input model doesn't silently store dead config.
        raise HTTPException(
            400, "auth_header only applies to webhook channel",
        )
    row = SubscriptionRepository(db).create(
        channel=req.channel.value,
        target=req.target,
        label=req.label,
        enabled=req.enabled,
        event_type=req.event_type,
        auth_header=req.auth_header,
    )
    return SubscriptionResponse.from_row(row)


@router.get("/subscriptions/{sub_id}", response_model=SubscriptionResponse)
def get_subscription(sub_id: int, db: Session = Depends(get_db)) -> SubscriptionResponse:
    row = SubscriptionRepository(db).get(sub_id)
    if not row:
        raise HTTPException(404, f"No subscription with id {sub_id}")
    return SubscriptionResponse.from_row(row)


@router.patch("/subscriptions/{sub_id}", response_model=SubscriptionResponse)
def update_subscription(
    sub_id: int,
    patch: SubscriptionPatchRequest,
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    existing = SubscriptionRepository(db).get(sub_id)
    if not existing:
        raise HTTPException(404, f"No subscription with id {sub_id}")
    # If target is being changed, re-validate against the (existing) channel.
    if patch.target is not None:
        _validate_target_for_channel(existing.channel, patch.target)
    fields = patch.model_dump(exclude_unset=True)
    updated = SubscriptionRepository(db).update(sub_id, **fields)
    return SubscriptionResponse.from_row(updated)


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int, db: Session = Depends(get_db)) -> Response:
    ok = SubscriptionRepository(db).delete(sub_id)
    if not ok:
        raise HTTPException(404, f"No subscription with id {sub_id}")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Test send + delivery history
# ---------------------------------------------------------------------------


@router.post("/subscriptions/{sub_id}/test", response_model=DeliveryResponse)
def test_subscription(sub_id: int) -> DeliveryResponse:
    """Fire a one-off send using the latest PipelineRun.

    Uses the same handler chain the cron uses, so seeing this succeed
    means the daily dispatch will succeed too. Works even when the
    subscription is currently disabled (so users can validate before
    flipping the switch).
    """
    # Use a fresh SessionLocal — the dispatcher itself opens further
    # sessions per write; we just need a sub existence check first.
    db = SessionLocal()
    try:
        if SubscriptionRepository(db).get(sub_id) is None:
            raise HTTPException(404, f"No subscription with id {sub_id}")
    finally:
        db.close()

    dispatcher = NotificationDispatcher(SessionLocal)
    result = dispatcher.dispatch_to(subscription_id=sub_id, run_id=None)
    if result is None:
        # Shouldn't happen since we just checked, but defend anyway.
        raise HTTPException(404, f"No subscription with id {sub_id}")

    # dispatcher.dispatch_to already recorded a delivery row — fetch the
    # newest for this sub and return it so the client sees the same
    # shape it would in /deliveries.
    db = SessionLocal()
    try:
        rows = DeliveryRepository(db).list_recent(sub_id, limit=1)
        if not rows:
            # Defensive: if the delivery record failed we still return
            # the in-memory result wrapped in the response shape.
            raise HTTPException(500, "test send completed but no delivery row recorded")
        return DeliveryResponse.model_validate(rows[0])
    finally:
        db.close()


@router.get(
    "/subscriptions/{sub_id}/deliveries",
    response_model=list[DeliveryResponse],
)
def list_deliveries(
    sub_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[DeliveryResponse]:
    if limit < 1 or limit > 200:
        raise HTTPException(400, "limit must be between 1 and 200")
    if SubscriptionRepository(db).get(sub_id) is None:
        raise HTTPException(404, f"No subscription with id {sub_id}")
    rows = DeliveryRepository(db).list_recent(sub_id, limit=limit)
    return [DeliveryResponse.model_validate(r) for r in rows]
