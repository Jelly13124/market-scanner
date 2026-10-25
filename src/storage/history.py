"""Immutable datasets and full-universe scan publication."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from src.storage.mongo import get_store, digest, json_value, utcnow


def freeze_dataset(db, store, *, owner_id, ticker, as_of, evidence, features=None, quality=None):
    from bson import ObjectId
    manifest = sorted(({'collection': ref['collection'], 'document_id': ref['id'], 'content_hash': ref['content_hash']}
                       for ref in evidence), key=lambda r: (r['collection'], str(r['document_id'])))
    key = digest({'ticker': ticker, 'as_of': as_of.isoformat(), 'manifest': [str(r) for r in manifest],
                  'features': features or {}, 'quality': quality or {}})
    identity = {'owner_id': str(owner_id), 'dataset_hash': key}
    doc = dict(identity, _id=ObjectId(), schema_version=1, instrument_id=store.instrument(ticker, db),
        as_of=as_of, knowledge_mode='live_observed', manifest=manifest, features=json_value(features or {}),
        quality=json_value(quality or {}), created_at=utcnow())
    db.datasets.update_one(identity, {'$setOnInsert': doc}, upsert=True)
    return db.datasets.find_one(identity)['_id']


class ScanHistory:
    def __init__(self, store=None):
        self.store = store if store is not None else get_store()

    def save(self, *, execution_key, owner_id, config_id, config, scan_date, universe, outcomes, trigger_type='manual'):
        universe = list(dict.fromkeys(universe))
        by_ticker = {row.ticker: row for row in outcomes}
        def save(db):
            if len(by_ticker) != len(outcomes) or set(by_ticker) != set(universe):
                raise ValueError('Full-universe history requires exactly one outcome per ticker')
            from bson import ObjectId
            now = utcnow()
            as_of = datetime.fromisoformat(scan_date).replace(tzinfo=timezone.utc)
            identity = {'execution_key': execution_key}
            existing = db.scan_runs.find_one(identity)
            if existing is not None:
                if existing['owner_id'] != str(owner_id):
                    raise ValueError('Scan owner mismatch')
                return {'status': existing['status'], 'scan_run_id': str(existing['_id']), 'reused': True}
            run_id = ObjectId()
            versions = {'scanner': 'full-universe-v1', 'schema': '2.3'}
            run = dict(identity, _id=run_id, schema_version=1, owner_id=str(owner_id), config_id=str(config_id),
                config_snapshot=json_value(config), scan_date=scan_date, market='US', timezone='America/New_York',
                trigger_type=trigger_type, as_of=as_of, status='running', universe_manifest=universe,
                universe_hash=digest(universe), coverage_mode='full_universe', expected_count=len(universe),
                counts={}, versions=versions, attempt=1, created_at=now)
            db.scan_runs.insert_one(run)
            counts = Counter()
            partial = False
            try:
                for ticker in universe:
                    outcome = by_ticker[ticker]
                    names = [r['detector'] for r in outcome.detector_results]
                    if len(set(names)) != len(names):
                        raise ValueError('Duplicate detector outcome')
                    entry = outcome.entry
                    document = {'_id': ObjectId(), 'schema_version': 1, 'scan_run_id': run_id,
                        'instrument_id': self.store.instrument(ticker, db), 'owner_id': str(owner_id),
                        'outcome': outcome.outcome, 'selected': outcome.selected,
                        'detector_results': outcome.detector_results, 'quality': json_value(outcome.quality), 'created_at': now}
                    if outcome.outcome == 'evaluated':
                        document['dataset_id'] = freeze_dataset(db, self.store, owner_id=owner_id, ticker=ticker,
                            as_of=as_of, evidence=outcome.evidence, quality=outcome.quality)
                    if entry is not None:
                        for key in ('rank', 'composite_score', 'event_score', 'quant_score', 'event_severity', 'direction'):
                            value = getattr(entry, key)
                            if value is not None and (key != 'rank' or value > 0):
                                document[key] = value
                    db.scan_results.insert_one(document)
                    counts[outcome.outcome] += 1
                    counts['selected'] += int(outcome.selected)
                    partial |= outcome.outcome != 'evaluated' or outcome.quality.get('partial', False)
                if db.scan_results.count_documents({'scan_run_id': run_id}) != len(universe):
                    raise ValueError('Scan publication coverage mismatch')
                status = 'partial' if partial else 'succeeded'
                db.scan_runs.update_one({'_id': run_id, 'status': 'running'}, {'$set': {
                    'status': status, 'counts': dict(counts), 'finished_at': utcnow()}})
                return {'status': status, 'scan_run_id': str(run_id)}
            except Exception:
                db.scan_runs.update_one({'_id': run_id, 'status': 'running'}, {'$set': {
                    'status': 'failed', 'counts': dict(counts), 'finished_at': utcnow(),
                    'error': {'code': 'history_write_failed'}}})
                raise
        return self.store.execute(save) or {'status': self.store.status, 'persisted': False}

    def list_runs(self, owner_id, limit=50):
        return self.store.execute(lambda db: list(db.scan_runs.find({'owner_id': str(owner_id),
            'status': {'$in': ['succeeded', 'partial']}}).sort('created_at', -1).limit(min(200, max(1, limit))))) or []

    def results(self, owner_id, run_id):
        from bson import ObjectId
        def read(db):
            run = db.scan_runs.find_one({'_id': ObjectId(run_id), 'owner_id': str(owner_id),
                                        'status': {'$in': ['succeeded', 'partial']}})
            return list(db.scan_results.find({'scan_run_id': run['_id'], 'owner_id': str(owner_id)})) if run else []
        return self.store.execute(read) or []
