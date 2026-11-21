"""Phase 6E: REST contract tests for /lab/* endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base, get_db
from app.backend.routes import api_router


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _auth_header(client):
    """Register a user and return an auth header dict."""
    r = client.post("/auth/register", json={"email": "test@x.com", "password": "pw123456"})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_deepseek_key(client, hdrs):
    """Seed the configured provider key (DEEPSEEK_API_KEY) for the acting user.

    Wave B1 gated /lab chat on the user having the research provider's key
    (mirrors /research/analyze). Chat tests that exercise the LLM flow must
    seed it, otherwise the route fails fast with 400 before run_chat_turn.
    """
    r = client.post("/api-keys/", json={
        "provider": "DEEPSEEK_API_KEY", "key_value": "sk-test-deepseek",
    }, headers=hdrs)
    assert r.status_code == 200, r.text


def _spec_dict():
    return {
        "name": "TestStrategy", "description": "",
        "universe": {"kind": "sp500"},
        "entry": {"combiner": "and", "signals": [
            {"type": "ma_cross", "fast": 50, "slow": 200, "direction": "golden"}
        ]},
        "exit": [{"type": "stop_loss", "mode": "pct", "value": 0.05}],
        "filters": [], "sizing": {"type": "fixed_pct", "pct": 0.05},
        "backtest_config": {},
    }


class TestStrategyRoutes:
    def test_create_get_list_delete(self, client):
        hdrs = _auth_header(client)
        r = client.post("/lab/strategies", json={"name": "A", "description": "x"}, headers=hdrs)
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        assert r.json()["spec_json"]["entry"]["signals"]  # initial scaffold present
        r2 = client.get(f"/lab/strategies/{sid}", headers=hdrs)
        assert r2.status_code == 200
        r3 = client.get("/lab/strategies", headers=hdrs)
        assert len(r3.json()) == 1
        client.delete(f"/lab/strategies/{sid}", headers=hdrs)
        assert client.get(f"/lab/strategies/{sid}", headers=hdrs).status_code == 404

    def test_create_with_initial_spec(self, client):
        hdrs = _auth_header(client)
        r = client.post("/lab/strategies", json={
            "name": "B", "description": "", "initial_spec_json": _spec_dict()
        }, headers=hdrs)
        assert r.status_code in (200, 201)
        assert r.json()["spec_json"]["entry"]["signals"][0]["type"] == "ma_cross"

    def test_duplicate_name_409(self, client):
        hdrs = _auth_header(client)
        client.post("/lab/strategies", json={"name": "Dup"}, headers=hdrs)
        r = client.post("/lab/strategies", json={"name": "Dup"}, headers=hdrs)
        assert r.status_code == 409

    def test_manual_edit_via_patch(self, client):
        hdrs = _auth_header(client)
        sid = client.post("/lab/strategies", json={"name": "ME"}, headers=hdrs).json()["id"]
        r = client.patch(f"/lab/strategies/{sid}", json={
            "spec_json": _spec_dict(), "description": "edited"
        }, headers=hdrs)
        assert r.status_code == 200
        assert r.json()["version"] == 2
        assert r.json()["description"] == "edited"

    def test_requires_auth(self, client):
        assert client.get("/lab/strategies").status_code == 401


class TestChatRoutes:
    def test_get_chat_empty(self, client):
        hdrs = _auth_header(client)
        sid = client.post("/lab/strategies", json={"name": "ChatA"}, headers=hdrs).json()["id"]
        r = client.get(f"/lab/strategies/{sid}/chat", headers=hdrs)
        assert r.status_code == 200
        assert r.json() == []

    @patch("app.backend.routes.lab.run_chat_turn")
    def test_post_chat_reply(self, mock_chat, client):
        from src.lab.chat import ChatReply, ChatResponse
        mock_chat.return_value = ChatResponse(root=ChatReply(message="OK"))
        hdrs = _auth_header(client)
        _seed_deepseek_key(client, hdrs)
        sid = client.post("/lab/strategies", json={"name": "ChatB"}, headers=hdrs).json()["id"]
        r = client.post(f"/lab/strategies/{sid}/chat", json={"message": "hi"}, headers=hdrs)
        assert r.status_code == 200
        assert r.json()["kind"] == "reply"
        assert r.json()["message"]["content"] == "OK"

    @patch("app.backend.routes.lab.run_chat_turn")
    def test_post_chat_patch_and_apply(self, mock_chat, client):
        from src.lab.chat import ChatResponse, ProposeSpecPatch
        new_spec = _spec_dict()
        new_spec["description"] = "AI-modified"
        mock_chat.return_value = ChatResponse(root=ProposeSpecPatch(
            rationale="changed it", patch=new_spec,
        ))
        hdrs = _auth_header(client)
        _seed_deepseek_key(client, hdrs)
        sid = client.post("/lab/strategies", json={"name": "ChatC"}, headers=hdrs).json()["id"]
        r = client.post(f"/lab/strategies/{sid}/chat", json={"message": "edit"}, headers=hdrs)
        assert r.json()["kind"] == "patch"
        msg_id = r.json()["message"]["id"]
        # Apply
        r2 = client.post(f"/lab/strategies/{sid}/chat/apply",
                         json={"message_id": msg_id}, headers=hdrs)
        assert r2.status_code == 200
        # Strategy spec should have been updated
        r3 = client.get(f"/lab/strategies/{sid}", headers=hdrs)
        assert r3.json()["spec_json"]["description"] == "AI-modified"
        assert r3.json()["version"] == 2


class TestBacktestRoutes:
    @patch("app.backend.routes.lab.run_backtest")
    def test_run_backtest_persists(self, mock_run, client):
        from src.lab.backtest_runner import BacktestRunResult
        from src.lab.engine.metrics import Metrics
        from src.lab.engine.verdict import Verdict
        mock_run.return_value = BacktestRunResult(
            spec_snapshot=_spec_dict(),
            start_date="2020-01-01", end_date="2024-12-31", midpoint_date="2023-09-08",
            universe_size=10,
            is_metrics=Metrics(0.5, 0.15, 1.2, 1.3, -0.1, 1.5, 0.55, 1.8, 15, 30, 0.7),
            oos_metrics=Metrics(0.3, 0.12, 0.9, 1.0, -0.15, 0.8, 0.52, 1.5, 14, 15, 0.6),
            benchmark_cagr=0.10,
            verdict=Verdict(label="weak", text="weak edge", degradation_ratio=0.8),
            equity_curve_is=[100000, 110000], equity_curve_oos=[110000, 115000],
            is_trades=[], oos_trades=[],
            duration_seconds=12.3,
        )
        hdrs = _auth_header(client)
        sid = client.post("/lab/strategies", json={"name": "BT"}, headers=hdrs).json()["id"]
        r = client.post(f"/lab/strategies/{sid}/backtest", json={}, headers=hdrs)
        assert r.status_code == 200, r.text
        assert r.json()["verdict_label"] == "weak"
        bt_id = r.json()["id"]
        assert client.get(f"/lab/backtests/{bt_id}", headers=hdrs).status_code == 200
        assert len(client.get(f"/lab/strategies/{sid}/backtests", headers=hdrs).json()) == 1


def test_catalog_endpoint(client):
    r = client.get("/lab/catalog")
    assert r.status_code == 200
    body = r.json()
    assert {"relative_strength", "relative_volume", "range_breakout"} <= body.keys()
    assert "rsi" in body and "ma_cross" in body


@pytest.mark.parametrize("group,spy_available,evaluated", [
    ("and", True, 5), ("or", False, 1), ("strength_only", False, 0),
])
def test_shared_rule_backtest_persists_trades_and_evidence_coverage(
    client, monkeypatch, group, spy_available, evaluated,
):
    from datetime import date, timedelta
    from types import SimpleNamespace

    from v2.data.models import Price

    spec = _spec_dict()
    spec.update(
        entry={"combiner": "and", "signals": [
            {"type": name, "window": 2}
            for name in ("relative_volume", "range_breakout", "relative_strength")
        ]},
        exit=[{"type": "time_stop", "bars": 1}],
        backtest_config={"start_date": "2024-03-04", "end_date": "2024-03-18",
                         "is_oos_split": 0.5, "benchmark": "none", "reverse_signal_as_exit": False},
    )
    if group == "strength_only":
        spec["entry"]["signals"] = [spec["entry"]["signals"][-1]]
    else:
        spec["entry"]["combiner"] = group

    def historical_prices(ticker, start_date, end_date):
        if ticker == "SPY" and not spy_available:
            return []
        day = max(date(2024, 2, 29), date.fromisoformat(start_date))
        rows = []
        while day <= date.fromisoformat(end_date):
            if day.weekday() < 5:
                hit = ticker == "NVDA" and day.day in (4, 11)
                rows.append(Price(time=f"{day}T20:00:00Z", open=100, high=100, low=100, close=100,
                                  adjusted_close=115 if hit else 100, volume=200 if hit else 100))
            day += timedelta(days=1)
        return rows

    monkeypatch.setattr("src.lab.backtest_runner.load_universe_tickers", lambda *a, **kw: ["NVDA"])
    monkeypatch.setattr("v2.data.factory.make_data_client", lambda: SimpleNamespace(get_prices=historical_prices))
    headers = _auth_header(client)
    created = client.post("/lab/strategies", json={"name": "Daily rules", "initial_spec_json": spec},
                          headers=headers)
    assert created.status_code == 201, created.text
    response = client.post(f"/lab/strategies/{created.json()['id']}/backtest", json={}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["error_message"] is None
    assert result["universe_size"] == 1
    trades = [(t["ticker"], t["entry_date"][:10]) for t in result["trades_json"]]
    assert trades == ([("NVDA", "2024-03-05"), ("NVDA", "2024-03-12")] if evaluated else [])
    stored = client.get(f"/lab/backtests/{result['id']}", headers=headers).json()
    verdict = stored["verdict_text"]
    for segment in ("IS", "OOS"):
        assert f"{segment} had {evaluated} evaluated and {5 - evaluated} unavailable group decisions" in verdict
    assert f"{0 if spy_available else 5} ticker-sessions had incomplete evidence" in verdict
    operand = 1 if group == "strength_only" else 3
    spy_sessions = 5 if spy_available else 0
    assert f"Condition {operand} (relative_strength) had {spy_sessions} evaluated and {5 - spy_sessions} unavailable" in verdict
    if not evaluated:
        assert stored["verdict_label"] == "insufficient"
        assert "Insufficient rule data" in verdict
        assert stored["is_total_return"] is None and stored["oos_total_return"] is None
    else:
        assert "Condition 1 (relative_volume) had 5 evaluated and 0 unavailable" in verdict
