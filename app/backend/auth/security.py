import os
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _pwd.verify(raw, hashed)
    except Exception:
        return False


_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me")
_ALG = "HS256"
ACCESS_TTL = timedelta(minutes=30)
REFRESH_TTL = timedelta(days=14)


def _make(user_id: int, ttl: timedelta, kind: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "type": kind, "iat": now, "exp": now + ttl},
        _SECRET,
        algorithm=_ALG,
    )


def create_access_token(user_id: int) -> str:
    return _make(user_id, ACCESS_TTL, "access")


def create_refresh_token(user_id: int) -> str:
    return _make(user_id, REFRESH_TTL, "refresh")


def decode_token(token: str) -> dict:
    return jwt.decode(token, _SECRET, algorithms=[_ALG])
