"""TDD tests for Fernet-at-rest encryption of user API keys (per-user-keys C1).

Two layers:

1. Unit tests of ``app.backend.auth.key_crypto`` — encrypt/decrypt roundtrip,
   legacy-plaintext tolerance (a row written before encryption decrypts to
   itself), no-key passthrough (dev without ``APP_ENCRYPTION_KEY``), and the
   masking helper used in API responses.
2. A storage-level test through the real repository + service against an
   in-memory SQLite DB: with ``APP_ENCRYPTION_KEY`` set, the RAW ``key_value``
   column holds ciphertext (≠ plaintext) while ``ApiKeyService.get_api_keys_dict``
   still yields usable plaintext (so ``get_model`` keeps working) and the
   ``ApiKeyResponse`` schema masks the key.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.auth.key_crypto import decrypt_key, encrypt_key, mask_key
from app.backend.database.models import ApiKey, Base, User
from app.backend.models.schemas import ApiKeyResponse
from app.backend.repositories.api_key_repository import ApiKeyRepository
from app.backend.services.api_key_service import ApiKeyService


# ---------------------------------------------------------------------------
# Unit: key_crypto
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    c = encrypt_key("sk-secret-123")
    assert c != "sk-secret-123"
    assert decrypt_key(c) == "sk-secret-123"


def test_decrypt_legacy_plaintext(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    # A row written before encryption isn't a valid Fernet token → return as-is.
    assert decrypt_key("sk-plain-legacy") == "sk-plain-legacy"


def test_no_key_passthrough(monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    assert encrypt_key("x") == "x"
    assert decrypt_key("x") == "x"


def test_mask():
    assert mask_key("sk-abcd1234") == "••••1234"


def test_mask_short_and_empty():
    assert mask_key("") == ""
    assert mask_key("abc") == "••••"


# ---------------------------------------------------------------------------
# Storage-level: repository + service + schema, in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    db = TestingSession()
    # A user to own the keys (user_id is NOT NULL, FK to users).
    db.add(User(email="owner@x.com", hashed_password="x"))
    db.commit()
    uid = db.query(User).first().id
    try:
        yield db, uid
    finally:
        db.close()


def test_db_value_is_ciphertext_but_service_sees_plaintext(db_session, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db, uid = db_session

    repo = ApiKeyRepository(db)
    repo.create_or_update_api_key(provider="OPENAI_API_KEY", key_value="sk-plaintext-xyz", user_id=uid)

    # 1. RAW column is ciphertext, not the plaintext we passed in.
    raw = db.query(ApiKey).filter(ApiKey.user_id == uid).first()
    assert raw.key_value != "sk-plaintext-xyz"
    # And it's a real Fernet token (decrypts back).
    assert decrypt_key(raw.key_value) == "sk-plaintext-xyz"

    # 2. The SERVICE (what get_model consumes) sees usable plaintext.
    svc = ApiKeyService(db, user_id=uid)
    assert svc.get_api_keys_dict() == {"OPENAI_API_KEY": "sk-plaintext-xyz"}
    assert svc.get_api_key("OPENAI_API_KEY") == "sk-plaintext-xyz"


def test_update_path_also_encrypts(db_session, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db, uid = db_session

    repo = ApiKeyRepository(db)
    repo.create_or_update_api_key(provider="OPENAI_API_KEY", key_value="sk-first", user_id=uid)
    # Upsert (existing row) path.
    repo.create_or_update_api_key(provider="OPENAI_API_KEY", key_value="sk-second", user_id=uid)
    # Explicit update path.
    repo.update_api_key(provider="OPENAI_API_KEY", key_value="sk-third", user_id=uid)

    raw = db.query(ApiKey).filter(ApiKey.user_id == uid).first()
    assert raw.key_value != "sk-third"
    assert decrypt_key(raw.key_value) == "sk-third"
    assert ApiKeyService(db, user_id=uid).get_api_key("OPENAI_API_KEY") == "sk-third"


def test_api_response_masks_key(db_session, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db, uid = db_session

    repo = ApiKeyRepository(db)
    repo.create_or_update_api_key(provider="OPENAI_API_KEY", key_value="sk-abcd1234", user_id=uid)

    # The repo read decrypts → plaintext on the ORM object → schema masks it.
    api_key = repo.get_api_key_by_provider("OPENAI_API_KEY", user_id=uid)
    resp = ApiKeyResponse.model_validate(api_key)
    assert resp.key_value == mask_key("sk-abcd1234")
    assert resp.key_value == "••••1234"
    # The raw secret never appears in the serialized response.
    assert "sk-abcd1234" not in resp.model_dump_json()


def test_legacy_plaintext_row_still_readable(db_session, monkeypatch):
    """A pre-encryption row (plaintext in DB) must still resolve for the service."""
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db, uid = db_session

    # Simulate a legacy row written before encryption existed: plaintext in DB,
    # bypassing the repository's encrypt-on-write.
    db.add(ApiKey(provider="OPENAI_API_KEY", key_value="sk-legacy-plain", is_active=True, user_id=uid))
    db.commit()

    svc = ApiKeyService(db, user_id=uid)
    assert svc.get_api_key("OPENAI_API_KEY") == "sk-legacy-plain"
