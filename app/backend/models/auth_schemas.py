from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)  # bcrypt truncates >72 bytes; min length blocks trivial passwords
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str | None = None
    is_superuser: bool = False
    is_verified: bool = False
    timezone: str = "America/New_York"


class UpdateMeRequest(BaseModel):
    timezone: str
