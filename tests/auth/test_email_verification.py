"""Email-verification tests (deploy P2-B1).

Password registrations land ``is_verified=False`` and receive a Resend email
carrying a tokened verify link; hitting ``GET /auth/verify?token=...`` flips the
flag. A ``REQUIRE_EMAIL_VERIFICATION`` env gate (DEFAULT OFF) blocks unverified
non-superusers from protected routes when enabled — and is inert otherwise so
the existing suite stays green. OAuth users arrive verified from the provider.

The EmailHandler is monkeypatched everywhere so no real mail is sent; we assert
it was called with a link containing the verify token.
"""

from __future__ import annotations

import app.backend.routes.auth as auth_routes
from app.backend.auth.security import create_verify_token
from app.backend.database import get_db
from app.backend.database.models import User
from tests.auth.conftest import auth_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SpyEmail:
    """Stand-in for EmailHandler that records the kwargs of the last send()."""

    last_kwargs: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    def send(self, *args, **kwargs):  # noqa: D401 - test double
        type(self).last_kwargs = kwargs
        return {"status": "ok", "http_code": 200, "message_id": "x", "error_text": None, "latency_ms": 1}


def _patch_email(monkeypatch):
    _SpyEmail.last_kwargs = None
    monkeypatch.setattr(auth_routes, "EmailHandler", _SpyEmail)
    return _SpyEmail


def _user_by_email(client, email: str) -> User:
    """Open a session against the app's test engine and load the user row."""
    override_fn = client.app.dependency_overrides[get_db]
    gen = override_fn()
    db = next(gen)
    try:
        return db.query(User).filter(User.email == email).first()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# ---------------------------------------------------------------------------
# Register → unverified + email
# ---------------------------------------------------------------------------


def test_password_register_unverified_and_emails(client, monkeypatch):
    spy = _patch_email(monkeypatch)
    r = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    assert r.status_code == 201, r.text

    user = _user_by_email(client, "a@x.com")
    assert user is not None and user.is_verified is False

    # Email was sent with a tokened verify link.
    assert spy.last_kwargs is not None, "EmailHandler.send was not called"
    kw = spy.last_kwargs
    assert kw.get("to") == "a@x.com"
    body = (kw.get("html") or "") + (kw.get("text") or "")
    assert "/auth/verify?token=" in body


def test_verify_token_marks_verified(client, monkeypatch):
    _patch_email(monkeypatch)
    r = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    assert r.status_code == 201
    user = _user_by_email(client, "a@x.com")
    assert user.is_verified is False

    token = create_verify_token(user.id)
    vr = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert vr.status_code == 200, vr.text

    refreshed = _user_by_email(client, "a@x.com")
    assert refreshed.is_verified is True


def test_invalid_verify_token_400(client, monkeypatch):
    _patch_email(monkeypatch)
    r = client.get("/auth/verify?token=not-a-real-token", follow_redirects=False)
    assert r.status_code == 400


def test_access_token_rejected_as_verify_token(client, monkeypatch):
    """A plain access token must NOT be accepted by /auth/verify (type guard)."""
    _patch_email(monkeypatch)
    reg = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    access = reg.json()["access_token"]
    r = client.get(f"/auth/verify?token={access}", follow_redirects=False)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_gate_blocks_unverified_when_required(full_client, monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    _patch_email(monkeypatch)
    reg = full_client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    assert reg.status_code == 201
    token = reg.json()["access_token"]

    # /auth/me stays reachable so the user can see their unverified state.
    me = full_client.get("/auth/me", headers=auth_header(token))
    assert me.status_code == 200 and me.json()["is_verified"] is False

    # A gated route (api-keys list) is blocked with 403 until verified.
    blocked = full_client.get("/api-keys/", headers=auth_header(token))
    assert blocked.status_code == 403, blocked.text


def test_gate_allows_after_verify_when_required(full_client, monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    _patch_email(monkeypatch)
    reg = full_client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    token = reg.json()["access_token"]
    user = _user_by_email(full_client, "a@x.com")

    full_client.get(f"/auth/verify?token={create_verify_token(user.id)}", follow_redirects=False)

    ok = full_client.get("/api-keys/", headers=auth_header(token))
    assert ok.status_code == 200, ok.text


def test_gate_off_by_default_allows(full_client, monkeypatch):
    # Flag unset → unverified user reaches gated routes (existing behavior).
    monkeypatch.delenv("REQUIRE_EMAIL_VERIFICATION", raising=False)
    _patch_email(monkeypatch)
    reg = full_client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    token = reg.json()["access_token"]

    ok = full_client.get("/api-keys/", headers=auth_header(token))
    assert ok.status_code == 200, ok.text


def test_gate_exempts_superuser(full_client, monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    _patch_email(monkeypatch)
    reg = full_client.post("/auth/register", json={"email": "admin@x.com", "password": "pw123456"})
    token = reg.json()["access_token"]

    # Promote to superuser directly in the shared in-memory DB.
    db = full_client.session_local()
    try:
        u = db.query(User).filter(User.email == "admin@x.com").first()
        u.is_superuser = True
        db.commit()
    finally:
        db.close()

    ok = full_client.get("/api-keys/", headers=auth_header(token))
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------------------
# OAuth auto-verify
# ---------------------------------------------------------------------------


def test_oauth_user_auto_verified(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    client.get("/auth/oauth/google", follow_redirects=False)
    state = client.cookies.get("oauth_state")
    monkeypatch.setattr(
        auth_routes,
        "exchange_code",
        lambda provider, code, redirect_uri: {
            "provider_account_id": "g1",
            "email": "oauth@x.com",
            "full_name": "O",
            "email_verified": True,
        },
    )
    r = client.get(f"/auth/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 302

    user = _user_by_email(client, "oauth@x.com")
    assert user is not None and user.is_verified is True
