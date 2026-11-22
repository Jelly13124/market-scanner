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


@pytest.mark.parametrize("analysis_status", [None, "partial"])
@patch("app.backend.routes.lab.run_backtest")
def test_report_draft_uses_saved_evidence_and_confirms_each_revision(mock_run, client, analysis_status):
    from app.backend.database.models import ResearchReport, UniverseSnapshot, User
    from src.lab.backtest_runner import BacktestRunResult

    hdrs = _auth_header(client)
    group = {"combiner": "or", "signals": [{"type": "range_breakout", "window": 7}]}
    with next_db(client) as db:
        uid = db.query(User).one().id
        snapshot = UniverseSnapshot(user_id=uid, market="US", origin="scanner", tickers=["ABC"])
        db.add(snapshot)
        db.flush()
        snapshot_id = snapshot.id
        report = ResearchReport(user_id=uid, ticker="ABC", scan_date="2024-02-29", request_json={},
                                report_markdown="Research", rendered_html="<p>Research</p>",
                                analyze_request_json={"analysis_status": analysis_status, "source_scan_evidence": {
                                    "ticker": "ABC", "market": "us", "scan_result_id": 91,
                                    "universe_snapshot_id": snapshot_id,
                                    "detector_config": {"weights": {"rule_group": group}}}})
        db.add(report)
        db.commit()
        path = f"/lab/reports/{report.id}/strategy-draft"
    foreign = client.post("/auth/register", json={"email": "foreign@example.com", "password": "pw123456"})
    foreign_headers = {"Authorization": "Bearer " + foreign.json()["access_token"]}
    assert client.post(path, headers=foreign_headers).status_code == 404
    response = client.post(path, headers=hdrs)
    assert response.status_code == 200, response.text
    draft = response.json()
    config = draft["spec_json"]["backtest_config"]
    assert config["end_date"] == "2024-03-01"
    assert config["start_date"] == "2021-02-28"
    assert {"commission_bps", "slippage_bps", "starting_capital_usd", "max_concurrent_positions"} <= config.keys()
    assert client.get("/research/reports", headers=hdrs).json()[0]["can_draft_strategy"]
    assert draft["source_scan_result_id"] == 91
    assert draft["universe_snapshot_id"] == snapshot_id
    assert draft["spec_json"]["entry"]["signals"][0]["window"] == 7
    assert draft["spec_json"]["universe"] == {"kind": "snapshot", "snapshot_id": snapshot_id}
    assert client.post(path, headers=hdrs).json()["id"] == draft["id"]
    save = f"/lab/strategies/{draft['id']}"
    run = save + "/backtest"
    assert client.post(run, json={}, headers=hdrs).status_code == 409
    spec = draft["spec_json"]
    assert client.patch(save, json={"expected_version": 1, "spec_json": dict(spec, universe={"kind":"sp500"})}, headers=hdrs).status_code == 422
    assert client.patch(save, json={"expected_version": 1, "spec_json": dict(spec, backtest_config={})}, headers=hdrs).status_code == 422
    assert client.patch(save, json={"expected_version": 1, "spec_json": dict(spec, invented_execution="magic")}, headers=hdrs).status_code == 422
    with next_db(client) as db:
        from app.backend.repositories.lab_chat_repository import LabChatRepository
        proposal = LabChatRepository(db).add(strategy_id=draft["id"], user_id=uid, role="assistant",
                                             content="Change settings", spec_patch_json=spec)
        proposal_id = proposal.id
    chat_apply = save + "/chat/apply"
    assert client.patch(save, json={"spec_json": spec}, headers=foreign_headers).status_code == 404
    assert client.post(chat_apply, json={"message_id": proposal_id}, headers=foreign_headers).status_code == 404
    missing_version = client.patch(save, json={"spec_json": spec}, headers=hdrs)
    unversioned_proposal = client.post(chat_apply, json={"message_id": proposal_id}, headers=hdrs)
    assert (missing_version.status_code, unversioned_proposal.status_code) == (409, 409)
    assert "expected_version" in missing_version.json()["detail"]
    assert "editor" in unversioned_proposal.json()["detail"]
    spec["entry"]["signals"][0]["window"] = 10
    spec["exit"] = [{"type": "time_stop"}]
    saved = client.patch(save, json={"spec_json": spec, "expected_version": 1}, headers=hdrs).json()
    assert saved["version"] == 2
    assert saved["spec_json"]["exit"] == [{"type": "time_stop", "bars": 20}]
    spec = saved["spec_json"]
    assert client.patch(save, json={"spec_json": spec, "expected_version": 1}, headers=hdrs).status_code == 409
    assert client.post(run, json={"confirm_version": 1}, headers=hdrs).status_code == 409
    mock_run.assert_not_called()
    mock_run.return_value = BacktestRunResult(spec, "2023-01-01", "2025-01-01", "2024-01-01", 1, None, None, None, None)
    from dataclasses import replace
    mock_run.side_effect = [
        replace(mock_run.return_value, error_message="No tradable input data"),
        mock_run.return_value,
    ]
    failed = client.post(run, json={"confirm_version": 2}, headers=hdrs)
    assert failed.status_code == 503, failed.text
    assert "No tradable input data" in failed.json()["detail"]
    with next_db(client) as db:
        from app.backend.database.models import ConfirmedStrategyRevision
        assert db.query(ConfirmedStrategyRevision).count() == 0
    assert client.get(save + "/backtests", headers=hdrs).json() == []
    result = client.post(run, json={"confirm_version": 2}, headers=hdrs)
    assert result.status_code == 200, result.text
    assert result.json()["confirmed_version"] == 2
    assert result.json()["confirmed_revision_id"]
    assert client.post(run, json={"confirm_version": 2}, headers=hdrs).json()["id"] == result.json()["id"]
    assert mock_run.call_count == 2
    assert result.json()["source_report_id"] == draft["source_report_id"]
    assert result.json()["source_scan_result_id"] == 91
    assert client.post(run, headers=foreign_headers, json={"confirm_version": 2}).status_code == 404
    with next_db(client) as db:
        from app.backend.database.models import ConfirmedStrategyRevision
        revision = db.query(ConfirmedStrategyRevision).one()
        assert revision.spec_json == spec
    spec["entry"]["signals"][0]["window"] = 20
    assert client.patch(save, json={"spec_json": spec, "expected_version": 2}, headers=hdrs).json()["version"] == 3
    previous = client.get(f"/lab/backtests/{result.json()['id']}", headers=hdrs).json()
    assert previous["spec_snapshot_json"]["entry"]["signals"][0]["window"] == 10


def next_db(client):
    from contextlib import contextmanager
    return contextmanager(client.app.dependency_overrides[get_db])()


@pytest.mark.parametrize("market,owner,status,block", [
    ("ALL", "self", "succeeded", "range_breakout"),
    ("US", "other", "succeeded", "range_breakout"),
    ("US", "self", "failed", "range_breakout"),
    ("US", "self", "succeeded", "unsupported_block"),
])
def test_unsuitable_report_is_not_offered_for_drafting(client, market, owner, status, block):
    from app.backend.database.models import ResearchReport, UniverseSnapshot, User

    hdrs = _auth_header(client)
    with next_db(client) as db:
        uid = db.query(User).one().id
        other = User(email="separate@example.com")
        db.add(other)
        db.flush()
        snapshot = UniverseSnapshot(user_id=uid if owner == "self" else other.id, market=market,
                                    origin="scanner", tickers=["ABC"])
        db.add(snapshot)
        db.flush()
        report = ResearchReport(user_id=uid, ticker="ABC", scan_date="2024-02-29", request_json={},
                                report_markdown="Research", rendered_html="Research",
                                analyze_request_json={"analysis_status": status, "source_scan_evidence": {
                                    "ticker": "ABC", "market": "us", "scan_result_id": 1, "universe_snapshot_id": snapshot.id,
                                    "detector_config": {"weights": {"rule_group": {
                                        "combiner": "and", "signals": [{"type": block}]}}}}})
        db.add(report)
        db.commit()
        path = f"/lab/reports/{report.id}/strategy-draft"
    assert not client.get("/research/reports", headers=hdrs).json()[0]["can_draft_strategy"]
    assert client.post(path, headers=hdrs).status_code in (404, 422)
