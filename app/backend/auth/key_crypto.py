"""Fernet-at-rest encryption for user-supplied API keys (per-user-keys C1).

For a public deploy we store OTHER PEOPLE's LLM provider keys. They must not
sit in the DB as plaintext. This module is the single crypto choke: the
repository encrypts on write and decrypts on read, so everything above it
(service, ``get_model``) keeps seeing real plaintext keys.

Key material: ``APP_ENCRYPTION_KEY`` — a base64 32-byte Fernet key, generated
once with ``Fernet.generate_key()`` and stored in ``.env`` (gitignored).

Graceful dev fallback: when ``APP_ENCRYPTION_KEY`` is unset (local dev, tests
without the var) we store/return plaintext and log a warning instead of
crashing. ``decrypt_key`` is also tolerant of legacy plaintext rows written
before encryption was introduced — they decrypt to themselves and get
re-encrypted on the next write, so the rollout is seamless.
"""

import logging
import os

logger = logging.getLogger(__name__)


def _fernet():
    """Return a ``Fernet`` from ``APP_ENCRYPTION_KEY``, or ``None`` in dev (unset)."""
    key = os.getenv("APP_ENCRYPTION_KEY")
    if not key:
        return None  # dev: no encryption
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_key(plaintext: str) -> str:
    """Encrypt a plaintext API key for storage. Passthrough when no key configured."""
    f = _fernet()
    if f is None:
        logger.warning("APP_ENCRYPTION_KEY unset — storing API key UNENCRYPTED (dev only).")
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_key(stored: str) -> str:
    """Decrypt a stored API key. Passthrough when no key configured; tolerant of legacy plaintext."""
    f = _fernet()
    if f is None:
        return stored
    from cryptography.fernet import InvalidToken

    try:
        return f.decrypt(stored.encode()).decode()
    except (InvalidToken, ValueError):
        # Legacy plaintext row (written before encryption) — return as-is so the
        # rollout is seamless; it'll be re-encrypted on the next write.
        return stored


def mask_key(plaintext: str) -> str:
    """Mask a key for API responses: '••••' + last 4 chars (keys are write-only)."""
    if not plaintext:
        return ""
    return "••••" + plaintext[-4:] if len(plaintext) >= 4 else "••••"
