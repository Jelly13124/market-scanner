import os

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.backend.auth.security import decode_token
from app.backend.database import get_db
from app.backend.repositories.user_repository import UserRepository


def _load_user(authorization: str | None, db: Session):
    """Decode the Bearer access token and load the active user, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        claims = decode_token(authorization.split(" ", 1)[1])
        if claims.get("type") != "access":
            raise ValueError("wrong token type")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = UserRepository(db).get_by_id(int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def get_current_user_allow_unverified(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Authenticate WITHOUT the email-verification gate.

    Used by ``/auth/me`` so an unverified user can still observe their own
    state (and re-request the verification email) while every other protected
    route stays gated via :func:`get_current_user`.
    """
    return _load_user(authorization, db)


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    user = _load_user(authorization, db)
    # Email-verification gate — DEFAULT OFF so the existing suite stays green;
    # prod sets REQUIRE_EMAIL_VERIFICATION=true. Superusers are exempt.
    if os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true" and not user.is_verified and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Please verify your email before using the app.")
    return user
