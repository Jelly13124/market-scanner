"""Idempotent SQL history copy; never deletes or changes SQL rows."""
from __future__ import annotations

from datetime import datetime, timezone
from src.storage.mongo import get_store, digest, json_value, utcnow


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def migrate(session, *, store=None, apply=False):
    from app.backend.database.models import ResearchReport, ResearchTradePlan, ScanRun, ScannerConfig, WatchlistEntry
    from bson import ObjectId
    store = store if store is not None else get_store()
    stats = {'reports': 0, 'scan_runs': 0, 'scan_results': 0, 'unowned_skipped': 0, 'native_mirrors_skipped': 0}
    for row in session.query(ResearchReport).order_by(ResearchReport.id):
        if row.user_id is None:
            stats['unowned_skipped'] += 1
            continue
        native_id = (row.analyze_request_json or {}).get('mongo_report_id')
        if native_id and ObjectId.is_valid(native_id):
            native = store.execute(lambda database: database.reports.find_one({'_id': ObjectId(native_id), 'owner_id': str(row.user_id)}))
            if native:
                stats['native_mirrors_skipped'] += 1
                continue
        stats['reports'] += 1
        if not apply:
            continue
        def report(db):
            identity = {'legacy_sql_id': f'research_reports:{row.id}'}
            if db.reports.find_one(identity):
                return
            sections = dict(row.sections_json or {})
            sections['_legacy'] = {'request': row.request_json, 'analyze_request': row.analyze_request_json,
                'markdown': row.report_markdown, 'persona_assignments': row.persona_assignments_json}
            artifacts = []
            if row.rendered_html:
                from gridfs import GridFS
                from bson import Int64
                data = row.rendered_html.encode()
                import hashlib
                file_id = GridFS(db).put(data, content_type='text/html')
                artifacts = [{'file_id': file_id, 'mime': 'text/html', 'bytes': Int64(len(data)),
                              'sha256': hashlib.sha256(data).hexdigest(), 'renderer_version': 'legacy_sql'}]
            plan = session.query(ResearchTradePlan).filter(ResearchTradePlan.report_id == row.id).first()
            plan_values = {column.name: getattr(plan, column.name) for column in plan.__table__.columns
                           if column.name not in ('id', 'report_id', 'created_at')} if plan else {}
            db.reports.insert_one(dict(identity, _id=ObjectId(), schema_version=1, owner_id=str(row.user_id),
                instrument_id=store.instrument(row.ticker, db), provenance='legacy_unverified',
                request_hash=digest(row.request_json), language=(row.analyze_request_json or {}).get('report_language', 'en'),
                summary=row.report_markdown, sections=sections, artifacts=artifacts,
                trade_plan={k:v for k,v in plan_values.items() if not k.startswith('backtest_')},
                backtest={k:v for k,v in plan_values.items() if k.startswith('backtest_')},
                versions={'legacy': True}, created_at=aware(row.created_at), migrated_at=utcnow()))
        store.execute(report, required=True)
    for row in session.query(ScanRun).order_by(ScanRun.id):
        config = session.get(ScannerConfig, row.config_id)
        if config is None or config.user_id is None:
            stats['unowned_skipped'] += 1
            continue
        entries = session.query(WatchlistEntry).filter(WatchlistEntry.scan_run_id == row.id).all()
        stats['scan_runs'] += 1
        stats['scan_results'] += len(entries)
        if not apply:
            continue
        def scan(db):
            identity = {'legacy_sql_id': f'scan_runs:{row.id}'}
            existing = db.scan_runs.find_one(identity)
            if existing and existing['status'] != 'running':
                return
            run_id = existing['_id'] if existing else ObjectId()
            created = aware(row.created_at)
            # The current mutable ScannerConfig cannot reconstruct old weights.
            document = dict(identity, _id=run_id, schema_version=1, owner_id=str(config.user_id),
                execution_key=identity['legacy_sql_id'], config_id=str(row.config_id),
                config_snapshot={'legacy_config_id': row.config_id, 'original_config_unavailable': True},
                scan_date=created.date().isoformat(), market='US', timezone='America/New_York', trigger_type='migration',
                as_of=created, status='running', universe_manifest=[e.ticker for e in entries],
                universe_hash=digest([e.ticker for e in entries]), coverage_mode='legacy_topn_only',
                expected_count=len(entries), counts={}, versions={'legacy': True}, attempt=1, created_at=created)
            db.scan_runs.update_one(identity, {'$setOnInsert': document}, upsert=True)
            for entry in entries:
                instrument = store.instrument(entry.ticker, db)
                doc = {'_id': ObjectId(), 'schema_version': 1, 'scan_run_id': run_id, 'instrument_id': instrument,
                    'owner_id': str(config.user_id), 'outcome': 'evaluated', 'selected': True,
                    'detector_results': [], 'quality': {'legacy_topn_only': True, 'legacy_triggers': entry.triggers},
                    'created_at': created, 'rank': entry.rank, 'composite_score': float(entry.composite_score),
                    'event_score': float(entry.event_score), 'event_severity': float(entry.event_severity or 0),
                    'direction': entry.direction}
                db.scan_results.update_one({'scan_run_id': run_id, 'instrument_id': instrument}, {'$setOnInsert': doc}, upsert=True)
            db.scan_runs.update_one({'_id': run_id}, {'$set': {'status': 'partial', 'counts': {'legacy_topn': len(entries)},
                                                           'finished_at': aware(row.completed_at or row.created_at)}})
        store.execute(scan, required=True)
    return stats
