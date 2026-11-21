from datetime import timedelta
from unittest.mock import Mock, patch

import mongomock
import pytest
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

from src.storage.mongo import MongoStore, utcnow
from src.storage.history import ScanHistory
from src.storage.checkpoint import OptionalMongoSaver
from src.storage.daily_prices import save_price_bars
from v2.data.cached_client import CachedDataClient
from v2.data.models import Price
from v2.scanner.models import ScanOutcome, ScoredEntry


def bar(close=11):
    return Price(open=10, high=max(12, close), low=9, close=close, volume=100, time='2026-10-22')


class Backend:
    def __init__(self):
        self.calls = 0
        self.quote_calls = 0
    def get_prices(self, ticker, start_date, end_date, **kwargs):
        self.calls += 1
        return [bar()]
    def get_quote(self, ticker):
        self.quote_calls += 1
        return {'price': 12}
    def close(self):
        pass


@pytest.fixture
def store():
    return MongoStore(mongomock.MongoClient(tz_aware=True).market_scanner)


def test_unconfigured_mongo_still_returns_online_prices(monkeypatch):
    monkeypatch.delenv('MONGODB_URI', raising=False)
    backend = Backend()
    client = CachedDataClient(backend, store=MongoStore())
    assert client.get_prices('SPY', '2026-10-20', '2026-10-22') == [bar()]
    assert backend.calls == 1
    assert client.store.status == 'unconfigured'


def test_mongo_hit_skips_provider_and_rehydrates_models(store):
    online = Backend()
    client = CachedDataClient(online, store=store)
    first = client.get_prices('SPY', '2026-10-20', '2026-10-22')
    second = client.get_prices(ticker='SPY', start_date='2026-10-20', end_date='2026-10-22')
    assert first == second
    assert online.calls == 1
    assert store._db.price_bars.count_documents({}) == 1
    assert client.evidence[0] == client.evidence[1]


def test_expired_or_different_range_fetches_online(store):
    online = Backend()
    client = CachedDataClient(online, store=store)
    client.get_prices('SPY', '2026-10-20', '2026-10-22')
    store._db.company_snapshots.update_many({}, {'$set': {'payload.expires_at': utcnow() - timedelta(seconds=1)}})
    client.get_prices('SPY', '2026-10-20', '2026-10-22')
    client.get_prices('SPY', '2026-10-01', '2026-10-22')
    assert online.calls == 3
    assert store._db.price_bars.count_documents({}) == 1  # no duplicate evidence revision


def test_driver_failure_does_not_hide_online_result_or_log_credentials(store, caplog):
    with patch.object(store._db.company_snapshots, 'find_one', side_effect=RuntimeError('mongodb://secret:password@host')):
        client = CachedDataClient(Backend(), store=store)
        assert client.get_prices('SPY', '2026-10-20', '2026-10-22') == [bar()]
    assert store.status == 'unavailable'
    assert 'password' not in caplog.text
    assert 'secret' not in caplog.text


def test_quotes_never_enter_mongo(store):
    client = CachedDataClient(Backend(), store=store)
    client.get_quote('SPY')
    client.get_quote('SPY')
    assert client.backend.quote_calls == 2
    assert store._db.company_snapshots.count_documents({}) == 0


def test_revisions_preserve_old_bars(store):
    backend = Backend()
    client = CachedDataClient(backend, store=store)
    client.get_prices('SPY', '2026-10-20', '2026-10-22')
    store._db.company_snapshots.update_many({}, {'$set': {'payload.expires_at': utcnow() - timedelta(seconds=1)}})
    backend.get_prices = lambda ticker, start_date, end_date, **kwargs: [bar(13)]
    client.get_prices('SPY', '2026-10-20', '2026-10-22')
    assert [r['revision'] for r in store._db.price_bars.find().sort('revision')] == [1, 2]


def outcomes():
    return [ScanOutcome(ticker='A', outcome='evaluated', selected=True,
        entry=ScoredEntry(ticker='A', composite_score=80., event_score=80., rank=1),
        detector_results=[{'detector': 'test', 'version': '1', 'status': 'triggered', 'signal_session': '2026-10-21'}]),
        ScanOutcome(ticker='B', outcome='evaluated', detector_results=[{'detector': 'test', 'version': '1', 'status': 'no_event'}]),
        ScanOutcome(ticker='C', outcome='no_data', detector_results=[{'detector': 'test', 'version': '1', 'status': 'no_data'}]),
        ScanOutcome(ticker='D', outcome='error', detector_results=[{'detector': 'test', 'version': '1', 'status': 'error'}])]


def save_scan(store, key='slot1'):
    return ScanHistory(store).save(execution_key=key, owner_id='owner', config_id=1, config={'weight': 1},
        scan_date='2026-10-22', universe=['A', 'B', 'C', 'D'], outcomes=outcomes())


def test_full_universe_and_independent_rescans(store):
    assert save_scan(store)['status'] == 'partial'
    assert save_scan(store)['reused']
    selected = store._db.scan_results.find_one({'selected': True})
    assert selected['quality']['signal_sessions'] == {'test': '2026-10-21'}
    # Installed validators accept only the original detector_results keys.
    assert 'signal_session' not in selected['detector_results'][0]
    assert store._db.scan_results.count_documents({}) == 4
    save_scan(store, 'manual2')
    assert store._db.scan_results.count_documents({}) == 8
    assert store._db.datasets.count_documents({}) == 2
    assert ScanHistory(store).list_runs('someone_else') == []


def test_history_failure_never_publishes_success(store):
    with patch.object(store._db.scan_results, 'insert_one', side_effect=RuntimeError('write failure')):
        assert save_scan(store).get('persisted') is False
    assert store._db.scan_runs.find_one()['status'] == 'failed'


def test_missing_outcome_is_not_full_coverage(store):
    with pytest.raises(ValueError, match='exactly one'):
        ScanHistory(store).save(execution_key='x', owner_id='o', config_id=1, config={}, scan_date='2026-10-22',
                               universe=['A', 'B'], outcomes=outcomes()[:1])


def test_checkpoint_resume_does_not_repeat_successful_node(store):
    class State(TypedDict):
        count: int
    calls = []
    should_fail = [True]
    def first(state):
        calls.append('first')
        return {'count': 1}
    def second(state):
        calls.append('second')
        if should_fail.pop() if should_fail else False:
            raise RuntimeError('simulated interruption')
        return {'count': state['count'] + 1}
    graph = StateGraph(State)
    graph.add_node('one', first); graph.add_node('two', second)
    graph.add_edge(START, 'one'); graph.add_edge('one', 'two'); graph.add_edge('two', END)
    config = {'configurable': {'thread_id': 'owner:run'}}
    with pytest.raises(RuntimeError):
        graph.compile(checkpointer=OptionalMongoSaver(store)).invoke({'count': 0}, config)
    result = graph.compile(checkpointer=OptionalMongoSaver(store)).invoke(None, config)
    assert result['count'] == 2
    assert calls.count('first') == 1


def test_existing_raw_mongo_bars_cover_overlapping_request(store):
    from datetime import datetime, timezone
    now = utcnow()
    instrument = store.instrument('SPY', store._db)
    bars = [bar().model_copy(update={'time': day}).model_dump(mode='json')
            for day in ['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05']]
    save_price_bars(store._db, instrument, bars, now)
    backend = Backend()
    rows = CachedDataClient(backend, store=store).get_prices('SPY', '2024-01-02', '2024-01-05')
    assert len(rows) == 4
    assert backend.calls == 0


def test_yahoo_keeps_raw_prices_actions_and_inclusive_end():
    import pandas as pd
    from v2.data.yfinance_client import YFinanceClient
    frame = pd.DataFrame({'Open': [100.], 'High': [102.], 'Low': [98.], 'Close': [101.],
        'Volume': [100], 'Adj Close': [50.5], 'Dividends': [1.], 'Stock Splits': [2.]},
        index=pd.DatetimeIndex(['2024-01-05'], tz='America/New_York'))
    with patch('yfinance.Ticker') as ticker:
        ticker.return_value.history.return_value = frame
        result = YFinanceClient().get_prices('BRK.B', '2024-01-02', '2024-01-05')
        ticker.assert_called_once_with('BRK-B')
        kwargs = ticker.return_value.history.call_args.kwargs
        assert kwargs['end'] == '2024-01-06'
        assert kwargs['auto_adjust'] is False
    assert result[0].close == 101
    assert result[0].adjusted_close == 50.5
    assert result[0].dividend == 1
    assert result[0].split_ratio == 2


def test_report_reuse_is_owner_scoped_and_force_bypasses(store):
    from mongomock.gridfs import enable_gridfs_integration
    enable_gridfs_integration()
    from src.storage.analysis import AnalysisHistory
    from src.research.models import AnalyzeRequest, SectionPayload
    from src.research.shared_data import SharedData
    request = AnalyzeRequest(ticker='SPY', objective='medium_term', position_budget_usd=None,
        already_holds=False, cost_basis_usd=None, risk_tolerance='balanced', use_personas=False,
        included_sections={'data_health'})
    shared = SharedData(ticker='SPY', scan_date='2026-10-22', prices=[bar()], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None, earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[])
    history = AnalysisHistory(store)
    ticket = history.start(owner_id='a', request=request, shared=shared)
    report = {'request': request, 'sections': {'data_health': SectionPayload(name='data_health', markdown='ok',
        structured=None, skipped=False, persona_used=None)}, 'backtest': None, 'rendered_html': '<html>ok</html>'}
    assert history.save(ticket, report)
    assert history.start(owner_id='a', request=request, shared=shared)['cached']
    assert history.start(owner_id='b', request=request, shared=shared)['cached'] is None
    assert history.start(owner_id='a', request=request, shared=shared, force=True)['cached'] is None
    assert store._db.reports.find_one()['artifacts'][0]['mime'] == 'text/html'


def test_source_scan_reference_cannot_cross_owners(store):
    from src.storage.analysis import AnalysisHistory
    from src.research.models import AnalyzeRequest
    from src.research.shared_data import SharedData
    from bson import ObjectId
    request = AnalyzeRequest(ticker='SPY', objective='medium_term', position_budget_usd=None,
        already_holds=False, cost_basis_usd=None, risk_tolerance='balanced', use_personas=False)
    shared = SharedData(ticker='SPY', scan_date='2026-10-22', prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[], company_facts={}, sector_etf_prices=[], spy_prices=[])
    with pytest.raises(ValueError, match='unauthorized'):
        AnalysisHistory(store).start(owner_id='b', request=request, shared=shared, source_scan_result_id=str(ObjectId()))


def test_retired_detectors_remain_explicit_outcomes():
    from v2.scanner.runner import run_scan
    from v2.scanner.models import ScannerWeights
    from v2.scanner.detectors import RETIRED_DETECTORS
    name = sorted(RETIRED_DETECTORS)[0]
    seen = []
    result = run_scan(tickers=['SPY'], end_date='2026-10-22', detectors=[],
        weights=ScannerWeights(enabled_detectors=[name]), provider_factory=Backend, outcome_cb=seen.append)
    assert result == []
    assert seen[0].detector_results == [{'detector': name, 'version': 'retired', 'status': 'retired'}]
    assert seen[0].entry is None


def test_legacy_migration_is_idempotent_and_never_invents_full_universe(store):
    from mongomock.gridfs import enable_gridfs_integration
    enable_gridfs_integration()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.backend.database.models import Base, User, ScannerConfig, ScanRun, WatchlistEntry, ResearchReport
    from src.storage.migration import migrate
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(id=1, email='migration@example.invalid', is_active=True)
        config = ScannerConfig(name='legacy', user_id=1, universe_kind='custom', universe_tickers=['A'])
        session.add_all([user, config]); session.flush()
        run = ScanRun(config_id=config.id, status='COMPLETE', universe_size=10)
        report = ResearchReport(ticker='A', scan_date='2024-01-01', request_json={'ticker': 'A'},
            report_markdown='# Original report', rendered_html='<p>Original</p>', user_id=1)
        session.add_all([run, report]); session.flush()
        session.add(WatchlistEntry(scan_run_id=run.id, ticker='A', composite_score=80., direction='neutral',
                                   event_score=80., rank=1, triggers=[]))
        session.commit()
        assert migrate(session, store=store)['reports'] == 1
        assert store._db.reports.count_documents({}) == 0
        migrate(session, store=store, apply=True)
        migrate(session, store=store, apply=True)
        assert store._db.reports.count_documents({}) == 1
        assert store._db.scan_runs.count_documents({}) == 1
        assert store._db.scan_results.count_documents({}) == 1
        assert store._db.scan_runs.find_one()['coverage_mode'] == 'legacy_topn_only'
        assert store._db.datasets.count_documents({}) == 0
        assert store._db.reports.find_one()['provenance'] == 'legacy_unverified'
        assert session.query(ResearchReport).count() == 1
        assert session.query(WatchlistEntry).count() == 1
    engine.dispose()


def test_scan_report_reuse_requires_same_sql_signal_and_keeps_original_market_observation(store):
    from dataclasses import replace
    from mongomock.gridfs import enable_gridfs_integration
    from src.research.models import AnalyzeRequest
    from src.research.shared_data import SharedData
    from src.research.sop_orchestrator import run_sop
    from src.storage.analysis import AnalysisHistory

    enable_gridfs_integration()
    signal = {"scan_result_id": 21, "scan_run_id": 10, "ticker": "SPY", "rank": 1,
              "direction": "bullish", "composite_score": 80.0, "triggers": []}
    request = AnalyzeRequest(ticker="SPY", objective="medium_term", position_budget_usd=None,
        already_holds=False, cost_basis_usd=None, risk_tolerance="balanced", use_personas=False,
        included_sections={"data_health"}, source_scan_evidence=signal)
    shared = SharedData(ticker="SPY", scan_date="2026-10-22", prices=[bar()], financials=[],
        insider_trades=[], news=[], analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[])
    with patch("src.research.sop_orchestrator.fetch_shared_data", return_value=shared), \
         patch("src.research.sop_orchestrator.run_signal_backtest", return_value=None), \
         patch("src.storage.analysis.AnalysisHistory", return_value=AnalysisHistory(store)), \
         patch("src.storage.checkpoint.get_store", return_value=store):
        stored = run_sop(request, owner_id=1)
        reused = run_sop(request, owner_id=1)
        assert reused["reused"]
        assert reused["analysis_market_evidence"] == stored["analysis_market_evidence"]
        for changed in (None, dict(signal, scan_result_id=22), dict(signal, direction="bearish")):
            different = run_sop(replace(request, source_scan_evidence=changed), owner_id=1)
            assert not different.get("reused")
            assert different["usage"]["cache_hits"] == 0
        with pytest.raises(ValueError, match="unauthorized"):
            run_sop(replace(request, source_scan_evidence=None), owner_id=1,
                    resume_run_id=stored["analysis_run_id"])


def test_historical_consensus_ignores_legacy_backdated_cache(store):
    from src.storage.mongo import digest
    from v2.data.yfinance_client import YFinanceClient

    request = {"ticker": "AAPL", "asof_date": "2001-01-05"}
    key = digest({"source": "hybrid", "method": "get_analyst_targets", "request": request, "schema": 1})
    store._db.company_snapshots.insert_one({
        "snapshot_kind": "provider_response", "content_hash": "legacy",
        "observed_at": utcnow(), "payload": {
            "request_key": key, "expires_at": utcnow() + timedelta(days=1),
            "result": {"ticker": "AAPL", "asof_date": "2001-01-05", "target_mean": 990.},
        },
    })
    with patch("yfinance.Ticker") as live:
        assert CachedDataClient(YFinanceClient(), store=store).get_analyst_targets(**request) is None
        live.assert_not_called()
