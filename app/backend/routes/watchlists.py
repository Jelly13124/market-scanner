"""REST routes for user-curated watchlists (Phase 5B).

Endpoints (all under ``/watchlists``):

    GET    /watchlists                          list all (current user)
    POST   /watchlists                          create empty list (409 on name conflict)
    GET    /watchlists/{id}                     detail (404 if not owned by current user)
    PATCH  /watchlists/{id}                     update name and/or tickers
    DELETE /watchlists/{id}                     204 No Content
    POST   /watchlists/{id}/tickers             add ticker
    DELETE /watchlists/{id}/tickers/{ticker}    remove ticker

Wave 4 (Task 4.1): every endpoint requires a valid Bearer token and all
repository calls are scoped to ``current_user.id``. A cross-tenant
GET/PATCH/DELETE returns 404 (never reveals another user's row exists).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import User
from app.backend.models.screener_schemas import LiveQuoteRow
from app.backend.models.watchlist_schemas import (
    TickerAddRequest,
    UserWatchlistCreate,
    UserWatchlistResponse,
    UserWatchlistUpdate,
)
from app.backend.repositories.watchlist_repository import UserWatchlistRepository
from app.backend.services.live_quotes import fetch_live_quotes


router = APIRouter(prefix="/watchlists")


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


@router.get("", response_model=list[UserWatchlistResponse])
def list_watchlists(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[UserWatchlistResponse]:
    rows = UserWatchlistRepository(db).list(user_id=current_user.id)
    return [UserWatchlistResponse.model_validate(r) for r in rows]


@router.post("", response_model=UserWatchlistResponse, status_code=201)
def create_watchlist(body: UserWatchlistCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> UserWatchlistResponse:
    repo = UserWatchlistRepository(db)
    if repo.get_by_name(body.name, user_id=current_user.id) is not None:
        raise HTTPException(409, f"watchlist with name {body.name!r} already exists")
    try:
        row = repo.create(body.name, user_id=current_user.id)
    except IntegrityError:
        # Race condition with another request — surface as conflict too.
        db.rollback()
        raise HTTPException(409, f"watchlist with name {body.name!r} already exists")
    return UserWatchlistResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------


@router.get("/{watchlist_id}", response_model=UserWatchlistResponse)
def get_watchlist(watchlist_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> UserWatchlistResponse:
    row = UserWatchlistRepository(db).get(watchlist_id, user_id=current_user.id)
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)


@router.patch("/{watchlist_id}", response_model=UserWatchlistResponse)
def update_watchlist(watchlist_id: int, body: UserWatchlistUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> UserWatchlistResponse:
    repo = UserWatchlistRepository(db)
    # Name conflict check (only when renaming to a name already taken by ANOTHER row for this user).
    if body.name is not None:
        existing = repo.get_by_name(body.name, user_id=current_user.id)
        if existing is not None and existing.id != watchlist_id:
            raise HTTPException(409, f"watchlist with name {body.name!r} already exists")
    try:
        row = repo.update(watchlist_id, user_id=current_user.id, name=body.name, tickers=body.tickers)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "watchlist name conflict")
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)


@router.delete("/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Response:
    deleted = UserWatchlistRepository(db).delete(watchlist_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Tickers within a watchlist
# ---------------------------------------------------------------------------


@router.post("/{watchlist_id}/tickers", response_model=UserWatchlistResponse)
def add_ticker(watchlist_id: int, body: TickerAddRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> UserWatchlistResponse:
    row = UserWatchlistRepository(db).add_ticker(watchlist_id, body.ticker, user_id=current_user.id)
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)


@router.delete("/{watchlist_id}/tickers/{ticker}", response_model=UserWatchlistResponse)
def remove_ticker(watchlist_id: int, ticker: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> UserWatchlistResponse:
    row = UserWatchlistRepository(db).remove_ticker(watchlist_id, ticker, user_id=current_user.id)
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Live quotes (on-demand yfinance batch fetch)
# ---------------------------------------------------------------------------


@router.get("/{watchlist_id}/quotes", response_model=list[LiveQuoteRow])
def get_watchlist_quotes(watchlist_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[LiveQuoteRow]:
    wl = UserWatchlistRepository(db).get(watchlist_id, user_id=current_user.id)
    if wl is None:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return [LiveQuoteRow(**q) for q in fetch_live_quotes(list(wl.tickers or []))]
