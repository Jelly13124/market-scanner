"""Resolve only the acting user's stored keys; no owner or host fallback."""

from typing import Dict, Optional

from sqlalchemy.orm import Session

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

    def get_api_keys_dict(self) -> Dict[str, str]:
        """Return the acting user's stored active keys as a provider->value dict.

        Stored keys only — no ``.env`` merge. This is the payload injected
        into a run when the keys are passed explicitly.
        """
        api_keys = self.repository.get_all_api_keys(include_inactive=False, user_id=self.user_id)
        return {key.provider: key.key_value for key in api_keys}

    def get_api_key(self, provider: str) -> Optional[str]:
        """Resolve only this user's stored active key."""
        api_key = self.repository.get_api_key_by_provider(provider, user_id=self.user_id)
        if api_key:
            return api_key.key_value
        # Host-key fallback is allowed ONLY for the seed superuser/owner.
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
