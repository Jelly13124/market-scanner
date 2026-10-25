"""Local API smoke with live Yahoo data, temporary SQL and zero model calls.

Run explicitly: python -m scripts.smoke_no_mongo. Never touches Docker MongoDB
or the project's SQL database. The generated report contains data-health and
missing-data sections only; it is not a live AI/model quality acceptance test.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix='market-scanner-no-mongo-') as folder:
        os.environ['MONGODB_URI'] = ''
        os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(folder) / 'smoke.db')
        os.environ['ENVIRONMENT'] = 'development'
        os.environ['RESEARCH_MODEL_PROVIDER'] = 'Ollama'
        os.environ['RESEARCH_MODEL_NAME'] = 'unused-no-model-calls'
        from fastapi.testclient import TestClient
        from app.backend.main import app, _scheduler_service
        from app.backend.auth.dependencies import get_current_user
        from app.backend.database import SessionLocal, engine
        from app.backend.database.models import User, ResearchReport
        from src.storage.mongo import get_store
        with SessionLocal() as db:
            user = User(id=1, email='smoke@example.invalid', is_active=True)
            db.add(user)
            db.commit()
        app.dependency_overrides[get_current_user] = lambda: User(id=1, email='smoke@example.invalid', is_active=True)
        try:
            with patch.object(_scheduler_service, 'start'), TestClient(app) as client:
                assert client.get('/health').status_code == 200
                retired = client.post('/pipeline/run', json={})
                assert retired.status_code == 410
                response = client.post('/research/analyze', json={
                    'ticker': 'SPY', 'included_sections': ['data_health', 'missing_data']})
                response.raise_for_status()
                report = response.json()
                assert report['storage_status'] == 'unconfigured'
                assert report['usage']['calls'] == 0
                assert report['sections']['data_health']['skipped'] is False
                assert get_store()._client is None
                with SessionLocal() as db:
                    assert db.query(ResearchReport).count() == 1
                print(json.dumps({'health': 'ok', 'analyze_http': response.status_code,
                    'storage': report['storage_status'], 'model_calls': report['usage']['calls'],
                    'sql_reports': 1, 'legacy_pipeline_http': retired.status_code,
                    'mongodb_connected': False, 'live_model_acceptance': 'not_run'}))
        finally:
            app.dependency_overrides.clear()
            engine.dispose()


if __name__ == '__main__':
    main()
