import logging
import os
import secrets
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user, get_current_user_allow_unverified
from app.backend.auth.oauth import build_authorize_url, exchange_code, get_provider
from app.backend.auth.security import create_access_token, create_refresh_token, create_verify_token, decode_token, decode_verify_token, hash_password, verify_password
from app.backend.database import get_db
from app.backend.models.auth_schemas import LoginRequest, RegisterRequest, TokenResponse, UpdateMeRequest, UserOut
from app.backend.rate_limit import auth_limit, rate_limited
from app.backend.repositories.user_repository import UserRepository
from app.backend.services.notifications.email_handler import EmailHandler
from app.backend.services.scheduler_service import SchedulerService, get_scheduler_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")

_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
_OAUTH_REDIRECT_BASE = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8001")
_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


def _send_verification_email(email: str, user_id: int) -> None:
    """Best-effort verification email. A mail failure must NOT 500 the
    registration — log it and let the user re-request later."""
    base = os.getenv("FRONTEND_BASE_URL", _FRONTEND_URL).rstrip("/")
    link = f"{base}/auth/verify?token={create_verify_token(user_id)}"
    html = f'<p>Welcome! Please verify your email to start using the app.</p><p><a href="{link}">Verify your email</a></p><p>Or paste this link into your browser:<br>{link}</p>'
    text = f"Welcome! Verify your email by visiting:\n{link}\n"
    try:
        EmailHandler().send(to=email, subject="Verify your email", html=html, text=text)
    except Exception:
        logger.exception("verification email send failed for %s", email)


def _set_refresh_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        key="refresh_token",
        value=create_refresh_token(user_id),
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,
        path="/auth",
        max_age=14 * 24 * 3600,
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
@rate_limited(auth_limit())
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    repo = UserRepository(db)
    if repo.get_by_email(body.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = repo.create(email=body.email, hashed_password=hash_password(body.password), full_name=body.full_name, is_verified=False)
    _send_verification_email(body.email, user.id)
    _set_refresh_cookie(response, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    """Consume an email-verify token and mark the user verified.

    Authenticates via the query-param token (NOT get_current_user), so it
    stays reachable while the verification gate is on. Invalid/expired → 400.
    """
    try:
        user_id = decode_verify_token(token)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    user = UserRepository(db).get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    if not user.is_verified:
        user.is_verified = True
        db.commit()
    return HTMLResponse("<h1>Email verified</h1><p>You can now use the app.</p>")


@router.post("/login", response_model=TokenResponse)
@rate_limited(auth_limit())
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    repo = UserRepository(db)
    user = repo.get_by_email(body.email)
    if user is None or user.hashed_password is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _set_refresh_cookie(response, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        claims = decode_token(token)
        if claims.get("type") != "refresh":
            raise ValueError("wrong token type")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = UserRepository(db).get_by_id(int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    # Rotate the refresh cookie so its TTL slides and a leaked token is superseded on the next refresh.
    _set_refresh_cookie(response, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("refresh_token", path="/auth")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(current_user=Depends(get_current_user_allow_unverified)):
    return UserOut.model_validate(current_user)


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UpdateMeRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler_service),
):
    """Update the current user's settings (currently: timezone).

    Validates the IANA name against the host tz database; unknown zones → 400.
    After persisting, re-register the user's crons so the new tz takes effect
    immediately (a scheduler hiccup must not fail the tz save).
    """
    if body.timezone not in available_timezones():
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {body.timezone}")
    current_user.timezone = body.timezone
    db.commit()
    db.refresh(current_user)
    try:
        scheduler.reregister_user_jobs(current_user.id)
    except Exception:
        logger.exception("update_me: failed to re-register crons for user %s", current_user.id)
    return UserOut.model_validate(current_user)


@router.get("/oauth/{provider}")
def oauth_authorize(provider: str):
    try:
        get_provider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    state = secrets.token_urlsafe(16)
    redirect_uri = f"{_OAUTH_REDIRECT_BASE}/auth/oauth/{provider}/callback"
    resp = RedirectResponse(build_authorize_url(provider, state, redirect_uri), status_code=302)
    resp.set_cookie(key="oauth_state", value=state, httponly=True, samesite="lax", secure=_COOKIE_SECURE, path="/auth", max_age=600)
    return resp


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, code: str, state: str, request: Request, db: Session = Depends(get_db)):
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="invalid state")
    redirect_uri = f"{_OAUTH_REDIRECT_BASE}/auth/oauth/{provider}/callback"
    identity = exchange_code(provider, code, redirect_uri)
    if not identity["email_verified"] or not identity["email"]:
        raise HTTPException(status_code=400, detail=f"email not verified by {provider}")
    user = UserRepository(db).find_or_create_oauth(provider=provider, provider_account_id=identity["provider_account_id"], email=identity["email"], full_name=identity["full_name"])
    access_token = create_access_token(user.id)
    resp = RedirectResponse(f"{_FRONTEND_URL}/#access_token={access_token}", status_code=302)
    resp.set_cookie(key="refresh_token", value=create_refresh_token(user.id), httponly=True, samesite="lax", secure=_COOKIE_SECURE, path="/auth", max_age=14 * 24 * 3600)
    resp.delete_cookie("oauth_state", path="/auth")
    return resp
