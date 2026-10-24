"""Wave B1 — POST /lab/strategies/{id}/chat must use the LOGGED-IN user's
stored API keys and fail fast (400) when a NORMAL user lacks the configured
provider's key, so the host's keys are never spent on a user's behalf.

Lab strategy chat burns LLM credits through the SAME ``call_research_llm``
chokepoint as the analyze path (via ``run_chat_turn``), so it gets the same
per-user-key gate as Wave A4's /research/analyze.

Harness mirrors tests/research/test_analyze_route_keys.py: in-memory SQLite
shared via StaticPool, with get_db + get_current_user overridden, plus real
User / ApiKey rows so the REAL ApiKeyService runs end-to-end.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.auth.dependencies import get_current_user
from app.backend.database.connection import Base, get_db
from app.backend.database.models import ApiKey, User
from app.backend.routes import api_router

# The configured provider for research/lab is DeepSeek by default
# (RESEARCH_MODEL_PROVIDER), whose key name is DEEPSEEK_API_KEY. Per-user keys
# are stored keyed by that exact *_API_KEY name.
DEEPSEEK_KEY = "DEEPSEEK_API_KEY"


@pytest.fixture
def harness():
    """Yield (TestClient, Session factory) sharing one in-memory DB.

    The Session factory lets a test seed User / ApiKey rows that the route's
    own ApiKeyService (via the overridden get_db) will then read back.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    # Normal (non-superuser) acting user — the one whose keys must be used and
    # who must be blocked when no key is stored.
    fake_user = User(id=1, email="user@test.com", is_active=True, is_superuser=False)

    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _seed_user(Session, *, user_id=1, is_superuser=False):
    s = Session()
    try:
        s.add(User(id=user_id, email=f"u{user_id}@test.com",
                   is_active=True, is_superuser=is_superuser))
        s.commit()
    finally:
        s.close()


def _seed_key(Session, *, user_id=1, provider=DEEPSEEK_KEY, value="sk-user-deepseek"):
    s = Session()
    try:
        s.add(ApiKey(provider=provider, key_value=value, is_active=True, user_id=user_id))
        s.commit()
    finally:
        s.close()


def _create_strategy(client) -> int:
    """Create a strategy via the route and return its id."""
    r = client.post("/lab/strategies", json={"name": "ChatKeys", "description": ""})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


@patch("app.backend.routes.lab.run_chat_turn")
def test_lab_chat_uses_user_keys(mock_chat, harness):
    """A user with a stored DEEPSEEK key → run_chat_turn receives that user's
    api_keys dict (containing DEEPSEEK_API_KEY)."""
    from src.lab.chat import ChatReply, ChatResponse

    client, Session = harness
    _seed_user(Session, user_id=1, is_superuser=False)
    _seed_key(Session, user_id=1, provider=DEEPSEEK_KEY, value="sk-user-deepseek")

    mock_chat.return_value = ChatResponse(root=ChatReply(message="OK"))

    sid = _create_strategy(client)
    resp = client.post(f"/lab/strategies/{sid}/chat", json={"message": "hi"})
    assert resp.status_code == 200, resp.text

    assert mock_chat.called
    keys = mock_chat.call_args.kwargs.get("api_keys")
    assert keys is not None, "run_chat_turn must be called with api_keys=..."
    assert keys.get(DEEPSEEK_KEY) == "sk-user-deepseek"


@patch("app.backend.routes.lab.run_chat_turn")
def test_lab_chat_without_key_returns_400(mock_chat, harness):
    """A NORMAL user with NO key for the configured provider → 400 with the
    friendly 'Add your ... API key' message, and run_chat_turn is NOT called
    (no host-key spend)."""
    client, Session = harness
    _seed_user(Session, user_id=1, is_superuser=False)
    # No key seeded.

    sid = _create_strategy(client)
    resp = client.post(f"/lab/strategies/{sid}/chat", json={"message": "hi"})
    assert resp.status_code == 400, resp.text
    assert "Add your" in resp.json()["detail"]
    assert DEEPSEEK_KEY in resp.json()["detail"]
    assert not mock_chat.called, "run_chat_turn must NOT run when the user lacks the key"
