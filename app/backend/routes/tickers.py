"""Ticker autocomplete endpoint for the watchlist UI (Phase 5B).

    GET /tickers/search?q=...   list[TickerSearchResult]   (cap 20)

Backed by a static union of the bundled universe CSVs (nasdaq100 + sp500 +
russell3000). Loaded once at module import time and cached.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter

from app.backend.models.watchlist_schemas import TickerSearchResult
from v2.scanner.universes.loader import load_universe


router = APIRouter(prefix="/tickers")


_MAX_RESULTS = 20


@lru_cache(maxsize=1)
def _symbol_table() -> tuple[str, ...]:
    """Union of nasdaq100 + sp500 + russell3000, deduped, preserving order.

    nasdaq100 first so the "popular default" (empty-query response) leads
    with the most-watched mega-caps.
    """
    seen: set[str] = set()
    out: list[str] = []
    for kind in ("nasdaq100", "sp500", "russell3000"):
        try:
            tickers = load_universe(kind)
        except Exception:
            # Any CSV missing/broken — skip rather than 500 the search route.
            continue
        for t in tickers:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return tuple(out)


def _rank_matches(query: str, symbols: tuple[str, ...]) -> list[str]:
    """Rank: exact match → startswith → contains. Stable within each tier."""
    q = query.strip().upper()
    if not q:
        # Empty query — return top 20 "popular" (first 20 of the table,
        # which is nasdaq100-led).
        return list(symbols[:_MAX_RESULTS])

    exact: list[str] = []
    startswith: list[str] = []
    contains: list[str] = []
    for sym in symbols:
        if sym == q:
            exact.append(sym)
        elif sym.startswith(q):
            startswith.append(sym)
        elif q in sym:
            contains.append(sym)
    return (exact + startswith + contains)[:_MAX_RESULTS]


@router.get("/search", response_model=list[TickerSearchResult])
def search_tickers(q: str = "") -> list[TickerSearchResult]:
    """Autocomplete-friendly ticker lookup. Case-insensitive."""
    matches = _rank_matches(q, _symbol_table())
    return [TickerSearchResult(ticker=m, name=None) for m in matches]
