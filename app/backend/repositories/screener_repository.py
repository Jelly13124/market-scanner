"""ScreenerRepository — CRUD for ticker_snapshots.

Filter-dict → SQLAlchemy WHERE translation lives here. Unknown filter
keys are logged + ignored (keeps the API forward-compatible with new
chips added in later phases).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.backend.database.models import TickerSnapshot

logger = logging.getLogger(__name__)


@dataclass
class SnapshotRow:
    """Plain transport struct between SnapshotBuilder and the repository.

    Mirrors TickerSnapshot columns 1:1 minus `id` and `last_updated`
    (server-defaulted). All numeric fields are Decimal | None.
    """
    ticker: str
    market: str
    snapshot_date: date

    price: Decimal | None = None
    prev_close: Decimal | None = None
    change_pct: Decimal | None = None
    volume: int | None = None
    avg_volume_10d: int | None = None
    rel_volume: Decimal | None = None

    market_cap: Decimal | None = None

    pe_ttm: Decimal | None = None
    pe_forward: Decimal | None = None
    pb: Decimal | None = None
    ps: Decimal | None = None
    peg: Decimal | None = None

    eps_growth_yoy: Decimal | None = None
    revenue_growth_yoy: Decimal | None = None

    roe: Decimal | None = None
    profit_margin: Decimal | None = None

    dividend_yield_pct: Decimal | None = None
    beta: Decimal | None = None

    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None

    analyst_rating: str | None = None
    analyst_count: int | None = None
    target_mean_price: Decimal | None = None

    recent_earnings_date: date | None = None
    upcoming_earnings_date: date | None = None

    perf_1d: Decimal | None = None
    perf_5d: Decimal | None = None
    perf_1m: Decimal | None = None
    perf_3m: Decimal | None = None
    perf_ytd: Decimal | None = None
    perf_1y: Decimal | None = None

    data_source: str | None = None


# Filter key → (column, comparator). Comparator: "gte" | "lte" | "in" | "after" | "before"
_RANGE_FILTERS = {
    "price_min": ("price", "gte"),
    "price_max": ("price", "lte"),
    "chg_pct_min": ("change_pct", "gte"),
    "chg_pct_max": ("change_pct", "lte"),
    "mcap_min": ("market_cap", "gte"),
    "mcap_max": ("market_cap", "lte"),
    "pe_min": ("pe_ttm", "gte"),
    "pe_max": ("pe_ttm", "lte"),
    "eps_growth_min": ("eps_growth_yoy", "gte"),
    "eps_growth_max": ("eps_growth_yoy", "lte"),
    "div_yield_min": ("dividend_yield_pct", "gte"),
    "div_yield_max": ("dividend_yield_pct", "lte"),
    "revenue_growth_min": ("revenue_growth_yoy", "gte"),
    "revenue_growth_max": ("revenue_growth_yoy", "lte"),
    "peg_min": ("peg", "gte"),
    "peg_max": ("peg", "lte"),
    "roe_min": ("roe", "gte"),
    "roe_max": ("roe", "lte"),
    "beta_min": ("beta", "gte"),
    "beta_max": ("beta", "lte"),
    "perf_1d_min": ("perf_1d", "gte"),
    "perf_1d_max": ("perf_1d", "lte"),
    "perf_5d_min": ("perf_5d", "gte"),
    "perf_5d_max": ("perf_5d", "lte"),
    "perf_1m_min": ("perf_1m", "gte"),
    "perf_1m_max": ("perf_1m", "lte"),
    "perf_3m_min": ("perf_3m", "gte"),
    "perf_3m_max": ("perf_3m", "lte"),
    "perf_ytd_min": ("perf_ytd", "gte"),
    "perf_ytd_max": ("perf_ytd", "lte"),
    "perf_1y_min": ("perf_1y", "gte"),
    "perf_1y_max": ("perf_1y", "lte"),
}
_DATE_FILTERS = {
    "recent_earnings_after": ("recent_earnings_date", "after"),
    "recent_earnings_before": ("recent_earnings_date", "before"),
    "upcoming_earnings_after": ("upcoming_earnings_date", "after"),
    "upcoming_earnings_before": ("upcoming_earnings_date", "before"),
}
_LIST_FILTERS = {
    "sector_in": "sector",
    "analyst_rating_in": "analyst_rating",
}

_SORTABLE_COLS = {
    "ticker", "market_cap", "price", "change_pct", "volume", "pe_ttm",
    "eps_growth_yoy", "dividend_yield_pct", "revenue_growth_yoy",
    "peg", "roe", "beta",
    "perf_1d", "perf_5d", "perf_1m", "perf_3m", "perf_ytd", "perf_1y",
}


class ScreenerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ----- writes ------------------------------------------------------

    def bulk_upsert(self, rows: list[SnapshotRow]) -> int:
        """INSERT ... ON CONFLICT (ticker, snapshot_date) DO UPDATE.
        Returns count of rows processed (matches len(rows))."""
        if not rows:
            return 0
        dialect = self.db.bind.dialect.name
        payloads = [asdict(r) for r in rows]
        if dialect == "postgresql":
            stmt = pg_insert(TickerSnapshot).values(payloads)
            update_cols = {c.name: stmt.excluded[c.name]
                           for c in TickerSnapshot.__table__.columns
                           if c.name not in ("id", "ticker", "snapshot_date",
                                             "last_updated")}
            stmt = stmt.on_conflict_do_update(
                constraint="uq_snapshot_ticker_date",
                set_=update_cols,
            )
        else:  # sqlite (tests) — same shape
            stmt = sqlite_insert(TickerSnapshot).values(payloads)
            update_cols = {c.name: stmt.excluded[c.name]
                           for c in TickerSnapshot.__table__.columns
                           if c.name not in ("id", "ticker", "snapshot_date",
                                             "last_updated")}
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "snapshot_date"],
                set_=update_cols,
            )
        self.db.execute(stmt)
        self.db.commit()
        return len(rows)

    def cleanup_old_snapshots(self, keep_days: int = 30) -> int:
        cutoff = date.today() - timedelta(days=keep_days)
        result = self.db.execute(
            delete(TickerSnapshot).where(TickerSnapshot.snapshot_date < cutoff)
        )
        self.db.commit()
        return result.rowcount or 0

    # ----- reads -------------------------------------------------------

    def latest_snapshot_date(self, market: str | None = None) -> date | None:
        q = select(func.max(TickerSnapshot.snapshot_date))
        if market is not None:
            q = q.where(TickerSnapshot.market == market)
        return self.db.execute(q).scalar()

    def query(
        self,
        market: list[str] | None = None,
        universe: list[str] | None = None,
        snapshot_date: date | None = None,
        filters: dict[str, Any] | None = None,
        sort_by: str = "market_cap",
        sort_dir: Literal["asc", "desc"] = "desc",
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[TickerSnapshot], int]:
        filters = filters or {}

        # Resolve snapshot_date: latest matching market filter if not given.
        if snapshot_date is None:
            target_market = market[0] if (market and len(market) == 1) else None
            snapshot_date = self.latest_snapshot_date(market=target_market)
            if snapshot_date is None:
                return [], 0

        conds = [TickerSnapshot.snapshot_date == snapshot_date]
        if market:
            conds.append(TickerSnapshot.market.in_(market))
        if universe:
            conds.append(TickerSnapshot.ticker.in_(universe))

        for key, value in filters.items():
            if value is None or value == "":
                continue
            if key in _RANGE_FILTERS:
                col_name, op = _RANGE_FILTERS[key]
                col = getattr(TickerSnapshot, col_name)
                if op == "gte":
                    conds.append(col >= Decimal(str(value)))
                else:
                    conds.append(col <= Decimal(str(value)))
            elif key in _DATE_FILTERS:
                col_name, op = _DATE_FILTERS[key]
                col = getattr(TickerSnapshot, col_name)
                d = value if isinstance(value, date) else date.fromisoformat(str(value))
                if op == "after":
                    conds.append(col >= d)
                else:
                    conds.append(col <= d)
            elif key in _LIST_FILTERS:
                col = getattr(TickerSnapshot, _LIST_FILTERS[key])
                vals = value if isinstance(value, list) else [value]
                if vals:
                    conds.append(col.in_(vals))
            else:
                logger.debug("ScreenerRepository: ignoring unknown filter %r", key)

        where = and_(*conds)

        # total count (before limit/offset)
        total = self.db.execute(
            select(func.count()).select_from(TickerSnapshot).where(where)
        ).scalar() or 0

        # rows
        sort_col_name = sort_by if sort_by in _SORTABLE_COLS else "market_cap"
        sort_col = getattr(TickerSnapshot, sort_col_name)
        order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
        rows = self.db.execute(
            select(TickerSnapshot)
            .where(where)
            .order_by(order)
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return list(rows), int(total)
