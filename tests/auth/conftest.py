import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import get_db
from app.backend.database.models import Base
from app.backend.routes.auth import router as auth_router


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(auth_router)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


@pytest.fixture
def full_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    from app.backend.routes import api_router
    app = FastAPI()
    app.include_router(api_router)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _register(client, email):
    r = client.post("/auth/register", json={"email": email, "password": "pw123456"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.fixture
def two_users(full_client):
    """Returns (token_a, token_b) for two distinct registered users."""
    return _register(full_client, "a@x.com"), _register(full_client, "b@x.com")


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}
