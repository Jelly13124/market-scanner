"""Deliver a rendered report to a user's verified recipient emails.

Shared by the on-demand "email this report" endpoint (Stage 2) and the scheduled
push job (Stage 3). Never raises on a per-recipient mail failure — it logs and
counts the address as failed so one bad address can't sink the batch.
"""
import logging

from sqlalchemy.orm import Session

from app.backend.database.models import ReportRecipient
from app.backend.services.notifications.email_handler import EmailHandler

logger = logging.getLogger(__name__)


def verified_recipients(db: Session, user_id: int) -> list[ReportRecipient]:
    """The user's report-recipient rows that have been email-verified."""
    return (
        db.query(ReportRecipient)
        .filter(ReportRecipient.user_id == user_id, ReportRecipient.is_verified.is_(True))
        .order_by(ReportRecipient.id)
        .all()
    )


def email_report_html(db: Session, user_id: int, *, ticker: str, html: str) -> dict:
    """Email a rendered report to every verified recipient of ``user_id``.

    Returns ``{"sent": [emails...], "failed": [emails...]}``. With no verified
    recipients both lists are empty — the caller decides whether that's an error
    (on-demand) or a quiet no-op (scheduled)."""
    recipients = verified_recipients(db, user_id)
    subject = f"Quant Lab report — {ticker}"
    text = f"Your Quant Lab report for {ticker}. Open the HTML version to read it."
    handler = EmailHandler()
    sent: list[str] = []
    failed: list[str] = []
    for r in recipients:
        try:
            res = handler.send(to=r.email, subject=subject, html=html or "", text=text)
            (sent if res.get("status") == "ok" else failed).append(r.email)
        except Exception:
            logger.exception("emailing report (%s) to %s failed", ticker, r.email)
            failed.append(r.email)
    return {"sent": sent, "failed": failed}
