from datetime import datetime, timezone
from unittest.mock import Mock

import mongomock
import pytest

from scripts.backfill_prices import closed_sessions, pool, sync_ticker
from src.storage.daily_prices import save_price_bars
from src.storage.mongo import MongoStore
from v2.data.cached_client import CachedDataClient
from v2.data.models import Price
from v2.data.yfinance_client import YFinanceClient


def test_window_uses_closed_sessions_even_on_half_days():
    before = datetime(2025, 11, 28, 17, 59, tzinfo=timezone.utc)
    after = before.replace(hour=18)
    assert closed_sessions(before)[-1] == '2025-11-26'
    assert closed_sessions(after)[-1] == '2025-11-28'
    assert closed_sessions(after)[0] == '2020-11-30'


def test_pool_includes_one_benchmark():
    assert pool(None, ['aapl', 'spy', 'AAPL']) == ['AAPL', 'SPY']
    assert pool(None, ['AAPL']) == ['AAPL', 'SPY']
    assert 'MSFT' in pool('nasdaq100_sp500', None)


def test_partial_resume_with_disjoint_gaps_and_offline_repeat():
    db = mongomock.MongoClient(tz_aware=True).history
    store = MongoStore(db)
    dates = ['2025-02-10', '2025-02-11', '2025-02-12', '2025-02-13']
    def bar(day):
        return Price(time=day, open=10, high=12, low=9, close=11,
                     adjusted_close=11, volume=100, dividend=0, split_ratio=0)
    fetch = Mock(side_effect=[[bar(dates[1]), bar(dates[3])], [bar(dates[0])], [bar(dates[2])]])
    assert sync_ticker(store, db, 'SPY', dates, fetch)['status'] == 'partial'
    assert sync_ticker(store, db, 'SPY', dates, fetch)['status'] == 'succeeded'
    assert sync_ticker(store, db, 'SPY', dates, fetch)['status'] == 'cached'
    assert [call.args[1:] for call in fetch.call_args_list] == [
        (dates[0], dates[3]), (dates[0], dates[0]), (dates[2], dates[2])]
    assert db.price_bars.count_documents({'revision': 1}) == 4
    assert db.data_sync_jobs.count_documents({}) == 2
    one = db.price_bars.find_one({'session_date': dates[0]})
    assert one['bar_time'].hour == 14 and one['bar_time'].minute == 30


def test_provider_error_records_failed_window():
    db = mongomock.MongoClient(tz_aware=True).history
    result = sync_ticker(MongoStore(db), db, 'SPY', ['2025-02-10'], Mock(side_effect=TimeoutError))
    assert result['status'] == 'failed'
    assert db.data_sync_jobs.find_one()['coverage']['missing_ranges'] == [['2025-02-10', '2025-02-10']]


def test_closed_history_remains_readable_after_response_cache_expires(monkeypatch):

    db = mongomock.MongoClient(tz_aware=True).history
    store = MongoStore(db)
    day = '2024-01-03'
    bar = Price(open=10, low=9, high=12, close=11, volume=2, time=day)
    sync_ticker(store, db, 'SPY', [day], Mock(return_value=[bar]))
    monkeypatch.setattr('v2.data.cached_client.utcnow', lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))

    def offline(self, ticker, start_date, end_date):
        raise AssertionError('A fully stored past session must read locally')

    monkeypatch.setattr(YFinanceClient, 'get_prices', offline)
    assert CachedDataClient(YFinanceClient(), store=store).get_prices('SPY', day, day) == [bar]


def test_seed_rechecks_intraday_observation_even_if_values_are_identical():
    db = mongomock.MongoClient(tz_aware=True).history
    store = MongoStore(db)
    day = '2024-01-03'
    bar = Price(open=10, low=9, high=12, close=11, volume=2, time=day)
    instrument = store.instrument('SPY', db)
    save_price_bars(db, instrument, [bar.model_dump()], datetime(2024, 1, 3, 16, tzinfo=timezone.utc))
    fetch = Mock(return_value=[bar])
    assert sync_ticker(store, db, 'SPY', [day], fetch)['status'] == 'succeeded'
    assert sync_ticker(store, db, 'SPY', [day], fetch)['status'] == 'cached'
    assert db.price_bars.count_documents({}) == fetch.call_count == 1


def test_spy_registered_as_etf_and_share_class_uses_yahoo_symbol():
    db = mongomock.MongoClient(tz_aware=True).history
    store = MongoStore(db)
    spy = store.instrument('SPY', db)
    brk = store.instrument('BRK.B', db)
    assert db.instruments.find_one({'_id': spy})['asset_type'] == 'etf'
    assert db.instruments.find_one({'_id': brk})['provider_symbols']['yahoo'] == 'BRK-B'


def test_explicit_pool_rejects_known_non_us_market_suffix():
    with pytest.raises(ValueError, match='US'):
        pool(None, ['AAPL', '600519.SH'])


def test_overlapping_writers_reconcile_duplicate_revision(monkeypatch):
    db = mongomock.MongoClient(tz_aware=True).history
    db.price_bars.create_index([(field, 1) for field in (
        'instrument_id', 'source', 'interval', 'session_date', 'revision')], unique=True)
    instrument = MongoStore(db).instrument('SPY', db)
    day = '2024-01-03'
    bar = Price(open=10, low=9, high=12, close=11, volume=2, time=day).model_dump()
    now = datetime(2024, 1, 4, tzinfo=timezone.utc)
    insert = db.price_bars.insert_many

    def concurrent_insert(docs, ordered):
        monkeypatch.setattr(db.price_bars, 'insert_many', insert)
        save_price_bars(db, instrument, [dict(bar, close=12)], now)
        return insert(docs, ordered=ordered)

    monkeypatch.setattr(db.price_bars, 'insert_many', concurrent_insert)
    save_price_bars(db, instrument, [bar], now)
    assert [float(r['close'].to_decimal()) for r in db.price_bars.find().sort('revision')] == [12, 11]
