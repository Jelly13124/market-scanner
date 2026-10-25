"""Owner-scoped immutable analysis reports; SQL remains a rollback mirror."""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone
from src.storage.mongo import get_store, digest, json_value, utcnow
from src.storage.history import freeze_dataset


def versions():
    root = Path(__file__).resolve().parents[1] / 'research'
    files = sorted([*root.rglob('*.md'), *root.rglob('*.py')])
    return {'graph': 'analyze-v1', 'schema': '2.3', 'renderer': 'sop-v1',
        'code': digest({str(f.relative_to(root)): f.read_text() for f in files}),
        'model': os.getenv('RESEARCH_MODEL_NAME', 'deepseek-chat'),
        'provider': os.getenv('RESEARCH_MODEL_PROVIDER', 'DeepSeek')}


class AnalysisHistory:
    def __init__(self, store=None):
        self.store = store if store is not None else get_store()

    def start(self, *, owner_id, request, shared, force=False, source_scan_result_id=None, model_route=None):
        if owner_id is None:
            return None
        def start(db):
            from bson import ObjectId
            owner = str(owner_id)
            instrument = self.store.instrument(request.ticker, db)
            if source_scan_result_id:
                source = db.scan_results.find_one({'_id': ObjectId(source_scan_result_id), 'owner_id': owner,
                                                   'instrument_id': instrument})
                if source is None:
                    raise ValueError('Unknown or unauthorized source scan result')
            as_of = datetime.fromisoformat(shared.scan_date).replace(tzinfo=timezone.utc)
            # Feature hash includes actual values, not just ticker/date. This
            # remains exact when online inputs could not be cached separately.
            features = json_value(shared)
            features.pop('storage_status', None)
            dataset = freeze_dataset(db, self.store, owner_id=owner, ticker=request.ticker, as_of=as_of,
                evidence=shared.evidence, features=features, quality={'inputs': shared.quality})
            v = dict(versions(), **(model_route or {}))
            key = digest({'request': json_value(request), 'dataset_id': str(dataset), 'versions': v})
            existing = None if force else db.reports.find_one({'owner_id': owner, 'request_hash': key, 'provenance': 'native', 'versions.result_status': 'succeeded'})
            if existing and existing.get('versions', {}).get('sections_in_artifact'):
                from gridfs import GridFS
                import json
                artifact = next(a for a in existing['artifacts'] if a['mime'] == 'application/json')
                existing['sections'] = json.loads(GridFS(db).get(artifact['file_id']).read())
            run_id = ObjectId()
            doc = {'_id': run_id, 'schema_version': 1, 'owner_id': owner, 'instrument_id': instrument,
                'dataset_id': dataset, 'request': json_value(request), 'run_key': key,
                'thread_id': f'{owner}:{run_id}', 'versions': v, 'status': 'running', 'usage': {}, 'created_at': utcnow()}
            if source_scan_result_id:
                doc['source_scan_result_id'] = ObjectId(source_scan_result_id)
            if existing:
                doc.update(status='succeeded', cached_from_report_id=existing['_id'], finished_at=utcnow())
            db.analysis_runs.insert_one(doc)
            return {'run': doc, 'cached': existing}
        ticket = self.store.execute(start)
        if source_scan_result_id and ticket is None:
            raise ValueError("Cannot verify source scan result without MongoDB")
        return ticket

    def save(self, ticket, report, *, error=None):
        if ticket is None:
            return None
        run = ticket['run']
        def save(db):
            from bson import ObjectId
            if error:
                db.analysis_runs.update_one({'_id': run['_id'], 'owner_id': run['owner_id']}, {'$set': {
                    'status': 'failed', 'error': {'code': type(error).__name__}, 'finished_at': utcnow()}})
                return None
            sections = {k: json_value(v) for k, v in report['sections'].items()}
            partial = any(p.skipped and p.skip_reason != 'user excluded this section'
                          for name, p in report['sections'].items() if not name.startswith('_'))
            doc = {'_id': ObjectId(), 'schema_version': 1, 'owner_id': run['owner_id'],
                'instrument_id': run['instrument_id'], 'run_id': run['_id'], 'dataset_id': run['dataset_id'],
                'provenance': 'native', 'request_hash': run['run_key'], 'language': report['request'].report_language,
                'summary': sections.get('executive_summary', {}).get('markdown', ''), 'sections': sections,
                'backtest': json_value(report.get('backtest')) or {}, 'artifacts': [], 'versions': run['versions'],
                'created_at': utcnow()}
            doc['versions'] = dict(run['versions'], result_status='partial' if partial else 'succeeded')
            from gridfs import GridFS
            from bson import Int64, BSON
            import hashlib, json
            from src.research.html_render import render_sop
            fs = GridFS(db)
            def artifact(data, mime):
                file_id = fs.put(data, content_type=mime)
                return {'file_id': file_id, 'mime': mime, 'bytes': Int64(len(data)),
                        'sha256': hashlib.sha256(data).hexdigest(), 'renderer_version': 'sop-v1'}
            if len(BSON.encode(doc)) > 8_000_000:
                data = json.dumps(doc['sections'], ensure_ascii=False).encode()
                doc['artifacts'].append(artifact(data, 'application/json'))
                doc['sections'] = {}
                doc['versions']['sections_in_artifact'] = True
            html = report.get('rendered_html') or render_sop(report)
            doc['artifacts'].append(artifact(html.encode(), 'text/html'))
            db.reports.insert_one(doc)
            db.analysis_runs.update_one({'_id': run['_id'], 'owner_id': run['owner_id'], 'status': 'running'}, {'$set': {
                'status': 'partial' if partial else 'succeeded', 'finished_at': utcnow(),
                'usage': report.get('usage', {})}})
            return str(doc['_id'])
        return self.store.execute(save)

    def section_get(self, ticket, name, prior):
        if ticket is None:
            return None
        run = ticket['run']
        key = digest([run['run_key'], name, json_value(prior)])
        return self.store.execute(lambda db: db.llm_cache.find_one({'owner_id': run['owner_id'], 'cache_key': key,
                                                                   'expires_at': {'$gt': utcnow()}}))

    def section_put(self, ticket, name, prior, payload):
        if ticket is None or payload.skipped:
            return
        from datetime import timedelta
        run = ticket['run']
        key = digest([run['run_key'], name, json_value(prior)])
        def save(db):
            from bson import ObjectId
            now = utcnow()
            doc = {'_id': ObjectId(), 'schema_version': 1, 'owner_id': run['owner_id'], 'cache_key': key,
                'origin_run_id': run['_id'], 'node_name': name, 'input_hash': digest(json_value(prior)),
                'versions': run['versions'], 'output': json_value(payload), 'usage': {}, 'created_at': now,
                'expires_at': now + timedelta(seconds=max(1, int(os.getenv('LLM_CACHE_TTL_SECONDS', '86400'))))}
            new_id = doc.pop('_id')
            db.llm_cache.update_one({'owner_id': run['owner_id'], 'cache_key': key},
                {'$set': doc, '$setOnInsert': {'_id': new_id}}, upsert=True)
        self.store.execute(save)

    def resume(self, *, owner_id, request, run_id, model_route=None):
        from bson import ObjectId
        from src.research.shared_data import SharedData
        from v2.data import models
        if owner_id is None or not ObjectId.is_valid(run_id):
            raise ValueError('Unknown or unauthorized analysis run')
        def resume(db):
            run = db.analysis_runs.find_one({'_id': ObjectId(run_id), 'owner_id': str(owner_id)})
            if run is None or run['request'] != json_value(request):
                raise ValueError('Unknown or unauthorized analysis run')
            current = dict(versions(), **(model_route or {}))
            if any(run['versions'].get(k) != v for k, v in current.items()):
                raise ValueError('Checkpoint versions changed; start a fresh analysis')
            dataset = db.datasets.find_one({'_id': run['dataset_id'], 'owner_id': str(owner_id)})
            if dataset is None:
                raise ValueError('Checkpoint dataset is unavailable')
            data = dict(dataset['features'])
            fields = {'prices': (models.Price, True), 'financials': (models.FinancialMetrics, True),
                'insider_trades': (models.InsiderTrade, True), 'news': (models.CompanyNews, True),
                'analyst_actions': (models.AnalystAction, True), 'analyst_targets': (models.AnalystTarget, False),
                'earnings_history': (models.EarningsRecord, True), 'sector_etf_prices': (models.Price, True),
                'spy_prices': (models.Price, True), 'quote': (models.Quote, False)}
            for key, (model, many) in fields.items():
                value = data.get(key)
                if value is not None:
                    data[key] = [model.model_validate(v) for v in value] if many else model.model_validate(value)
            data['evidence'] = [{'collection': ref['collection'], 'id': ref['document_id'],
                                 'content_hash': ref['content_hash']} for ref in dataset['manifest']]
            report = db.reports.find_one({'run_id': run['_id'], 'owner_id': str(owner_id)})
            if report and report.get('versions', {}).get('sections_in_artifact'):
                from gridfs import GridFS
                import json
                artifact = next(a for a in report['artifacts'] if a['mime'] == 'application/json')
                report['sections'] = json.loads(GridFS(db).get(artifact['file_id']).read())
            if not report:
                db.analysis_runs.update_one({'_id': run['_id']}, {'$set': {'status': 'running'}})
            return {'run': run, 'cached': report}, SharedData(**data)
        result = self.store.execute(resume)
        if result is None:
            raise ValueError('Checkpoint storage is unavailable')
        return result
