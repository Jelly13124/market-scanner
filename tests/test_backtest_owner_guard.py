"""Backtest strategies may only resolve the acting user's own watchlists."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker
from app.backend.database import get_db
from app.backend.database.models import Base, User, UserWatchlist, Strategy
from app.backend.auth.security import create_access_token
from app.backend.routes.lab import router, _scaffold_spec


@pytest.fixture
def harness():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([User(id=1, email='bt1@example.com'), User(id=2, email='bt2@example.com')]); db.commit()
        watch = UserWatchlist(user_id=2, name='other-private', tickers=['AAPL'])
        db.add(watch); db.commit(); wid = watch.id
    app = FastAPI(); app.include_router(router)
    def session():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app, headers={'Authorization': 'Bearer ' + create_access_token(1)}) as client:
        yield client, factory, wid
    engine.dispose()


def test_create_and_update_cannot_reference_other_owner_watchlist(harness):
    client, _, wid = harness
    spec = _scaffold_spec('private'); spec['universe'] = {'kind': 'watchlist', 'watchlist_id': wid}
    assert client.post('/lab/strategies', json={'name': 'bad', 'initial_spec_json': spec}).status_code == 404
    created = client.post('/lab/strategies', json={'name': 'valid'}).json()
    assert client.patch(f"/lab/strategies/{created['id']}", json={'spec_json': spec}).status_code == 404


def test_run_rechecks_ownership_for_old_stored_strategies(harness):
    client, factory, wid = harness
    spec = _scaffold_spec('legacy'); spec['universe'] = {'kind': 'watchlist', 'watchlist_id': wid}
    with factory() as db:
        row = Strategy(user_id=1, name='legacy-invalid', spec_json=spec, version=1)
        db.add(row); db.commit(); sid = row.id
    assert client.post(f'/lab/strategies/{sid}/backtest', json={}).status_code == 404
