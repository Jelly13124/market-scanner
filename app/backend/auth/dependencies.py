from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.backend.auth.security import decode_token
from app.backend.database import get_db
from app.backend.repositories.user_repository import UserRepository


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
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
