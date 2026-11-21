"""Seed local Yahoo daily history and resume missing US trading sessions."""
import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import groupby
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from src.storage.mongo import digest, get_store, json_value, utcnow
from src.storage.daily_prices import calendar, observed_after_close, save_price_bars
from v2.data.yfinance_client import YFinanceClient
from v2.scanner.universes.loader import load_universe


def closed_sessions(now):
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    sessions = calendar().sessions_in_range(today - relativedelta(years=5), today)
    if calendar().session_close(sessions[-1]) > now:
        sessions = sessions[:-1]
    return [day.date().isoformat() for day in sessions]


def pool(universe, tickers):
    members = load_universe('custom', custom=tickers) if tickers else load_universe(universe)
    if not members:
        raise ValueError('Stock universe is empty')
    if any(symbol.endswith(('.SH', '.SZ', '.BJ')) for symbol in members):
        raise ValueError('Daily history supports US instruments only')
    return list(dict.fromkeys([*members, 'SPY']))


def missing_ranges(sessions, stored):
    ranges = []
    for missing, days in groupby(sessions, key=lambda day: day not in stored):
        if missing:
            gap = list(days)
            ranges.append([gap[0], gap[-1]])
    return ranges


def sync_ticker(store, db, ticker, sessions, fetch):
    instrument = store.instrument(ticker, db)
    start, end = sessions[0], sessions[-1]
    query = {'instrument_id': instrument, 'source': 'yahoo', 'interval': '1d',
             'session_date': {'$gte': start, '$lte': end}}

    def completed():
        rows = db.price_bars.find(query, {'_id': 0, 'session_date': 1, 'fetched_at': 1})
        return {row['session_date'] for row in rows if observed_after_close(row['session_date'], row['fetched_at'])}

    stored = completed()
    gaps = missing_ranges(sessions, stored)
    if not gaps:
        return {'ticker': ticker, 'status': 'cached', 'stored': len(sessions)}
    started = utcnow()
    expected = set(sessions)
    errors = set()
    for first, last in gaps:
        try:
            prices = fetch(ticker, first, last)
        except Exception as exc:
            errors.add(type(exc).__name__)
            continue
        bars = [json_value(p) for p in prices if first <= p.time <= last and p.time in expected
                and p.low <= min(p.open, p.close) <= max(p.open, p.close) <= p.high]
        if bars:
            save_price_bars(db, instrument, bars, utcnow())
    stored = expected.intersection(completed())
    remaining = missing_ranges(sessions, stored)
    status = 'succeeded'
    if remaining:
        status = 'failed' if errors and not stored else 'partial'
    key = digest(['daily_history', ticker, start, end])
    coverage = {'expected_sessions': len(sessions), 'stored_sessions': len(stored),
                'missing_ranges': remaining, 'provider_window_verified': not remaining}
    previous_attempts = db.data_sync_jobs.count_documents({
        'instrument_id': instrument, 'resource_type': 'price_bars', 'request_key': key})
    job = {'schema_version': 1, 'resource_type': 'price_bars', 'instrument_id': instrument,
           'source': 'yahoo', 'request_key': key, 'attempt': previous_attempts + 1,
           'range_start': datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
           'range_end': datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1),
           'created_at': started, 'finished_at': utcnow(), 'status': status, 'coverage': coverage}
    if errors:
        job['error'] = {'types': sorted(errors)}
    db.data_sync_jobs.insert_one(job)
    return {'ticker': ticker, 'status': status, 'stored': len(stored), 'missing_ranges': remaining,
            'errors': sorted(errors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--universe', choices=['sp500', 'nasdaq100', 'nasdaq100_sp500', 'russell3000', 'all_us'])
    group.add_argument('--tickers', nargs='+', help='US ticker symbols')
    args = parser.parse_args()
    try:
        members = pool(args.universe, args.tickers)
    except ValueError as exc:
        parser.error(str(exc))
    store = get_store()
    db = store.execute(lambda db: db, required=True)
    if 'uq_bar_revision' not in db.price_bars.index_information():
        parser.error('Install the MongoDB schema before backfilling')
    sessions = closed_sessions(utcnow())
    print(json.dumps({'start': sessions[0], 'end': sessions[-1], 'sessions': len(sessions),
                      'instruments': len(members), 'database': db.name}), flush=True)

    def sync(ticker):
        return sync_ticker(store, db, ticker, sessions, YFinanceClient(request_timeout=20).get_prices)

    counts = Counter()
    with ThreadPoolExecutor(max_workers=4) as workers:
        for result in workers.map(sync, members):
            print(json.dumps(result), flush=True)
            counts[result['status']] += 1
    print(json.dumps({'totals': counts}))
    return int(bool(counts['partial'] or counts['failed']))


if __name__ == '__main__':
    raise SystemExit(main())
