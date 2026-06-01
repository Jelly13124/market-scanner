"""Repository for API key database operations.

Wave 5 (per-user API keys): every method is scoped by a required
``user_id`` keyword so one user's keys are never visible to — or mutable
by — another. The upsert's "find existing by provider" is scoped to the
same user, matching the composite unique ``(user_id, provider)``
(migration ``75ec58cc6c14``).
"""

from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from app.backend.auth.key_crypto import decrypt_key, encrypt_key
from app.backend.database.models import ApiKey


class ApiKeyRepository:
    """Repository for API key database operations (scoped per user)."""

    def __init__(self, db: Session):
        self.db = db

    def _decrypted(self, api_key: Optional[ApiKey]) -> Optional[ApiKey]:
        """Decrypt ``key_value`` in place, then DETACH so the plaintext is never
        flushed back to the DB. Callers above the repo (service, response schema)
        only read the object, so expunging is safe and keeps encryption the sole
        choke point. Tolerant of legacy plaintext rows (decrypt_key returns as-is)."""
        if api_key is None:
            return None
        api_key.key_value = decrypt_key(api_key.key_value)
        self.db.expunge(api_key)
        return api_key

    def create_or_update_api_key(
        self,
        provider: str,
        key_value: str,
        description: str = None,
        is_active: bool = True,
        *,
        user_id: int,
    ) -> ApiKey:
        """Create a new API key or update this user's existing one for the provider."""
        # Find existing key for THIS user + provider (matches composite unique).
        existing_key = self.db.query(ApiKey).filter(ApiKey.user_id == user_id, ApiKey.provider == provider).first()

        if existing_key:
            # Update existing key
            existing_key.key_value = encrypt_key(key_value)
            existing_key.description = description
            existing_key.is_active = is_active
            existing_key.updated_at = func.now()
            self.db.commit()
            self.db.refresh(existing_key)
            return self._decrypted(existing_key)
        else:
            # Create new key owned by this user
            api_key = ApiKey(
                provider=provider,
                key_value=encrypt_key(key_value),
                description=description,
                is_active=is_active,
                user_id=user_id,
            )
            self.db.add(api_key)
            self.db.commit()
            self.db.refresh(api_key)
            return self._decrypted(api_key)

    def get_api_key_by_provider(self, provider: str, *, user_id: int) -> Optional[ApiKey]:
        """Get this user's active API key by provider name (decrypted)."""
        api_key = (
            self.db.query(ApiKey)
            .filter(
                ApiKey.user_id == user_id,
                ApiKey.provider == provider,
                ApiKey.is_active == True,
            )
            .first()
        )
        return self._decrypted(api_key)

    def get_all_api_keys(self, include_inactive: bool = False, *, user_id: int) -> List[ApiKey]:
        """Get all of this user's API keys (decrypted)."""
        query = self.db.query(ApiKey).filter(ApiKey.user_id == user_id)
        if not include_inactive:
            query = query.filter(ApiKey.is_active == True)
        return [self._decrypted(k) for k in query.order_by(ApiKey.provider).all()]

    def update_api_key(
        self,
        provider: str,
        key_value: str = None,
        description: str = None,
        is_active: bool = None,
        *,
        user_id: int,
    ) -> Optional[ApiKey]:
        """Update this user's existing API key."""
        api_key = self.db.query(ApiKey).filter(ApiKey.user_id == user_id, ApiKey.provider == provider).first()
        if not api_key:
            return None

        if key_value is not None:
            api_key.key_value = encrypt_key(key_value)
        if description is not None:
            api_key.description = description
        if is_active is not None:
            api_key.is_active = is_active

        api_key.updated_at = func.now()
        self.db.commit()
        self.db.refresh(api_key)
        return self._decrypted(api_key)

    def delete_api_key(self, provider: str, *, user_id: int) -> bool:
        """Delete this user's API key by provider."""
        api_key = self.db.query(ApiKey).filter(ApiKey.user_id == user_id, ApiKey.provider == provider).first()
        if not api_key:
            return False

        self.db.delete(api_key)
        self.db.commit()
        return True

    def deactivate_api_key(self, provider: str, *, user_id: int) -> bool:
        """Deactivate this user's API key instead of deleting it."""
        api_key = self.db.query(ApiKey).filter(ApiKey.user_id == user_id, ApiKey.provider == provider).first()
        if not api_key:
            return False

        api_key.is_active = False
        api_key.updated_at = func.now()
        self.db.commit()
        return True

    def update_last_used(self, provider: str, *, user_id: int) -> bool:
        """Update the last_used timestamp for this user's API key."""
        api_key = (
            self.db.query(ApiKey)
            .filter(
                ApiKey.user_id == user_id,
                ApiKey.provider == provider,
                ApiKey.is_active == True,
            )
            .first()
        )
        if not api_key:
            return False

        api_key.last_used = func.now()
        self.db.commit()
        return True

    def bulk_create_or_update(self, api_keys_data: List[dict], *, user_id: int) -> List[ApiKey]:
        """Bulk create or update multiple API keys for this user."""
        results = []
        for data in api_keys_data:
            api_key = self.create_or_update_api_key(
                provider=data["provider"],
                key_value=data["key_value"],
                description=data.get("description"),
                is_active=data.get("is_active", True),
                user_id=user_id,
            )
            results.append(api_key)
        return results
