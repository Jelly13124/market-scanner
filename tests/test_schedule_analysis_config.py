"""Scheduled Analyze must preserve the saved canvas, ownership and market."""
from unittest.mock import Mock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker
from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import Base, User
from app.backend.routes.report_schedules import router
from app.backend.services.scheduler_service import get_scheduler_service, _run_report_schedule_job


@pytest.fixture
def setup():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([User(id=1, email='one@example.com'), User(id=2, email='two@example.com')]); db.commit()
    app = FastAPI(); app.include_router(router)
    def session():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: User(id=1)
    app.dependency_overrides[get_scheduler_service] = lambda: Mock()
    with TestClient(app) as client:
        yield client, factory, app
    engine.dispose()


def test_snapshot_round_trip_and_worker_uses_same_config(setup):
    client, factory, app = setup
    config = {'market': 'cn', 'objective': 'long_term', 'position_budget_usd': 5000,
              'already_holds': True, 'cost_basis_usd': 42, 'risk_tolerance': 'conservative',
              'included_sections': ['valuation', 'debate'], 'use_personas': True,
              'persona_overrides': {'valuation': 'buffett'}, 'debate_rounds': 4}
    response = client.post('/report-schedules/', json={'tickers': ['600519.SH'], 'cron_expr': '30 9 * * 1-5', 'report_language': 'zh', 'analysis_config': config})
    assert response.status_code == 201, response.text
    schedule = response.json()
    assert all(schedule['analysis_config'][key] == value for key, value in config.items())
    assert client.patch(f"/report-schedules/{schedule['id']}", json={'is_enabled': True}).json()['analysis_config'] == schedule['analysis_config']
    with patch('app.backend.services.scheduler_service.SessionLocal', factory), \
         patch('app.backend.services.report_delivery.verified_recipients', return_value=[Mock()]), \
         patch('app.backend.services.report_delivery.email_report_html', return_value={'sent': [], 'failed': []}), \
         patch('app.backend.services.api_key_service.ApiKeyService.get_api_keys_dict', return_value={}), \
         patch('src.research.html_render.render_sop', return_value='<html/>'), \
         patch('src.research.sop_orchestrator.run_sop') as run:
        _run_report_schedule_job(schedule['id'])
    request = run.call_args.args[0]
    assert request.ticker == '600519.SH'
    assert request.market == 'cn' and request.report_language == 'zh'
    assert request.included_sections == set(config['included_sections'])
    for key in ['objective', 'position_budget_usd', 'already_holds', 'cost_basis_usd', 'risk_tolerance', 'use_personas', 'persona_overrides', 'debate_rounds']:
        assert getattr(request, key) == config[key]
    assert run.call_args.kwargs['owner_id'] == 1
    app.dependency_overrides[get_current_user] = lambda: User(id=2)
    assert client.get('/report-schedules/').json() == []
    assert client.patch(f"/report-schedules/{schedule['id']}", json={'analysis_config': config}).status_code == 404


def test_empty_schedule_sections_rejected(setup):
    client, _, _ = setup
    assert client.post('/report-schedules/', json={'tickers': ['AAPL'], 'cron_expr': '30 9 * * *', 'analysis_config': {'included_sections': []}}).status_code == 422


def test_legacy_schedule_keeps_default_report_behavior(setup):
    client, factory, _ = setup
    created = client.post('/report-schedules/', json={'tickers': ['AAPL'], 'cron_expr': '30 9 * * *'}).json()
    assert created['analysis_config'] is None
    with patch('app.backend.services.scheduler_service.SessionLocal', factory), \
         patch('app.backend.services.report_delivery.verified_recipients', return_value=[Mock()]), \
         patch('app.backend.services.report_delivery.email_report_html', return_value={'sent': [], 'failed': []}), \
         patch('app.backend.services.api_key_service.ApiKeyService.get_api_keys_dict', return_value={}), \
         patch('src.research.html_render.render_sop', return_value='<html/>'), \
         patch('src.research.sop_orchestrator.run_sop') as run:
        _run_report_schedule_job(created['id'])
    from src.research.models import SECTION_ORDER
    request = run.call_args.args[0]
    assert request.market == 'us'
    assert request.included_sections == set(SECTION_ORDER)
    assert request.use_personas is False
    assert request.debate_rounds == 1


def test_schedule_migration_preserves_existing_rows():
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    migration = import_module('app.backend.alembic.versions.d7e3f901b625_report_schedule_analysis_config')
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE report_schedules (id INTEGER PRIMARY KEY, cron_expr TEXT)'))
        connection.execute(text("INSERT INTO report_schedules VALUES (1, '30 9 * * *')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text('SELECT cron_expr, analysis_config FROM report_schedules')).one() == ('30 9 * * *', None)
            migration.downgrade()
        assert 'analysis_config' not in {col['name'] for col in inspect(connection).get_columns('report_schedules')}
    engine.dispose()
