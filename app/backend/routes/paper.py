"""Ordinary users' own simulated accounts; the legacy host book stays private."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import User, UserPaperAccount, UserPaperPosition
from app.backend.models.paper_schemas import PaperAccountCreate, PaperOrderCreate, PaperMarkCreate
from app.backend.services.user_paper_service import account_for, fill, snapshot

router = APIRouter(prefix="/paper")


@router.get("/account")
@router.get("/performance")
def get_account(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return snapshot(db, current_user.id)


@router.post("/account", status_code=201)
def create_account(body: PaperAccountCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if account_for(db, current_user.id) is not None:
        raise HTTPException(409, "Your paper account already exists")
    db.add(UserPaperAccount(user_id=current_user.id, initial_cash=body.initial_cash, cash=body.initial_cash, realized_pnl=0))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Your paper account already exists")
    return snapshot(db, current_user.id)


@router.post("/orders", status_code=201)
def place_order(body: PaperOrderCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        fill(db, current_user.id, body)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return snapshot(db, current_user.id)


@router.post("/marks")
def mark_position(body: PaperMarkCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = account_for(db, current_user.id, lock=True)
    if account is None:
        raise HTTPException(409, "Create your paper account first")
    position = db.query(UserPaperPosition).filter(UserPaperPosition.account_id == account.id, UserPaperPosition.ticker == body.ticker).first()
    if position is None:
        raise HTTPException(404, "No position in your account for this ticker")
    position.last_price = body.price
    db.commit()
    return snapshot(db, current_user.id)
