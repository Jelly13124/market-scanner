"""Tenant-isolation tests for /api-keys (Wave 5 — per-user API keys).

User A stores a provider key; user B never sees it (list, GET, delete all
isolated). The ``ApiKeyService`` resolves only the acting user's keys, and
the key-resolution policy surfaces a friendly error for a non-superuser
with no stored key while letting the seed superuser fall back to ``.env``.
"""

from __future__ import annotations

import pytest

from app.backend.database import get_db
from app.backend.database.models import User
from app.backend.services.api_key_service import ApiKeyError, ApiKeyService
from tests.auth.conftest import auth_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(client, token: str) -> int:
    """Resolve a token's user id via /auth/me (avoids hardcoding ids)."""
    r = client.get("/auth/me", headers=auth_header(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _db(client):
    """Open a session against the app's test engine (caller must close)."""
    override_fn = client.app.dependency_overrides.get(get_db)
    gen = override_fn()
    return gen, next(gen)


def _close(gen):
    try:
        next(gen)
    except StopIteration:
        pass


def _store_key(client, token, provider="OPENAI_API_KEY", value="sk-aaa"):
    return client.post(
        "/api-keys/",
        json={"provider": provider, "key_value": value, "is_active": True},
        headers=auth_header(token),
    )


# ---------------------------------------------------------------------------
# Route-level isolation
# ---------------------------------------------------------------------------


class TestApiKeyRouteIsolation:
    def test_requires_auth(self, full_client):
        """No token → 401 (not a 500, not someone's keys)."""
        assert full_client.get("/api-keys/").status_code == 401

    def test_a_key_invisible_to_b_in_list(self, full_client, two_users):
        tok_a, tok_b = two_users
        assert _store_key(full_client, tok_a).status_code == 200

        # A sees their key
        ra = full_client.get("/api-keys/", headers=auth_header(tok_a))
        assert ra.status_code == 200
        assert [k["provider"] for k in ra.json()] == ["OPENAI_API_KEY"]

        # B sees nothing
        rb = full_client.get("/api-keys/", headers=auth_header(tok_b))
        assert rb.status_code == 200
        assert rb.json() == []

    def test_b_cannot_get_a_key(self, full_client, two_users):
        tok_a, tok_b = two_users
        _store_key(full_client, tok_a)
        r = full_client.get("/api-keys/OPENAI_API_KEY", headers=auth_header(tok_b))
        assert r.status_code == 404

    def test_b_cannot_delete_a_key(self, full_client, two_users):
        tok_a, tok_b = two_users
        _store_key(full_client, tok_a)

        # Cross-tenant delete → 404
        r = full_client.delete("/api-keys/OPENAI_API_KEY", headers=auth_header(tok_b))
        assert r.status_code == 404

        # A's key still present
        r2 = full_client.get("/api-keys/OPENAI_API_KEY", headers=auth_header(tok_a))
        assert r2.status_code == 200
        assert r2.json()["key_value"] == "sk-aaa"

    def test_a_can_delete_own_key(self, full_client, two_users):
        tok_a, _ = two_users
        _store_key(full_client, tok_a)
        r = full_client.delete("/api-keys/OPENAI_API_KEY", headers=auth_header(tok_a))
        assert r.status_code == 200
        r2 = full_client.get("/api-keys/OPENAI_API_KEY", headers=auth_header(tok_a))
        assert r2.status_code == 404

    def test_same_provider_distinct_per_user(self, full_client, two_users):
        """A and B may both store OPENAI_API_KEY; each resolves to their own."""
        tok_a, tok_b = two_users
        _store_key(full_client, tok_a, value="sk-aaa")
        _store_key(full_client, tok_b, value="sk-bbb")

        ra = full_client.get("/api-keys/OPENAI_API_KEY", headers=auth_header(tok_a))
        rb = full_client.get("/api-keys/OPENAI_API_KEY", headers=auth_header(tok_b))
        assert ra.json()["key_value"] == "sk-aaa"
        assert rb.json()["key_value"] == "sk-bbb"


# ---------------------------------------------------------------------------
# Service-level resolution + policy
# ---------------------------------------------------------------------------


class TestApiKeyServiceResolution:
    def test_service_returns_only_acting_user_keys(self, full_client, two_users):
        tok_a, tok_b = two_users
        _store_key(full_client, tok_a, value="sk-aaa")
        uid_a, uid_b = _uid(full_client, tok_a), _uid(full_client, tok_b)

        gen, db = _db(full_client)
        try:
            assert ApiKeyService(db, user_id=uid_a).get_api_keys_dict() == {"OPENAI_API_KEY": "sk-aaa"}
            assert ApiKeyService(db, user_id=uid_b).get_api_keys_dict() == {}
            assert ApiKeyService(db, user_id=uid_a).get_api_key("OPENAI_API_KEY") == "sk-aaa"
            assert ApiKeyService(db, user_id=uid_b).get_api_key("OPENAI_API_KEY") is None
        finally:
            _close(gen)

    def test_non_superuser_missing_key_raises_friendly_error(self, full_client, two_users):
        """A regular user with no key gets a clear error — NOT the host's .env key."""
        tok_a, _ = two_users
        uid_a = _uid(full_client, tok_a)

        gen, db = _db(full_client)
        try:
            svc = ApiKeyService(db, user_id=uid_a)
            with pytest.raises(ApiKeyError) as exc:
                svc.require_api_key("OPENAI_API_KEY")
            assert "OPENAI_API_KEY" in str(exc.value)
            assert "Settings" in str(exc.value)
        finally:
            _close(gen)

    def test_superuser_falls_back_to_env(self, full_client, two_users, monkeypatch):
        """The seed superuser (host) may fall back to .env when they have no stored key."""
        tok_a, _ = two_users
        uid_a = _uid(full_client, tok_a)
        monkeypatch.setenv("OPENAI_API_KEY", "host-env-key")

        gen, db = _db(full_client)
        try:
            # Promote A to superuser.
            db.query(User).filter(User.id == uid_a).update({User.is_superuser: True})
            db.commit()

            svc = ApiKeyService(db, user_id=uid_a)
            assert svc.get_api_key("OPENAI_API_KEY") == "host-env-key"
            assert svc.require_api_key("OPENAI_API_KEY") == "host-env-key"
        finally:
            _close(gen)

    def test_stored_key_wins_over_env_for_superuser(self, full_client, two_users, monkeypatch):
        """Even for the superuser, their own stored key takes precedence over .env."""
        tok_a, _ = two_users
        _store_key(full_client, tok_a, value="sk-stored")
        uid_a = _uid(full_client, tok_a)
        monkeypatch.setenv("OPENAI_API_KEY", "host-env-key")

        gen, db = _db(full_client)
        try:
            db.query(User).filter(User.id == uid_a).update({User.is_superuser: True})
            db.commit()
            svc = ApiKeyService(db, user_id=uid_a)
            assert svc.get_api_key("OPENAI_API_KEY") == "sk-stored"
        finally:
            _close(gen)
