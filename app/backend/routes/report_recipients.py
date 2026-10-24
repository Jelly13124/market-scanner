"""Report-recipient emails: extra addresses a user binds to receive reports.

Each recipient must be verified (the user clicks a link emailed to that address)
before it is eligible to receive reports. Capped at 3 per user. Every route is
Bearer-auth'd and scoped to the caller's ``user_id`` — except ``GET /verify``,
which authenticates via the emailed query-param token so the link works without
a session.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.auth.security import (
    create_recipient_verify_token,
    decode_recipient_verify_token,
)
from app.backend.database import get_db
from app.backend.database.models import ReportRecipient, User
from app.backend.services.notifications.email_handler import EmailHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-recipients", tags=["report-recipients"])

_MAX_RECIPIENTS = 3
_FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", os.getenv("FRONTEND_URL", "http://localhost:5173"))


class RecipientCreate(BaseModel):
    email: EmailStr


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_verified: bool


def _send_recipient_verification(recipient: ReportRecipient) -> None:
    """Best-effort verification email. A mail failure must NOT 500 the request —
    log it and let the user re-request via the resend endpoint."""
    base = _FRONTEND_BASE_URL.rstrip("/")
    link = f"{base}/report-recipients/verify?token={create_recipient_verify_token(recipient.id)}"
    html = (
        "<p>You were added to receive Quant Lab reports at this address.</p>"
        f'<p><a href="{link}">Verify this email</a></p>'
        f"<p>Or paste this link into your browser:<br>{link}</p>"
    )
    text = f"Verify this email to receive Quant Lab reports:\n{link}\n"
    try:
        EmailHandler().send(to=recipient.email, subject="Verify your report email", html=html, text=text)
    except Exception:
        logger.exception("recipient verification email send failed for %s", recipient.email)


@router.get("/", response_model=list[RecipientOut])
def list_recipients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReportRecipient]:
    return (
        db.query(ReportRecipient)
        .filter(ReportRecipient.user_id == current_user.id)
        .order_by(ReportRecipient.id)
        .all()
    )


@router.post("/", response_model=RecipientOut, status_code=201)
def add_recipient(
    body: RecipientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportRecipient:
    email = str(body.email).strip().lower()
    if db.query(ReportRecipient).filter(
        ReportRecipient.user_id == current_user.id, ReportRecipient.email == email
    ).first():
        raise HTTPException(409, "That email is already bound")
    count = db.query(ReportRecipient).filter(ReportRecipient.user_id == current_user.id).count()
    if count >= _MAX_RECIPIENTS:
        raise HTTPException(400, f"At most {_MAX_RECIPIENTS} report emails per account")
    recipient = ReportRecipient(user_id=current_user.id, email=email, is_verified=False)
    db.add(recipient)
    db.commit()
    db.refresh(recipient)
    _send_recipient_verification(recipient)
    return recipient


@router.post("/{recipient_id}/resend", response_model=RecipientOut)
def resend_verification(
    recipient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportRecipient:
    recipient = db.query(ReportRecipient).filter(
        ReportRecipient.id == recipient_id, ReportRecipient.user_id == current_user.id
    ).first()
    if not recipient:
        raise HTTPException(404, "Recipient not found")
    if recipient.is_verified:
        raise HTTPException(400, "Already verified")
    _send_recipient_verification(recipient)
    return recipient


@router.delete("/{recipient_id}", status_code=204)
def delete_recipient(
    recipient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    recipient = db.query(ReportRecipient).filter(
        ReportRecipient.id == recipient_id, ReportRecipient.user_id == current_user.id
    ).first()
    if not recipient:
        raise HTTPException(404, "Recipient not found")
    db.delete(recipient)
    db.commit()


@router.get("/verify")
def verify_recipient(token: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """Consume a recipient-verify token and mark the recipient verified.

    Authenticates via the query-param token (NOT get_current_user) so the emailed
    link works without a session. Invalid/expired -> 400."""
    try:
        recipient_id = decode_recipient_verify_token(token)
    except Exception:
        raise HTTPException(400, "Invalid or expired verification link")
    recipient = db.query(ReportRecipient).filter(ReportRecipient.id == recipient_id).first()
    if recipient is None:
        raise HTTPException(400, "Invalid or expired verification link")
    if not recipient.is_verified:
        recipient.is_verified = True
        db.commit()
    return HTMLResponse("<h1>Email verified</h1><p>This address will now receive your reports.</p>")
