import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.backend.database.models import Base
from app.backend.repositories.user_repository import UserRepository

@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng); s = sessionmaker(bind=eng)()
    yield s; s.close()

def test_create_and_get(db):
    repo = UserRepository(db)
    u = repo.create(email="a@x.com", hashed_password="h", full_name="A")
    assert repo.get_by_email("a@x.com").id == u.id
    assert repo.get_by_id(u.id).email == "a@x.com"

def test_email_unique(db):
    repo = UserRepository(db)
    repo.create(email="a@x.com", hashed_password="h")
    with pytest.raises(Exception):
        repo.create(email="a@x.com", hashed_password="h2")

def test_find_or_create_oauth_idempotent(db):
    repo = UserRepository(db)
    u1 = repo.find_or_create_oauth(provider="google", provider_account_id="g1", email="a@x.com", full_name="A")
    u2 = repo.find_or_create_oauth(provider="google", provider_account_id="g1", email="a@x.com", full_name="A")
    assert u1.id == u2.id

def test_find_or_create_oauth_links_existing_email(db):
    repo = UserRepository(db)
    existing = repo.create(email="a@x.com", hashed_password="h")
    linked = repo.find_or_create_oauth(provider="github", provider_account_id="gh1", email="a@x.com")
    assert linked.id == existing.id  # links to the existing password user
