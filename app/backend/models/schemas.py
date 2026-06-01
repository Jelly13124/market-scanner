from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

from app.backend.auth.key_crypto import mask_key


class ErrorResponse(BaseModel):
    message: str
    error: str | None = None


# API Key schemas
class ApiKeyCreateRequest(BaseModel):
    """Request to create or update an API key"""

    provider: str = Field(..., min_length=1, max_length=100)
    key_value: str = Field(..., min_length=1)
    description: Optional[str] = None
    is_active: bool = True


class ApiKeyUpdateRequest(BaseModel):
    """Request to update an existing API key"""

    key_value: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ApiKeyResponse(BaseModel):
    """API key response. ``key_value`` is MASKED ('••••' + last 4) — the raw
    secret is never returned. Keys are write-only; the frontend only needs to
    know a key EXISTS and its masked tail. The repository decrypts on read, so
    the ORM object carries plaintext here; the validator masks it on the way out."""

    id: int
    provider: str
    key_value: str
    is_active: bool
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    last_used: Optional[datetime]

    @field_validator("key_value")
    @classmethod
    def _mask_key_value(cls, v: str) -> str:
        return mask_key(v)

    class Config:
        from_attributes = True


class ApiKeySummaryResponse(BaseModel):
    """API key response without the actual key value"""

    id: int
    provider: str
    is_active: bool
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    last_used: Optional[datetime]
    has_key: bool = True  # Indicates if a key is set

    class Config:
        from_attributes = True


class ApiKeyBulkUpdateRequest(BaseModel):
    """Request to update multiple API keys at once"""

    api_keys: List[ApiKeyCreateRequest]
