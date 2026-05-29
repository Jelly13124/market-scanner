import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.auth.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.backend.database import get_db
from app.backend.models.auth_schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.backend.repositories.user_repository import UserRepository

router = APIRouter(prefix="/auth")

_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


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
