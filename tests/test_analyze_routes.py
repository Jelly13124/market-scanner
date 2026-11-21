"""POST /research/analyze tests with mocked run_sop + render_sop."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.backend.auth.dependencies import get_current_user
from app.backend.database.connection import Base, get_db
from app.backend.database.models import ApiKey, User
from app.backend.main import app
from src.research.models import (
    AnalyzeRequest, AnalyzeReport, BacktestVerdict, SectionPayload,
    SECTION_ORDER,
)


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

    _fake_user = User(id=1, email="test@test.com", is_active=True, is_superuser=False)

    # Per-user keys (Wave A4): /research/analyze now fails fast (400) when the
    # acting user lacks the configured provider's key. Seed a matching user row
    # (id=1) + the DeepSeek key so these run-path tests exercise the SOP flow
    # rather than the new key gate. Seed a SEPARATE User instance — keep the
    # _fake_user returned by the override transient so reading .id never tries
    # to refresh from a closed session (DetachedInstanceError).
    _seed = Session()
    try:
        _seed.add(User(id=1, email="test@test.com", is_active=True, is_superuser=False))
        _seed.add(ApiKey(provider="DEEPSEEK_API_KEY", key_value="sk-test-deepseek",
                         is_active=True, user_id=1))
        _seed.commit()
    finally:
        _seed.close()

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_current_user] = lambda: _fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _fake_report(ticker="NVDA"):
    req = AnalyzeRequest(
        ticker=ticker, objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=True,
    )
    sections = {
        n: SectionPayload(
            name=n, markdown=f"## {n}\n\nbody for {n}",
            structured=None, skipped=False, persona_used=None,
        )
        for n in SECTION_ORDER
    }
    return AnalyzeReport(
        request=req, sections=sections,
        persona_assignments={"fundamentals": "buffett",
                             "valuation": "graham",
                             "risk_position": None,
                             "debate": ["wood", "burry"],
                             "_rationale": "x"},
        backtest=BacktestVerdict(
            signal="rsi_oversold", window_start="2020-01-01",
            window_end="2026-05-22", n_signals=10, win_rate_20d=0.6,
            avg_return_20d=0.02, t_stat=2.1, significant=True,
            verdict="significant",
        ),
        rendered_html=None,
    )


class TestAnalyzeEndpoint:
    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_happy_path(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html><body>NVDA report</body></html>"
        resp = client.post("/research/analyze", json={
            "ticker": "nvda",  # lowercased — schema should uppercase
            "objective": "medium_term",
            "position_budget_usd": 10000,
            "risk_tolerance": "balanced",
            "use_personas": True,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ticker"] == "NVDA"
        assert body["objective"] == "medium_term"
        assert body["use_personas"] is True
        assert "data_health" in body["sections"]
        assert body["sections"]["data_health"]["name"] == "data_health"
        assert body["backtest"]["signal"] == "rsi_oversold"
        assert body["persona_assignments"]["fundamentals"] == "buffett"

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_minimal_request(self, mock_render, mock_run, client):
        """Just ticker is enough — other fields default."""
        mock_run.return_value = _fake_report("AAPL")
        mock_render.return_value = "<html></html>"
        resp = client.post("/research/analyze", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["objective"] == "general_research"
        assert body["risk_tolerance"] == "balanced"
        assert body["use_personas"] is False

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_persists_to_db(self, mock_render, mock_run, client):
        from app.backend.repositories.research_repository import (
            ResearchReportRepository)
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html>x</html>"
        resp = client.post("/research/analyze", json={"ticker": "NVDA"})
        report_id = resp.json()["id"]
        # Fetch via existing Phase 3 endpoint to confirm it's there
        r2 = client.get(f"/research/reports/{report_id}/html")
        assert r2.status_code == 200
        assert "<html>x</html>" in r2.text

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_debate_rounds_round_trips(self, mock_render, mock_run, client):
        """Phase 5E — debate_rounds=4 should flow into the AnalyzeRequest
        handed to run_sop."""
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html></html>"
        resp = client.post("/research/analyze", json={
            "ticker": "NVDA",
            "debate_rounds": 4,
        })
        assert resp.status_code == 200, resp.text
        # run_sop was called with the internal AnalyzeRequest
        called_with = mock_run.call_args[0][0]
        assert called_with.debate_rounds == 4

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_debate_rounds_defaults_to_one(self, mock_render, mock_run, client):
        """When the field is omitted, backend defaults to 1."""
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html></html>"
        resp = client.post("/research/analyze", json={"ticker": "NVDA"})
        assert resp.status_code == 200, resp.text
        called_with = mock_run.call_args[0][0]
        assert called_with.debate_rounds == 1

    @patch("app.backend.routes.research.run_sop")
    @patch("app.backend.routes.research.render_sop")
    def test_debate_rounds_rejects_out_of_range(self, mock_render, mock_run, client):
        """Pydantic must reject values outside 1..5."""
        mock_run.return_value = _fake_report("NVDA")
        mock_render.return_value = "<html></html>"
        for bad in (0, 6, -1, 100):
            resp = client.post("/research/analyze", json={
                "ticker": "NVDA", "debate_rounds": bad,
            })
            assert resp.status_code == 422, f"expected 422 for {bad}, got {resp.status_code}"


@pytest.mark.parametrize('sections', [[], ['not_a_section']])
def test_invalid_sections_rejected_before_model_call(client, sections):
    with patch('app.backend.routes.research.run_sop') as run:
        response = client.post('/research/analyze', json={'ticker': 'AAPL', 'included_sections': sections})
    assert response.status_code == 422
    run.assert_not_called()


def test_omitted_sections_still_mean_all():
    from app.backend.routes.research import _to_analyze_request
    from app.backend.models.research_schemas import AnalyzeRunRequest
    assert _to_analyze_request(AnalyzeRunRequest(ticker='AAPL')).included_sections == set(SECTION_ORDER)


def _seed_signal(*, owner=1):
    from datetime import datetime, timezone
    from app.backend.database.models import ScannerConfig, ScanRun, WatchlistEntry
    sessions = app.dependency_overrides[get_db]()
    db = next(sessions)
    try:
        config = ScannerConfig(name="signal", universe_kind="custom", user_id=owner)
        db.add(config)
        db.flush()
        run = ScanRun(config_id=config.id, status="COMPLETE", detector_config={
            "as_of": "2026-10-14",
            "detectors": [{"name": "price_volume_anomaly", "version": "volume-v3",
                "description": "High volume on a flat-return day",
                "parameters": {"volume_z_threshold": 2.65, "volume_window": 23}}],
        })
        run.started_at = datetime(2026, 10, 15, 1, 23, 45, tzinfo=timezone.utc)
        db.add(run)
        db.flush()
        entry = WatchlistEntry(scan_run_id=run.id, ticker="NVDA", rank=1,
            composite_score=88, direction="bullish", triggers=[{
                "detector": "price_volume_anomaly", "signal_session": "2026-10-13",
                "reason": "Volume exceeded baseline", "components": {"volume_ratio": 2.75},
            }])
        db.add(entry)
        db.commit()
        return entry.id
    finally:
        sessions.close()


def test_owned_scanner_signal_reaches_model_and_saved_report_without_mongo(client, monkeypatch):
    from src.research.shared_data import SharedData
    from src.research.router import _RouterOutput
    from src.research.sections.valuation import _Narrative
    from v2.data.models import Price

    monkeypatch.setenv("MONGODB_URI", "")
    monkeypatch.setattr("src.research.quant_context._FLOW_ENABLED", False)
    source_id = _seed_signal()
    shared = SharedData(ticker="NVDA", scan_date="2026-11-20",
        prices=[Price(open=10, high=15, low=9, close=14.25, volume=90, time="2026-11-19")],
        financials=[], insider_trades=[], news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={}, sector_etf_prices=[], spy_prices=[])
    with patch("src.research.sop_orchestrator.fetch_shared_data", return_value=shared), \
         patch("src.research.sop_orchestrator.run_signal_backtest", return_value=None), \
         patch("src.research.llm.get_model") as model:
        invoke = model.return_value.with_structured_output.return_value.invoke
        invoke.side_effect = [_RouterOutput(fundamentals=None, valuation=None, risk_position=None,
                                            debate=[], rationale="Use objective sections."),
                              _Narrative(narrative="Test valuation")]
        response = client.post("/research/analyze", json={
            "ticker": "NVDA", "source_scan_result_id": source_id, "included_sections": ["valuation"], "use_personas": True,
            "source_scan_evidence": {"triggers": [{"reason": "untrusted user evidence"}]},
        })
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["source_scan_result_id"] == source_id
    assert report["source_scan_evidence"]["scan_started_at"] == "2026-10-15T01:23:45+00:00"
    assert report["source_scan_evidence"]["triggers"][0]["signal_session"] == "2026-10-13"
    assert report["analysis_market_evidence"]["latest_price_session"] == "2026-11-19"
    assert report["analysis_market_evidence"]["latest_close"] == 14.25
    assert report["analysis_market_evidence"]["observed_at"]
    router_prompt, prompt = [call.args[0] for call in invoke.call_args_list]
    assert "Scanner triggers: ['price_volume_anomaly']" in router_prompt
    html = client.get(f"/research/reports/{report['id']}/html").text
    from app.backend.database.models import ResearchReport
    sessions = app.dependency_overrides[get_db]()
    try:
        saved = next(sessions).get(ResearchReport, report["id"])
        assert saved.source_scan_result_id == source_id
        markdown = saved.report_markdown
    finally:
        sessions.close()
    for text in (html, router_prompt, prompt, markdown):
        assert "Scan started at 2026-10-15T01:23:45+00:00" in text
        assert "Scan as of 2026-10-14" in text
        assert "High volume on a flat-return day" in text
        assert "volume_z_threshold = 2.65" in text and "volume_window = 23" in text
        assert "volume-v3" in text
        assert "Original Scanner signal" in text
        assert "2.75" in text and "2026-10-13" in text
        assert "Analysis market evidence" in text and "2026-11-19" in text
        assert "untrusted user evidence" not in text


@pytest.mark.parametrize(("owner", "ticker", "market"), [(2, "NVDA", "us"), (1, "MSFT", "us"), (1, "NVDA", "cn")])
def test_scan_source_must_match_owner_ticker_and_market(client, owner, ticker, market):
    source_id = _seed_signal(owner=owner)
    with patch("app.backend.routes.research.run_sop") as analyze:
        response = client.post("/research/analyze", json={"ticker": ticker, "market": market,
                                                         "source_scan_result_id": source_id})
    assert response.status_code == 404
    analyze.assert_not_called()


def test_legacy_mongo_source_is_validated_separately_from_sql_ids(client, monkeypatch):
    from bson import ObjectId
    import mongomock
    from src.storage.mongo import MongoStore
    from app.backend.database.models import ResearchReport

    archive = mongomock.MongoClient(tz_aware=True).archive
    store = MongoStore(archive)
    monkeypatch.setattr("src.storage.mongo.get_store", lambda: store)
    instrument = store.instrument("NVDA", archive)
    run = archive.scan_runs.insert_one({"owner_id": "1", "scan_date": "2026-09-08"}).inserted_id
    row = {"scan_run_id": run, "instrument_id": instrument, "owner_id": "1",
           "outcome": "evaluated", "selected": True, "rank": 1, "composite_score": 50,
           "direction": "neutral", "detector_results": [],
           "quality": {"legacy_topn_only": True, "legacy_triggers": [{"detector": "archive_volume", "reason": "Archived signal"}]}}
    reference = str(archive.scan_results.insert_one(dict(row)).inserted_id)
    other = str(archive.scan_results.insert_one(dict(row, owner_id="2")).inserted_id)
    fired = {"detector": "archive_volume", "status": "triggered", "reason": "Native signal"}
    native = dict(row, quality={}, detector_results=[fired])
    native_id = str(archive.scan_results.insert_one(dict(native)).inserted_id)
    unselected = str(archive.scan_results.insert_one(dict(native, selected=False)).inserted_id)
    no_trigger = str(archive.scan_results.insert_one(dict(native, detector_results=[
        dict(fired, status="no_event")])).inserted_id)
    with patch("app.backend.routes.research.run_sop") as analyze:
        analyze.side_effect = lambda request, **kwargs: dict(_fake_report(), request=request)
        for bad_id, symbol, market in [(unselected, "NVDA", "us"), (no_trigger, "NVDA", "us"),
                                        (other, "NVDA", "us"), (reference, "NVDA", "cn"),
                                        (reference, "MSFT", "us"), (str(ObjectId()), "NVDA", "us")]:
            response = client.post("/research/analyze", json={
                "source_scan_result_id": bad_id, "ticker": symbol, "market": market, "resume_run_id": str(ObjectId())})
            assert response.status_code == 404, response.text
        analyze.assert_not_called()
        native_response = client.post("/research/analyze", json={"ticker": "NVDA", "source_scan_result_id": native_id})
        assert native_response.status_code == 200, native_response.text
        assert native_response.json()["source_scan_evidence"]["triggers"][0]["reason"] == "Native signal"
        response = client.post("/research/analyze", json={"ticker": "NVDA", "source_scan_result_id": reference})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["source_scan_result_id"] is None
    assert report["source_scan_evidence"]["mongo_scan_result_id"] == reference
    assert report["source_scan_evidence"]["scan_started_at"] is None
    assert "Archived signal" in client.get(f"/research/reports/{report['id']}/html").text
    sessions = app.dependency_overrides[get_db]()
    try:
        saved = next(sessions).get(ResearchReport, report["id"])
        assert saved.source_scan_result_id is None
        assert saved.analyze_request_json["source_scan_result_id"] == reference
    finally:
        sessions.close()
