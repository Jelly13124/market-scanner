"""Mongo-first read-through adapter for public market evidence.

Responses are immutable, typed snapshots with exact request keys and bounded
freshness. Quotes bypass persistence. Failed/empty responses are not cached.
MongoDB failures affect durability, not the online provider's result.
"""
from __future__ import annotations

import inspect
import logging
import os
from datetime import timedelta

from src.storage.mongo import digest, get_store, json_value, utcnow
from v2.data import models

logger = logging.getLogger(__name__)
_TYPES = {
    'get_statement_bundle': (None, False),
    'get_prices': (models.Price, True), 'get_news': (models.CompanyNews, True),
    'get_insider_trades': (models.InsiderTrade, True), 'get_financial_metrics': (models.FinancialMetrics, True),
    'get_company_facts': (models.CompanyFacts, False), 'get_earnings': (models.Earnings, False),
    'get_earnings_history': (models.EarningsRecord, True), 'get_earnings_calendar': (models.EarningsCalendarEntry, True),
    'get_analyst_targets': (models.AnalystTarget, False), 'get_analyst_actions': (models.AnalystAction, True),
    'get_estimate_revisions': (models.EstimateRevisions, False), 'get_market_cap': (None, False),
}


class CachedDataClient:
    def __init__(self, backend, *, store=None, source='hybrid'):
        self.backend = backend
        self.store = store if store is not None else get_store()
        self.source = source
        self.evidence = []
        self.quality = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.backend.close()

    def __getattr__(self, method):
        fn = getattr(self.backend, method)
        if method not in _TYPES:
            return fn
        def read(*args, **kwargs):
            # Signature binding normalizes positional/keyword calls and defaults.
            bound = inspect.signature(fn).bind(*args, **kwargs)
            bound.apply_defaults()
            request = json_value(dict(bound.arguments))
            key = digest({'source': self.source, 'method': method, 'request': request, 'schema': 1})
            now = utcnow()
            hit = self.store.execute(lambda db: db.company_snapshots.find_one({
                'snapshot_kind': 'provider_response', 'payload.request_key': key,
                'payload.expires_at': {'$gt': now}}, sort=[('observed_at', -1)]))
            model, many = _TYPES[method]
            if hit is not None:
                try:
                    raw = hit['payload']['result']
                    result = [model.model_validate(v) for v in raw] if many else (model.model_validate(raw) if model else raw)
                    self.evidence.append({'collection': 'company_snapshots', 'id': hit['_id'], 'content_hash': hit['content_hash']})
                    return result
                except (KeyError, TypeError, ValueError):
                    self.quality.append({'method': method, 'status': 'invalid_cache'})
            if method == 'get_prices' and self.source == 'hybrid':
                stored = self._read_prices(request, now)
                if stored is not None:
                    return stored
            result = fn(*args, **kwargs)
            slots = {'get_news': '_news', 'get_financial_metrics': '_metrics', 'get_company_facts': '_facts',
                     'get_insider_trades': '_insider', 'get_earnings_calendar': '_calendar'}
            provider = getattr(self.backend, slots.get(method, '_prices'), self.backend)
            self.quality.append({'method': method, 'status': 'online', 'cache_storage': self.store.status,
                                 'provider_status': getattr(provider, 'last_status', 'returned')})
            if result is None or result == [] or result == {}:
                return result
            raw = json_value(result)
            ttl = max(1, int(os.getenv('MARKET_CACHE_TTL_SECONDS', '900')))
            def save(db):
                from bson import ObjectId
                instrument = self.store.instrument(request.get('ticker', '__MARKET__'), db)
                content = digest(raw)
                document = {'_id': ObjectId(), 'schema_version': 1, 'instrument_id': instrument,
                    'source': self.source, 'snapshot_kind': 'provider_response', 'observed_at': now,
                    'payload': {'method': method, 'request': request, 'request_key': key, 'result': raw,
                                'expires_at': now + timedelta(seconds=ttl)}, 'content_hash': content}
                db.company_snapshots.insert_one(document)
                if self.source == 'hybrid' and not request.get('ticker', '').endswith(('.SH', '.SZ', '.BJ')):
                    self._save_prices(db, method, instrument, raw, now)
                self._save_domain(db, method, instrument, request, raw, now)
                if method == 'get_statement_bundle':
                    self._save_statements(db, instrument, request, raw, now)
                self._record_sync(db, method, instrument, request, raw, now, document['_id'], key)
                return {'collection': 'company_snapshots', 'id': document['_id'], 'content_hash': content}
            reference = self.store.execute(save)
            if reference:
                self.evidence.append(reference)
            else:
                self.quality.append({'method': method, 'status': 'not_persisted'})
            return result
        return read

    def _read_prices(self, request, now):
        # Validate session coverage before accepting overlapping cached bars.
        ticker = request['ticker'].upper()
        if ticker.endswith(('.SH', '.SZ', '.BJ')):
            return None
        try:
            import exchange_calendars as calendars
            calendar = calendars.get_calendar('XNYS')
            end = min(request['end_date'], now.date().isoformat())
            expected = {s.date().isoformat() for s in calendar.sessions_in_range(request['start_date'], end)}
        except Exception:
            return None
        if not expected:
            return []
        def read(db):
            instrument = db.instruments.find_one({'market': 'US', 'symbol': ticker})
            if not instrument:
                return None
            rows = db.price_bars.find({'instrument_id': instrument['_id'], 'source': 'yahoo', 'interval': '1d',
                'session_date': {'$gte': request['start_date'], '$lte': end}}).sort([('session_date', 1), ('revision', -1)])
            latest = {}
            for row in rows:
                latest.setdefault(row['session_date'], row)
            ttl = max(1, int(os.getenv('MARKET_CACHE_TTL_SECONDS', '900')))
            if not expected.issubset(latest):
                return None
            if any(latest[d]['fetched_at'] < now - timedelta(seconds=ttl) for d in expected):
                from datetime import datetime, timezone
                start_at = datetime.fromisoformat(request['start_date']).replace(tzinfo=timezone.utc)
                end_at = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1)
                confirmed = db.data_sync_jobs.find_one({'instrument_id': instrument['_id'], 'source': 'yahoo',
                    'resource_type': 'price_bars', 'status': 'succeeded', 'range_start': {'$lte': start_at},
                    'range_end': {'$gte': end_at}, 'finished_at': {'$gt': now - timedelta(seconds=ttl)}})
                if confirmed is None:
                    return None
            result, refs = [], []
            for day in sorted(expected):
                row = latest[day]
                values = {k: float(row[k].to_decimal()) for k in ('open','high','low','close','adjusted_close','dividend','split_ratio') if k in row}
                result.append(models.Price(**values, time=day, volume=row['volume']))
                refs.append({'collection': 'price_bars', 'id': row['_id'], 'content_hash': row['content_hash']})
            return result, refs
        found = self.store.execute(read)
        if found is None:
            return None
        result, refs = found
        self.evidence.extend(refs)
        return result

    @staticmethod
    def _save_prices(db, method, instrument, raw, now):
        if method != 'get_prices' or not raw:
            return
        from bson import ObjectId, Decimal128, Int64
        from datetime import datetime, timezone
        rows = db.price_bars.find({'instrument_id': instrument, 'source': 'yahoo', 'interval': '1d',
            'session_date': {'$in': [bar['time'][:10] for bar in raw]}}).sort('revision', -1)
        latest = {}
        for row in rows:
            latest.setdefault(row['session_date'], row)
        documents = []
        for bar in raw:
            session = bar['time'][:10]
            previous = latest.get(session)
            content = digest(bar)
            if previous and previous['content_hash'] == content:
                continue
            document = {'_id': ObjectId(), 'schema_version': 1, 'instrument_id': instrument,
                'source': 'yahoo', 'interval': '1d', 'session_date': session,
                'revision': previous['revision'] + 1 if previous else 1,
                'bar_time': datetime.fromisoformat(bar['time'].replace('Z', '+00:00')).replace(tzinfo=timezone.utc),
                'volume': Int64(bar['volume']), 'adjustment_policy': 'raw_ohlc_separate_adjusted_close',
                'content_hash': content, 'fetched_at': now, 'first_seen_at': now}
            for name in ('open', 'high', 'low', 'close', 'adjusted_close', 'dividend', 'split_ratio'):
                if bar.get(name) is not None:
                    document[name] = Decimal128(str(bar[name]))
            documents.append(document)
            latest[session] = document
        if documents:
            db.price_bars.insert_many(documents, ordered=False)

    @staticmethod
    def _save_statements(db, instrument, request, raw, now):
        from bson import ObjectId
        from datetime import datetime, timezone
        columns = sorted({c for table in raw.values() for c in table['columns']})
        for period_end in columns:
            payload = {}
            for name, table in raw.items():
                if period_end in table['columns']:
                    col = table['columns'].index(period_end)
                    payload[name] = {key: row[col] for key, row in zip(table['index'], table['data'])}
            identity = {'instrument_id': instrument, 'source': 'yahoo',
                'period_type': 'annual' if request['period'] == 'annual' else 'quarterly',
                'period_end': datetime.fromisoformat(period_end).replace(tzinfo=timezone.utc),
                'filing_key': 'yahoo-observed:' + request['period'] + ':' + period_end}
            content = digest(payload)
            latest = db.financial_statements.find_one(identity, sort=[('revision', -1)])
            if latest and latest['content_hash'] == content:
                continue
            db.financial_statements.insert_one(dict(identity, _id=ObjectId(), schema_version=1,
                revision=latest['revision'] + 1 if latest else 1, first_seen_at=now, currency='UNKNOWN',
                income_statement=payload.get('income', {}), balance_sheet=payload.get('balance', {}),
                cash_flow=payload.get('cashflow', {}), content_hash=content, pit_status='observed_only'))

    def _save_domain(self, db, method, instrument, request, raw, now):
        from bson import ObjectId
        from datetime import datetime, timezone
        def timestamp(value):
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            except (TypeError, ValueError):
                return None
        if method == 'get_news':
            for article in raw:
                published = timestamp(article.get('date'))
                if published is None:
                    continue  # keep unknown dates in the observed response snapshot
                identity = {'article_key': digest(article.get('url') or [article.get('source'), article['title'], article.get('date')])}
                content = digest(article)
                prior = db.news_articles.find_one(identity, sort=[('revision', -1)])
                if prior and prior['content_hash'] == content:
                    continue
                db.news_articles.insert_one(dict(identity, _id=ObjectId(), schema_version=1,
                    revision=prior['revision'] + 1 if prior else 1, provider=self.source, canonical_url=article.get('url') or '',
                    publisher=article.get('source') or '', headline=article['title'], summary='', language='unknown',
                    instrument_ids=[instrument], published_at=published, first_seen_at=now, fetched_at=now,
                    content_hash=content, content_policy='metadata_summary'))
        event_types = {'get_insider_trades': 'insider_trade', 'get_earnings_history': 'earnings_result',
                       'get_earnings_calendar': 'earnings_calendar', 'get_analyst_actions': 'analyst_rating'}
        if method in event_types:
            for event in raw:
                event_at = timestamp(event.get('filing_date') or event.get('date') or event.get('report_period'))
                if event_at is None:
                    continue
                event_instrument = self.store.instrument(event.get('ticker') or event.get('symbol') or request.get('ticker', '__MARKET__'), db)
                event_type = event_types[method]
                identity = {'instrument_id': event_instrument, 'source': self.source, 'event_type': event_type,
                    'event_key': digest([event_type, event_at.isoformat(), event.get('name'), event.get('firm'), event.get('url')])}
                content = digest(event)
                prior = db.corporate_events.find_one(identity, sort=[('revision', -1)])
                if prior and prior['content_hash'] == content:
                    continue
                db.corporate_events.insert_one(dict(identity, _id=ObjectId(), schema_version=1,
                    revision=prior['revision'] + 1 if prior else 1, event_at=event_at, first_seen_at=now,
                    status='scheduled' if event_type == 'earnings_calendar' else 'confirmed', payload=event, content_hash=content))

    def _record_sync(self, db, method, instrument, request, raw, now, snapshot_id, request_key):
        from bson import ObjectId
        from datetime import datetime, timezone
        resource = {'get_prices': 'price_bars', 'get_news': 'news_articles',
                    'get_statement_bundle': 'financial_statements', 'get_insider_trades': 'corporate_events',
                    'get_earnings_history': 'corporate_events', 'get_earnings_calendar': 'corporate_events',
                    'get_analyst_actions': 'corporate_events'}.get(method, 'company_snapshots')
        start = datetime.fromisoformat(request.get('start_date') or now.date().isoformat()).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(request.get('end_date') or now.date().isoformat()).replace(tzinfo=timezone.utc) + timedelta(days=1)
        count = len(raw) if isinstance(raw, list) else 1
        complete = resource == 'company_snapshots'
        coverage = {'returned_count': count, 'provider_window_verified': False}
        if method == 'get_prices' and self.source == 'hybrid' and not request.get('ticker', '').endswith(('.SH', '.SZ', '.BJ')):
            try:
                import exchange_calendars as calendars
                days = {s.date().isoformat() for s in calendars.get_calendar('XNYS').sessions_in_range(
                    request['start_date'], min(request['end_date'], now.date().isoformat()))}
                complete = days.issubset({row['time'][:10] for row in raw})
                coverage.update(expected_sessions=len(days), provider_window_verified=complete)
            except Exception:
                complete = False
        db.data_sync_jobs.insert_one({'_id': ObjectId(), 'schema_version': 1, 'resource_type': resource,
            'instrument_id': instrument, 'source': 'yahoo' if method in ('get_prices', 'get_statement_bundle') else self.source,
            'range_start': start, 'range_end': end, 'status': 'succeeded' if complete else 'partial',
            'attempt': 1, 'request_key': request_key, 'cursor': {'response_snapshot_id': snapshot_id},
            'coverage': coverage, 'created_at': now, 'finished_at': now})
