"""REST routes for user-curated watchlists (Phase 5B).

Endpoints (all under ``/watchlists``):

    GET    /watchlists                          list all
    POST   /watchlists                          create empty list (409 on name conflict)
    GET    /watchlists/{id}                     detail
    PATCH  /watchlists/{id}                     update name and/or tickers
    DELETE /watchlists/{id}                     204 No Content
    POST   /watchlists/{id}/tickers             add ticker
    DELETE /watchlists/{id}/tickers/{ticker}    remove ticker
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models.watchlist_schemas import (
    TickerAddRequest,
    UserWatchlistCreate,
    UserWatchlistResponse,
    UserWatchlistUpdate,
)
from app.backend.repositories.watchlist_repository import UserWatchlistRepository


router = APIRouter(prefix="/watchlists")


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


@router.get("", response_model=list[UserWatchlistResponse])
def list_watchlists(db: Session = Depends(get_db)) -> list[UserWatchlistResponse]:
    rows = UserWatchlistRepository(db).list()
    return [UserWatchlistResponse.model_validate(r) for r in rows]


@router.post("", response_model=UserWatchlistResponse, status_code=201)
def create_watchlist(
    body: UserWatchlistCreate, db: Session = Depends(get_db)
) -> UserWatchlistResponse:
    repo = UserWatchlistRepository(db)
    if repo.get_by_name(body.name) is not None:
        raise HTTPException(409, f"watchlist with name {body.name!r} already exists")
    try:
        row = repo.create(body.name)
    except IntegrityError:
        # Race condition with another request — surface as conflict too.
        db.rollback()
        raise HTTPException(409, f"watchlist with name {body.name!r} already exists")
    return UserWatchlistResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------


@router.get("/{watchlist_id}", response_model=UserWatchlistResponse)
def get_watchlist(
    watchlist_id: int, db: Session = Depends(get_db)
) -> UserWatchlistResponse:
    row = UserWatchlistRepository(db).get(watchlist_id)
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)


@router.patch("/{watchlist_id}", response_model=UserWatchlistResponse)
def update_watchlist(
    watchlist_id: int,
    body: UserWatchlistUpdate,
    db: Session = Depends(get_db),
) -> UserWatchlistResponse:
    repo = UserWatchlistRepository(db)
    # Name conflict check (only when renaming to a name already taken by ANOTHER row).
    if body.name is not None:
        existing = repo.get_by_name(body.name)
        if existing is not None and existing.id != watchlist_id:
            raise HTTPException(409, f"watchlist with name {body.name!r} already exists")
    try:
        row = repo.update(watchlist_id, name=body.name, tickers=body.tickers)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "watchlist name conflict")
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)


@router.delete("/{watchlist_id}", status_code=204)
def delete_watchlist(
    watchlist_id: int, db: Session = Depends(get_db)
) -> Response:
    deleted = UserWatchlistRepository(db).delete(watchlist_id)
    if not deleted:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Tickers within a watchlist
# ---------------------------------------------------------------------------


@router.post("/{watchlist_id}/tickers", response_model=UserWatchlistResponse)
def add_ticker(
    watchlist_id: int,
    body: TickerAddRequest,
    db: Session = Depends(get_db),
) -> UserWatchlistResponse:
    row = UserWatchlistRepository(db).add_ticker(watchlist_id, body.ticker)
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)


@router.delete("/{watchlist_id}/tickers/{ticker}", response_model=UserWatchlistResponse)
def remove_ticker(
    watchlist_id: int,
    ticker: str,
    db: Session = Depends(get_db),
) -> UserWatchlistResponse:
    row = UserWatchlistRepository(db).remove_ticker(watchlist_id, ticker)
    if not row:
        raise HTTPException(404, f"no watchlist with id {watchlist_id}")
    return UserWatchlistResponse.model_validate(row)
