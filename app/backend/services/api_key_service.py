"""Per-user API key resolution service.

Wave 5 (per-user API keys). Each ``ApiKeyService`` is bound to a single
acting ``user_id`` at construction; every lookup returns ONLY that user's
stored keys.

Key-resolution policy (the whole point of per-user keys):
  1. The acting user's own stored key for a provider always takes
     precedence.
  2. If the user has NO key for a required provider, we DO NOT silently
     fall back to the host's global ``.env`` key — that would make the
     host spend their own credits for a friend. Instead the caller gets a
     clear ``ApiKeyError`` ("Add your <provider> API key in Settings").
  3. EXCEPTION: the seed superuser/owner (``users.is_superuser = 1``) MAY
     fall back to ``.env`` so the host's own usage keeps working without
     re-entering keys they already have on the box. Resolution for the
     superuser therefore returns the env value when no stored key exists.

Note: ``get_api_keys_dict()`` returns only what is actually stored for the
user (no env merge); it is the explicit-injection payload. The env
fallback for the superuser lives in ``get_api_key()`` /
``require_api_key()`` so a missing single provider degrades to the host
key only for the owner.
"""

import os
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.backend.database.models import User
from app.backend.repositories.api_key_repository import ApiKeyRepository


class ApiKeyError(Exception):
    """Raised when a required provider key is missing for the acting user.

    Message is user-facing and safe to surface in an API error response.
    """


class ApiKeyService:
    """Loads API keys for a single acting user, applying the resolution policy."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.repository = ApiKeyRepository(db)

    def _is_seed_superuser(self) -> bool:
        """True when the acting user is a superuser (the host/owner)."""
        user = self.db.query(User).filter(User.id == self.user_id).first()
        return bool(user and user.is_superuser)

    def get_api_keys_dict(self) -> Dict[str, str]:
        """Return the acting user's stored active keys as a provider->value dict.

        Stored keys only — no ``.env`` merge. This is the payload injected
        into a run when the keys are passed explicitly.
        """
        api_keys = self.repository.get_all_api_keys(include_inactive=False, user_id=self.user_id)
        return {key.provider: key.key_value for key in api_keys}

    def get_api_key(self, provider: str) -> Optional[str]:
        """Resolve a single provider key for the acting user.

        Stored key wins; otherwise the seed superuser (and only them) falls
        back to the host ``.env`` value. A non-superuser with no stored key
        gets ``None`` (use :meth:`require_api_key` to turn that into a
        friendly error).
        """
        api_key = self.repository.get_api_key_by_provider(provider, user_id=self.user_id)
        if api_key:
            return api_key.key_value
        # Host-key fallback is allowed ONLY for the seed superuser/owner.
        if self._is_seed_superuser():
            return os.getenv(provider)
        return None

    def require_api_key(self, provider: str) -> str:
        """Like :meth:`get_api_key` but raise a friendly error when missing.

        Use on analyze/scan paths so a user without the needed key gets a
        clear "Add your <provider> API key in Settings" message instead of
        a crash or someone else's key being spent.
        """
        key = self.get_api_key(provider)
        if not key:
            raise ApiKeyError(f"Add your {provider} API key in Settings to run this.")
        return key
