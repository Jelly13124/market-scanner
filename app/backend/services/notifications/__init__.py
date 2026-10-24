"""Notification subsystem — dispatcher + per-channel handlers + renderer.

Public surface re-exported here for ergonomic imports:

    from app.backend.services.notifications import (
        NotificationDispatcher, EmailHandler, WebhookHandler,
        render_pipeline_html, render_pipeline_text,
    )

Each handler exposes a single ``send(subscription, run) -> dict`` method
returning a delivery-result dict with keys: ``status``, ``http_code``,
``error_text``, ``latency_ms``, plus channel-specific extras (e.g.
``message_id`` for Resend).
"""

from app.backend.services.notifications.email_handler import EmailHandler
from app.backend.services.notifications.render import (
    render_pipeline_html,
    render_pipeline_text,
)

# Optional re-exports — these modules land in later phases. Guarded so
# Phase 2 tests can import this package without Phase 3/4 modules.
try:
    from app.backend.services.notifications.webhook_handler import WebhookHandler  # noqa: F401
except ImportError:
    WebhookHandler = None  # type: ignore[assignment]

try:
    from app.backend.services.notifications.dispatcher import NotificationDispatcher  # noqa: F401
except ImportError:
    NotificationDispatcher = None  # type: ignore[assignment]

__all__ = [
    "EmailHandler",
    "render_pipeline_html",
    "render_pipeline_text",
    "WebhookHandler",
    "NotificationDispatcher",
]
