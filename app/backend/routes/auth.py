import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.auth.oauth import build_authorize_url, exchange_code, get_provider
from app.backend.auth.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.backend.database import get_db
from app.backend.models.auth_schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.backend.repositories.user_repository import UserRepository

router = APIRouter(prefix="/auth")

_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
_OAUTH_REDIRECT_BASE = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8001")
_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


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
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    repo = UserRepository(db)
    if repo.get_by_email(body.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = repo.create(email=body.email, hashed_password=hash_password(body.password), full_name=body.full_name)
    _set_refresh_cookie(response, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
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
def me(current_user=Depends(get_current_user)):
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
