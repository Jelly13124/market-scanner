"""Owner-isolated virtual USD account with atomic, decimal-valued fills."""
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.backend.database.models import UserPaperAccount, UserPaperPosition, UserPaperTrade

UNIT = Decimal("0.000001")


def money(value):
    return Decimal(value).quantize(UNIT)


def account_for(db: Session, user_id: int, *, lock=False):
    query = db.query(UserPaperAccount).filter(UserPaperAccount.user_id == user_id)
    return (query.with_for_update() if lock else query).first()


def snapshot(db: Session, user_id: int):
    # Serialize PostgreSQL reads with fills/marks for one coherent account view.
    account = account_for(db, user_id, lock=True)
    if account is None:
        return None
    positions = db.query(UserPaperPosition).filter(UserPaperPosition.account_id == account.id).order_by(UserPaperPosition.ticker).all()
    trades = db.query(UserPaperTrade).filter(UserPaperTrade.account_id == account.id).order_by(UserPaperTrade.id.desc()).limit(200).all()
    holdings = []
    market_value = Decimal(0)
    unrealized = Decimal(0)
    for position in positions:
        value = money(position.quantity * position.last_price)
        pnl = value - position.cost_basis
        market_value += value
        unrealized += pnl
        holdings.append(dict(ticker=position.ticker, quantity=position.quantity,
            average_cost=money(position.cost_basis / position.quantity), last_price=position.last_price,
            market_value=value, unrealized_pnl=pnl, updated_at=position.updated_at))
    equity = account.cash + market_value
    return dict(currency="USD", pricing_mode="manual_simulation", initial_cash=account.initial_cash,
        cash=account.cash, market_value=market_value, equity=equity,
        realized_pnl=account.realized_pnl, unrealized_pnl=unrealized,
        total_pnl=equity-account.initial_cash, positions=holdings,
        trades=[dict(id=t.id, ticker=t.ticker, side=t.side, quantity=t.quantity,
            price=t.price, notional=t.notional, realized_pnl=t.realized_pnl,
            cash_after=t.cash_after, created_at=t.created_at) for t in trades])


def fill(db: Session, user_id: int, order):
    account = account_for(db, user_id, lock=True)
    if account is None:
        raise HTTPException(409, "Create your paper account first")
    position = db.query(UserPaperPosition).filter(UserPaperPosition.account_id == account.id, UserPaperPosition.ticker == order.ticker).first()
    notional = money(order.quantity * order.price)
    if notional < UNIT:
        raise HTTPException(400, "Simulated order value is below account precision")
    realized = Decimal(0)
    if order.side == "buy":
        if account.cash < notional:
            raise HTTPException(400, "Insufficient virtual cash")
        if position is None:
            position = UserPaperPosition(account_id=account.id, ticker=order.ticker, quantity=0, cost_basis=0, last_price=order.price)
            db.add(position)
        position.quantity += order.quantity
        position.cost_basis += notional
        position.last_price = order.price
        account.cash -= notional
    else:
        if position is None or position.quantity < order.quantity:
            raise HTTPException(400, "Insufficient shares; short selling is not supported")
        released = position.cost_basis if position.quantity == order.quantity else money(position.cost_basis * order.quantity / position.quantity)
        realized = notional - released
        position.quantity -= order.quantity
        position.cost_basis -= released
        position.last_price = order.price
        account.cash += notional
        account.realized_pnl += realized
        if position.quantity == 0:
            db.delete(position)
    db.add(UserPaperTrade(account_id=account.id, ticker=order.ticker, side=order.side,
        quantity=order.quantity, price=order.price, notional=notional,
        realized_pnl=realized, cash_after=account.cash))
    db.flush()
