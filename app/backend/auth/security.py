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
VERIFY_TTL = timedelta(hours=24)


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


def create_verify_token(user_id: int) -> str:
    """Short-lived (24h) email-verification token; type="verify"."""
    return _make(user_id, VERIFY_TTL, "verify")


def decode_token(token: str) -> dict:
    return jwt.decode(token, _SECRET, algorithms=[_ALG])


def decode_verify_token(token: str) -> int:
    """Validate an email-verify token (type + exp) and return the user id.

    Raises on invalid signature, expiry, or wrong token type.
    """
    claims = jwt.decode(token, _SECRET, algorithms=[_ALG])
    if claims.get("type") != "verify":
        raise ValueError("wrong token type")
    return int(claims["sub"])


def create_recipient_verify_token(recipient_id: int) -> str:
    """Short-lived (24h) token to verify a bound report-recipient email.

    Encodes the ReportRecipient row id with a distinct type so it can't be
    confused with the account email-verification token."""
    return _make(recipient_id, VERIFY_TTL, "recipient_verify")


def decode_recipient_verify_token(token: str) -> int:
    """Validate a recipient-verify token (type + exp) and return the recipient id."""
    claims = jwt.decode(token, _SECRET, algorithms=[_ALG])
    if claims.get("type") != "recipient_verify":
        raise ValueError("wrong token type")
    return int(claims["sub"])
