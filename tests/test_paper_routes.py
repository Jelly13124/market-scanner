"""User-owned paper trading: conservation, invalid orders and tenant isolation."""
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker
from app.backend.database import get_db
from app.backend.database.models import Base, User, PaperSleeve, PaperEquityMark
from app.backend.auth.security import create_access_token
from app.backend.routes.paper import router


@pytest.fixture
def harness():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([User(id=1, email='paper1@example.com'), User(id=2, email='paper2@example.com')])
        db.commit()
    app = FastAPI(); app.include_router(router)
    def session():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app, headers={'Authorization': 'Bearer ' + create_access_token(1)}) as client:
        yield client, factory
    engine.dispose()


def create(client, cash='1000', **kw):
    return client.post('/paper/account', json={'initial_cash': cash}, **kw)


def order(client, side='buy', quantity='1', price='100', ticker='AAPL', **kw):
    return client.post('/paper/orders', json=dict(ticker=ticker, side=side, quantity=quantity, price=price), **kw)


def number(value): return Decimal(str(value))


def test_regular_user_can_initialize_but_not_reset_account(harness):
    client, _ = harness
    assert client.get('/paper/account').json() is None
    assert create(client).status_code == 201
    assert create(client, '999999').status_code == 409
    account = client.get('/paper/performance').json()
    assert number(account['cash']) == 1000
    assert account['pricing_mode'] == 'manual_simulation'


def test_buy_partial_sell_and_final_sell_conserve_equity(harness):
    client, _ = harness
    create(client)
    buy = order(client, quantity='10').json()
    assert number(buy['cash']) == 0
    partial = order(client, side='sell', quantity='4', price='120').json()
    assert number(partial['realized_pnl']) == 80
    assert number(partial['unrealized_pnl']) == 120
    assert number(partial['equity']) == 1200
    assert number(partial['total_pnl']) == number(partial['realized_pnl']) + number(partial['unrealized_pnl'])
    final = order(client, side='sell', quantity='6', price='120').json()
    assert final['positions'] == []
    assert number(final['cash']) == 1200
    assert number(final['realized_pnl']) == 200
    assert len(final['trades']) == 3


def test_weighted_cost_and_fractional_shares(harness):
    client, _ = harness
    create(client)
    order(client, quantity='0.125', price='100')
    account = order(client, quantity='0.125', price='200').json()
    assert number(account['positions'][0]['average_cost']) == 150
    assert number(account['positions'][0]['quantity']) == Decimal('0.25')
    assert number(account['cash']) == Decimal('962.5')


def test_manual_mark_changes_valuation_without_creating_a_trade(harness):
    client, _ = harness
    create(client); order(client)
    r = client.post('/paper/marks', json={'ticker': 'aapl', 'price': '150'})
    assert r.status_code == 200
    assert number(r.json()['total_pnl']) == 50
    assert number(r.json()['realized_pnl']) == 0
    assert len(r.json()['trades']) == 1
    assert client.post('/paper/marks', json={'ticker': 'MSFT', 'price': '150'}).status_code == 404


def test_failed_orders_do_not_change_cash_or_ledger(harness):
    client, _ = harness
    create(client)
    assert order(client, quantity='11').status_code == 400
    assert order(client, side='sell').status_code == 400
    assert order(client, quantity='0.000001', price='0.000001').status_code == 400
    state = client.get('/paper/account').json()
    assert number(state['cash']) == 1000
    assert state['trades'] == []


@pytest.mark.parametrize('field,value', [('quantity','0'),('quantity','-1'),('price','0'),('price','NaN'),('price','Infinity'),('ticker','../AAPL'),('quantity','0.0000001')])
def test_invalid_orders_rejected(harness, field, value):
    client, _ = harness
    create(client)
    body=dict(side='buy', ticker='AAPL', quantity='1', price='100'); body[field]=value
    assert client.post('/paper/orders', json=body).status_code == 422


def test_tenants_never_share_accounts_positions_or_trades(harness):
    client, _ = harness
    create(client); order(client)
    other = {'Authorization': 'Bearer ' + create_access_token(2)}
    assert client.get('/paper/account', headers=other).json() is None
    assert order(client, side='sell', headers=other).status_code == 409
    assert create(client, '2000', headers=other).status_code == 201
    state = client.get('/paper/account', headers=other).json()
    assert state['positions'] == [] and state['trades'] == []
    assert number(state['cash']) == 2000
    assert number(client.get('/paper/account').json()['cash']) == 900


def test_legacy_global_book_is_not_exposed(harness):
    client, factory = harness
    with factory() as db:
        sleeve = PaperSleeve(name='private-host-book', starting_cash=100000)
        db.add(sleeve); db.flush()
        db.add(PaperEquityMark(sleeve_id=sleeve.id, date='2026-01-01', equity=123456))
        db.commit()
    assert client.get('/paper/performance').json() is None
    assert client.get('/paper/equity-chart.png').status_code == 404
    client.headers.pop('Authorization')
    assert client.get('/paper/account').status_code == 401
    assert create(client).status_code == 401
