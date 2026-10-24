"""Pydantic request/response schemas for notification subscriptions.

Pattern mirrors ``app/backend/models/pipeline_schemas.py``. The frontend
uses these as the source of truth for TypeScript types.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"


class DeliveryStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------


class SubscriptionCreateRequest(BaseModel):
    """Body for POST /notifications/subscriptions."""

    channel: NotificationChannel
    target: str = Field(min_length=1, max_length=500,
                        description="Email address (channel='email') or HTTPS URL (channel='webhook')")
    label: str | None = Field(None, max_length=200, description="Human-readable name shown in UI")
    enabled: bool = True
    event_type: str = Field("pipeline.completed", max_length=50)
    auth_header: str | None = Field(None, max_length=500,
                                    description="Webhook only — full header value e.g. 'Bearer xxx'")

    @field_validator("target")
    @classmethod
    def _target_shape(cls, v: str, info) -> str:
        # We can't access other fields reliably in v1 of pydantic field_validator
        # without info.data — keep validation loose here; channel-specific
        # checks happen in the route handler where we already have the parsed
        # model. Just guard against trivially-empty after-strip.
        v = v.strip()
        if not v:
            raise ValueError("target cannot be empty/whitespace")
        return v


class SubscriptionPatchRequest(BaseModel):
    """Body for PATCH /notifications/subscriptions/{id} — all fields optional."""

    enabled: bool | None = None
    target: str | None = Field(None, min_length=1, max_length=500)
    label: str | None = Field(None, max_length=200)
    auth_header: str | None = Field(None, max_length=500)


class SubscriptionResponse(BaseModel):
    """Returned by GET/POST/PATCH /notifications/subscriptions[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    enabled: bool
    event_type: str
    channel: NotificationChannel
    target: str
    label: str | None = None
    # auth_header intentionally excluded from responses — it's a secret.
    # The frontend's "edit" flow re-sends it only when the user changes it.
    has_auth_header: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> "SubscriptionResponse":
        return cls(
            id=row.id,
            enabled=row.enabled,
            event_type=row.event_type,
            channel=row.channel,
            target=row.target,
            label=row.label,
            has_auth_header=bool(row.auth_header),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


# ---------------------------------------------------------------------------
# Deliveries (read-only audit log)
# ---------------------------------------------------------------------------


class DeliveryResponse(BaseModel):
    """Returned by GET /notifications/subscriptions/{id}/deliveries
    and inline as the result of POST .../test."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    subscription_id: int
    run_id: str | None = None
    status: DeliveryStatus
    http_code: int | None = None
    error_text: str | None = None
    latency_ms: int | None = None
    attempted_at: datetime
