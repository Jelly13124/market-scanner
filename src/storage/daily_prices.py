"""Revisioned US daily bars shared by the read-through client and history seed."""
from datetime import date, datetime, time, timezone
from functools import cache
from zoneinfo import ZoneInfo

import exchange_calendars
from bson import Decimal128, Int64, ObjectId
from pymongo.errors import BulkWriteError

from src.storage.mongo import digest


@cache
def calendar():
    return exchange_calendars.get_calendar('XNYS')


def observed_after_close(session, fetched_at):
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    # Every US regular session closes on the same UTC date.
    day = fetched_at.date().isoformat()
    return day > session or (day == session and fetched_at >= calendar().session_close(session))


def save_price_bars(db, instrument, raw, now):
    """Append changed US daily bars to the common Yahoo revision history."""
    try:
        _append_bars(db, instrument, raw, now)
    except BulkWriteError as exc:
        # A live request and the seed may allocate the same next revision.
        errors = exc.details['writeErrors']
        if not errors or exc.details.get('writeConcernErrors') or any(e['code'] != 11000 for e in errors):
            raise
        collided = {e['op']['session_date'] for e in errors}
        _append_bars(db, instrument, [bar for bar in raw if bar['time'][:10] in collided], now)


def _append_bars(db, instrument, raw, now):
    rows = db.price_bars.find({'instrument_id': instrument, 'source': 'yahoo', 'interval': '1d',
        'session_date': {'$in': [bar['time'][:10] for bar in raw]}}).sort('revision', -1)
    latest = {}
    for row in rows:
        latest.setdefault(row['session_date'], row)
    documents = []
    confirmed = []
    for bar in raw:
        session = bar['time'][:10]
        previous = latest.get(session)
        content = digest(bar)
        if previous and previous['content_hash'] == content:
            if not observed_after_close(session, previous['fetched_at']):
                confirmed.append(previous['_id'])
            continue
        document = {'_id': ObjectId(), 'schema_version': 1, 'instrument_id': instrument,
            'source': 'yahoo', 'interval': '1d', 'session_date': session,
            'revision': previous['revision'] + 1 if previous else 1,
            'bar_time': datetime.combine(date.fromisoformat(session), time(9, 30),
                                         ZoneInfo('America/New_York')).astimezone(timezone.utc),
            'volume': Int64(bar['volume']), 'adjustment_policy': 'raw_ohlc_separate_adjusted_close',
            'content_hash': content, 'fetched_at': now, 'first_seen_at': now}
        for name in ('open', 'high', 'low', 'close', 'adjusted_close', 'dividend', 'split_ratio'):
            if bar.get(name) is not None:
                document[name] = Decimal128(str(bar[name]))
        documents.append(document)
        latest[session] = document
    if confirmed:
        db.price_bars.update_many({'_id': {'$in': confirmed}}, {'$max': {'fetched_at': now}})
    if documents:
        db.price_bars.insert_many(documents, ordered=False)
