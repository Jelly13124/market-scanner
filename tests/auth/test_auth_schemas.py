import pytest
from pydantic import ValidationError
from app.backend.models.auth_schemas import RegisterRequest, LoginRequest, TokenResponse, UserOut

def test_register_valid():
    r = RegisterRequest(email="a@x.com", password="pw123456", full_name="A")
    assert r.email == "a@x.com"

def test_register_bad_email():
    with pytest.raises(ValidationError):
        RegisterRequest(email="notanemail", password="pw")

def test_token_default_type():
    assert TokenResponse(access_token="t").token_type == "bearer"

def test_userout_from_attributes():
    class FakeUser:
        id = 5; email = "a@x.com"; full_name = "A"; is_superuser = False; timezone = "Asia/Shanghai"
    out = UserOut.model_validate(FakeUser())
    assert out.id == 5 and out.is_superuser is False
    assert out.timezone == "Asia/Shanghai"
