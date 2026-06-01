"""Wave A4 — POST /research/analyze must use the LOGGED-IN user's stored
API keys and fail fast (400) when a NORMAL user lacks the configured
provider's key, so the host's keys are never spent on a user's behalf.

Harness mirrors tests/test_analyze_routes.py: in-memory SQLite shared via
StaticPool, with get_db + get_current_user overridden. Here we additionally
seed real User / ApiKey rows so the REAL ApiKeyService runs end-to-end.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.auth.dependencies import get_current_user
from app.backend.database.connection import Base, get_db
from app.backend.database.models import ApiKey, User
from app.backend.main import app
from src.research.models import (
    AnalyzeReport,
    AnalyzeRequest,
    BacktestVerdict,
    SECTION_ORDER,
    SectionPayload,
)

# The configured provider for research is DeepSeek by default
# (RESEARCH_MODEL_PROVIDER), whose key name is DEEPSEEK_API_KEY. The
# per-user keys are stored keyed by that exact *_API_KEY name.
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


def _fake_report(ticker="NVDA"):
    req = AnalyzeRequest(
        ticker=ticker, objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=False,
    )
    sections = {
        n: SectionPayload(
            name=n, markdown=f"## {n}\n\nbody", structured=None,
            skipped=False, persona_used=None,
        )
        for n in SECTION_ORDER
    }
    return AnalyzeReport(
        request=req, sections=sections, persona_assignments=None,
        backtest=BacktestVerdict(
            signal="rsi_oversold", window_start="2020-01-01",
            window_end="2026-05-22", n_signals=10, win_rate_20d=0.6,
            avg_return_20d=0.02, t_stat=2.1, significant=True,
            verdict="significant",
        ),
        rendered_html=None,
    )


@patch("app.backend.routes.research.render_sop")
@patch("app.backend.routes.research.run_sop")
def test_analyze_uses_user_keys(mock_run, mock_render, harness):
    """A user with a stored DEEPSEEK key → run_sop receives that user's
    api_keys dict (containing DEEPSEEK_API_KEY)."""
    client, Session = harness
    _seed_user(Session, user_id=1, is_superuser=False)
    _seed_key(Session, user_id=1, provider=DEEPSEEK_KEY, value="sk-user-deepseek")

    mock_run.return_value = _fake_report("NVDA")
    mock_render.return_value = "<html>x</html>"

    resp = client.post("/research/analyze", json={"ticker": "NVDA"})
    assert resp.status_code == 200, resp.text

    assert mock_run.called
    # api_keys passed as a keyword arg
    keys = mock_run.call_args.kwargs.get("api_keys")
    assert keys is not None, "run_sop must be called with api_keys=..."
    assert keys.get(DEEPSEEK_KEY) == "sk-user-deepseek"


@patch("app.backend.routes.research.render_sop")
@patch("app.backend.routes.research.run_sop")
def test_analyze_without_key_returns_400(mock_run, mock_render, harness):
    """A NORMAL user with NO key for the configured provider → 400 with the
    friendly 'Add your ... API key' message, and run_sop is NOT called (no
    host-key spend)."""
    client, Session = harness
    _seed_user(Session, user_id=1, is_superuser=False)
    # No key seeded.

    resp = client.post("/research/analyze", json={"ticker": "NVDA"})
    assert resp.status_code == 400, resp.text
    assert "Add your" in resp.json()["detail"]
    assert DEEPSEEK_KEY in resp.json()["detail"]
    assert not mock_run.called, "run_sop must NOT run when the user lacks the key"
