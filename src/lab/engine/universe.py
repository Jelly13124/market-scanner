"""Phase 6B: resolve UniverseSpec → list[ticker] for the backtest engine.

Delegates to v2/scanner/universes/loader.py for sp500/nasdaq100 and to
Phase 5B's UserWatchlistRepository for the watchlist case. Raises
UniverseError early so the engine fails fast on missing/empty input.
"""

from __future__ import annotations

from typing import Any

from app.backend.repositories.watchlist_repository import UserWatchlistRepository
from src.lab.spec.strategy import UniverseSpec


class UniverseError(ValueError):
    """Raised when a UniverseSpec cannot be resolved to a non-empty ticker list."""


def load_universe_tickers(spec: UniverseSpec, db: Any) -> list[str]:
    """Return list of uppercased ticker symbols for the spec's universe.

    For ``kind='watchlist'``, ``db`` must be a SQLAlchemy Session.
    For static kinds (sp500, nasdaq100), ``db`` is ignored.
    """
    if spec.kind == "watchlist":
        repo = UserWatchlistRepository(db)
        row = repo.get_by_id_unscoped(spec.watchlist_id)
        if row is None:
            raise UniverseError(f"UserWatchlist id={spec.watchlist_id} not found")
        tickers = list(row.tickers or [])
        if not tickers:
            raise UniverseError(f"UserWatchlist id={spec.watchlist_id} has no tickers")
        return [t.upper() for t in tickers]

    from v2.scanner.universes.loader import load_universe
    # load_universe(kind, custom=None, watchlist_tickers=None) per Phase 5C
    try:
        return load_universe(spec.kind)
    except Exception as e:
        raise UniverseError(f"Failed to load universe kind={spec.kind!r}: {e}") from e
