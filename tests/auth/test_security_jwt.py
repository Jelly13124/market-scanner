import pytest
from app.backend.auth.security import create_access_token, create_refresh_token, decode_token


def test_roundtrip_access():
    claims = decode_token(create_access_token(user_id=7))
    assert claims["sub"] == "7" and claims["type"] == "access"


def test_refresh_type():
    assert decode_token(create_refresh_token(user_id=7))["type"] == "refresh"


def test_tampered_rejected():
    with pytest.raises(Exception):
        decode_token("not.a.jwt")
