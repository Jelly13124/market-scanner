"""Repository for user-curated watchlists (Phase 5B).

Sync, Session-injected, commits per write. Mirrors the shape of
``PipelineRunRepository``.

Wave 4 (Task 4.1): every method is scoped by ``user_id`` so rows from
one user are never visible to another.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import UserWatchlist


class UserWatchlistRepository:
    """CRUD + ticker add/remove for ``UserWatchlist``."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- create --------------------------------------------------------------

    def create(self, name: str, *, user_id: int) -> UserWatchlist:
        """Insert an empty watchlist row with the given name, owned by ``user_id``."""
        row = UserWatchlist(name=name, tickers=[], user_id=user_id)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    # -- read ----------------------------------------------------------------

    def get(self, watchlist_id: int, *, user_id: int) -> Optional[UserWatchlist]:
        return (
            self.db.query(UserWatchlist)
            .filter(UserWatchlist.id == watchlist_id, UserWatchlist.user_id == user_id)
            .first()
        )

    def get_by_id_unscoped(self, watchlist_id: int) -> Optional[UserWatchlist]:
        """Unscoped lookup by primary key — for internal system use only (e.g. backtest engine).

        Do NOT call this from HTTP routes; use ``get(id, user_id=...)`` there.
        """
        return (
            self.db.query(UserWatchlist)
            .filter(UserWatchlist.id == watchlist_id)
            .first()
        )

    def get_by_name(self, name: str, *, user_id: int) -> Optional[UserWatchlist]:
        return (
            self.db.query(UserWatchlist)
            .filter(UserWatchlist.name == name, UserWatchlist.user_id == user_id)
            .first()
        )

    def list(self, *, user_id: int) -> list[UserWatchlist]:
        """Return all watchlists for ``user_id``, newest-first.

        Order by ``created_at`` first, then ``id`` as a tie-breaker —
        SQLite's CURRENT_TIMESTAMP default has 1-second resolution, so two
        rows inserted in the same second would otherwise be unordered.
        """
        return (
            self.db.query(UserWatchlist)
            .filter(UserWatchlist.user_id == user_id)
            .order_by(desc(UserWatchlist.created_at), desc(UserWatchlist.id))
            .all()
        )

    # -- update --------------------------------------------------------------

    def update(
        self,
        watchlist_id: int,
        *,
        user_id: int,
        name: str | None = None,
        tickers: list[str] | None = None,
    ) -> Optional[UserWatchlist]:
        row = self.get(watchlist_id, user_id=user_id)
        if not row:
            return None
        if name is not None:
            row.name = name
        if tickers is not None:
            # Always store uppercase, deduped, preserving caller order.
            seen: set[str] = set()
            cleaned: list[str] = []
            for t in tickers:
                u = t.strip().upper()
                if u and u not in seen:
                    seen.add(u)
                    cleaned.append(u)
            row.tickers = cleaned
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, watchlist_id: int, *, user_id: int) -> bool:
        row = self.get(watchlist_id, user_id=user_id)
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    # -- ticker membership ---------------------------------------------------

    def add_ticker(self, watchlist_id: int, ticker: str, *, user_id: int) -> Optional[UserWatchlist]:
        """Uppercase + append if not present. Idempotent."""
        row = self.get(watchlist_id, user_id=user_id)
        if not row:
            return None
        u = ticker.strip().upper()
        if not u:
            return row
        current = list(row.tickers or [])
        if u not in current:
            current.append(u)
            # Reassign so SQLAlchemy detects the JSON column mutation.
            row.tickers = current
            self.db.commit()
            self.db.refresh(row)
        return row

    def remove_ticker(self, watchlist_id: int, ticker: str, *, user_id: int) -> Optional[UserWatchlist]:
        row = self.get(watchlist_id, user_id=user_id)
        if not row:
            return None
        u = ticker.strip().upper()
        current = list(row.tickers or [])
        if u in current:
            current.remove(u)
            row.tickers = current
            self.db.commit()
            self.db.refresh(row)
        return row
