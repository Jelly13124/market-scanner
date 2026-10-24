# Screener Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a nightly-snapshot-backed Screener tab with 16 TradingView-style filter chips over the S&P 500 + CSI 300 universe (~800 tickers).

**Architecture:** A `ticker_snapshots` table holds one row per (ticker, date) with all filterable metrics. A cron job at 22:00 ET runs SnapshotBuilder (yfinance for US, mootdx+akshare for CN) to upsert rows. A new FastAPI router under `/screener` exposes filtered queries + column metadata + status. A new `Screener` React tab renders the chip bar + sortable table, calling those endpoints.

**Tech Stack:** SQLAlchemy + Alembic, FastAPI, APScheduler, yfinance, mootdx, akshare, React, TanStack Table, react-i18next.

**Spec:** `docs/superpowers/specs/2026-05-27-screener-phase1-design.md`

**Reuse:**
- `v2.scanner.universes.loader.load_universe()` — read-only consumer of bundled `sp500.csv` + `csi300.csv`
- `v2.data.factory` — yfinance composite client construction
- `app.backend.services.scheduler_service.SchedulerService` — APScheduler wrapper; we add one more job to its `_start` flow
- `app.backend.database.SessionLocal / get_db` — session machinery
- `tests/research/`-style mock patterns for yfinance / akshare

**Constraints:**
- DO NOT modify `v2/scanner/`, `src/research/`, `src/agents/`, or existing DB tables
- DO NOT add real yfinance / mootdx / akshare network calls in tests — mock everything
- DO NOT modify the Scanner cron (16:30 ET) or Research cron (16:35 ET)

---

## Task 1: Database model + Alembic migration

**Files:**
- Modify: `app/backend/database/models.py` (append `TickerSnapshot` class)
- Create: `app/backend/alembic/versions/d4e8a2c1b9f6_add_ticker_snapshots.py`
- Test: `tests/test_screener_db_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_screener_db_models.py`:

```python
"""TickerSnapshot ORM smoke test — verifies column shape and uniqueness."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, TickerSnapshot


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_insert_minimal_row(session):
    row = TickerSnapshot(
        ticker="AAPL",
        market="US",
        snapshot_date=date(2026, 5, 27),
        price=Decimal("210.50"),
        market_cap=Decimal("3200000000000"),
        sector="Technology",
    )
    session.add(row)
    session.commit()
    out = session.query(TickerSnapshot).filter_by(ticker="AAPL").one()
    assert out.market == "US"
    assert out.sector == "Technology"
    assert out.price == Decimal("210.50")


def test_full_field_set(session):
    row = TickerSnapshot(
        ticker="NVDA", market="US", snapshot_date=date(2026, 5, 27),
        price=Decimal("950.00"), prev_close=Decimal("940.00"),
        change_pct=Decimal("1.0638"), volume=120_000_000,
        avg_volume_10d=100_000_000, rel_volume=Decimal("1.200"),
        market_cap=Decimal("2300000000000"),
        pe_ttm=Decimal("65.123"), pe_forward=Decimal("45.000"),
        pb=Decimal("40.500"), ps=Decimal("30.000"), peg=Decimal("1.500"),
        eps_growth_yoy=Decimal("1.1033"), revenue_growth_yoy=Decimal("0.7820"),
        roe=Decimal("0.9500"), profit_margin=Decimal("0.4200"),
        dividend_yield_pct=Decimal("0.0200"), beta=Decimal("1.500"),
        sector="Technology", industry="Semiconductors", exchange="NASDAQ",
        analyst_rating="strong_buy", analyst_count=45,
        target_mean_price=Decimal("1100.00"),
        recent_earnings_date=date(2026, 5, 22),
        upcoming_earnings_date=date(2026, 8, 21),
        perf_1d=Decimal("0.0106"), perf_5d=Decimal("0.0312"),
        perf_1m=Decimal("0.0820"), perf_3m=Decimal("0.1750"),
        perf_ytd=Decimal("0.4500"), perf_1y=Decimal("1.2300"),
        data_source="yfinance",
    )
    session.add(row)
    session.commit()
    out = session.query(TickerSnapshot).filter_by(ticker="NVDA").one()
    assert out.analyst_rating == "strong_buy"
    assert out.perf_1y == Decimal("1.2300")


def test_unique_ticker_date_constraint(session):
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 27), price=Decimal("210")))
    session.commit()
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 27), price=Decimal("220")))
    with pytest.raises(IntegrityError):
        session.commit()


def test_different_dates_allowed(session):
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 26), price=Decimal("208")))
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 27), price=Decimal("210")))
    session.commit()
    assert session.query(TickerSnapshot).filter_by(ticker="AAPL").count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/test_screener_db_models.py -v
```
Expected: `ImportError: cannot import name 'TickerSnapshot' from 'app.backend.database.models'`

- [ ] **Step 3: Add ORM class to models.py**

Append to `app/backend/database/models.py` (after the last existing class):

```python
class TickerSnapshot(Base):
    """Per-ticker per-day snapshot of all filterable Screener metrics.

    Built nightly by SnapshotBuilder; queried by ScreenerRepository.
    PK on (ticker, snapshot_date) makes daily upserts idempotent.
    """

    __tablename__ = "ticker_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False)
    market = Column(String(8), nullable=False)
    snapshot_date = Column(Date, nullable=False)

    # Price / volume
    price = Column(Numeric(12, 4))
    prev_close = Column(Numeric(12, 4))
    change_pct = Column(Numeric(8, 4))
    volume = Column(BigInteger)
    avg_volume_10d = Column(BigInteger)
    rel_volume = Column(Numeric(6, 3))

    # Market cap
    market_cap = Column(Numeric(20, 2))

    # Valuation
    pe_ttm = Column(Numeric(10, 3))
    pe_forward = Column(Numeric(10, 3))
    pb = Column(Numeric(10, 3))
    ps = Column(Numeric(10, 3))
    peg = Column(Numeric(10, 3))

    # Growth
    eps_growth_yoy = Column(Numeric(10, 4))
    revenue_growth_yoy = Column(Numeric(10, 4))

    # Profitability
    roe = Column(Numeric(10, 4))
    profit_margin = Column(Numeric(10, 4))

    # Dividend
    dividend_yield_pct = Column(Numeric(8, 4))

    # Risk
    beta = Column(Numeric(8, 3))

    # Classification
    sector = Column(String(64))
    industry = Column(String(128))
    exchange = Column(String(16))

    # Analyst
    analyst_rating = Column(String(16))
    analyst_count = Column(Integer)
    target_mean_price = Column(Numeric(12, 4))

    # Earnings dates
    recent_earnings_date = Column(Date)
    upcoming_earnings_date = Column(Date)

    # Performance windows
    perf_1d = Column(Numeric(8, 4))
    perf_5d = Column(Numeric(8, 4))
    perf_1m = Column(Numeric(8, 4))
    perf_3m = Column(Numeric(8, 4))
    perf_ytd = Column(Numeric(8, 4))
    perf_1y = Column(Numeric(8, 4))

    # Meta
    data_source = Column(String(16))
    last_updated = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", name="uq_snapshot_ticker_date"),
        Index("idx_snapshot_date", "snapshot_date"),
        Index("idx_snapshot_market_date", "market", "snapshot_date"),
        Index("idx_snapshot_sector", "sector", "snapshot_date"),
    )
```

If any of `BigInteger`, `Date`, `Numeric`, `String`, `Integer`, `DateTime`, `Column`, `UniqueConstraint`, `Index`, or `func` are not already imported at the top of the file, add them to the existing `from sqlalchemy import ...` line.

- [ ] **Step 4: Run test to verify it passes**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/test_screener_db_models.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Find current alembic head and create migration**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m alembic heads
```
Note the printed revision id — call it `<CURRENT_HEAD>`. Use that as `down_revision`.

Create `app/backend/alembic/versions/d4e8a2c1b9f6_add_ticker_snapshots.py`:

```python
"""add ticker_snapshots table

Revision ID: d4e8a2c1b9f6
Revises: <CURRENT_HEAD>
Create Date: 2026-05-27 22:00:00.000000

Adds the per-ticker per-day snapshot table backing the Screener tab.
Filtered queries (faceted chips) and nightly upserts both target this
single table. Unique (ticker, snapshot_date) makes upsert idempotent;
3 indices serve the common WHERE patterns (date alone, market+date,
sector+date).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8a2c1b9f6"
down_revision: Union[str, None] = "<CURRENT_HEAD>"  # replace with output of `alembic heads`
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticker_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(12, 4)),
        sa.Column("prev_close", sa.Numeric(12, 4)),
        sa.Column("change_pct", sa.Numeric(8, 4)),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("avg_volume_10d", sa.BigInteger()),
        sa.Column("rel_volume", sa.Numeric(6, 3)),
        sa.Column("market_cap", sa.Numeric(20, 2)),
        sa.Column("pe_ttm", sa.Numeric(10, 3)),
        sa.Column("pe_forward", sa.Numeric(10, 3)),
        sa.Column("pb", sa.Numeric(10, 3)),
        sa.Column("ps", sa.Numeric(10, 3)),
        sa.Column("peg", sa.Numeric(10, 3)),
        sa.Column("eps_growth_yoy", sa.Numeric(10, 4)),
        sa.Column("revenue_growth_yoy", sa.Numeric(10, 4)),
        sa.Column("roe", sa.Numeric(10, 4)),
        sa.Column("profit_margin", sa.Numeric(10, 4)),
        sa.Column("dividend_yield_pct", sa.Numeric(8, 4)),
        sa.Column("beta", sa.Numeric(8, 3)),
        sa.Column("sector", sa.String(length=64)),
        sa.Column("industry", sa.String(length=128)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("analyst_rating", sa.String(length=16)),
        sa.Column("analyst_count", sa.Integer()),
        sa.Column("target_mean_price", sa.Numeric(12, 4)),
        sa.Column("recent_earnings_date", sa.Date()),
        sa.Column("upcoming_earnings_date", sa.Date()),
        sa.Column("perf_1d", sa.Numeric(8, 4)),
        sa.Column("perf_5d", sa.Numeric(8, 4)),
        sa.Column("perf_1m", sa.Numeric(8, 4)),
        sa.Column("perf_3m", sa.Numeric(8, 4)),
        sa.Column("perf_ytd", sa.Numeric(8, 4)),
        sa.Column("perf_1y", sa.Numeric(8, 4)),
        sa.Column("data_source", sa.String(length=16)),
        sa.Column("last_updated", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticker", "snapshot_date", name="uq_snapshot_ticker_date"),
    )
    op.create_index("idx_snapshot_date", "ticker_snapshots", ["snapshot_date"])
    op.create_index("idx_snapshot_market_date", "ticker_snapshots",
                    ["market", "snapshot_date"])
    op.create_index("idx_snapshot_sector", "ticker_snapshots",
                    ["sector", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("idx_snapshot_sector", table_name="ticker_snapshots")
    op.drop_index("idx_snapshot_market_date", table_name="ticker_snapshots")
    op.drop_index("idx_snapshot_date", table_name="ticker_snapshots")
    op.drop_table("ticker_snapshots")
```

- [ ] **Step 6: Verify migration applies cleanly**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m alembic upgrade head
C:\Users\Jerry\anaconda3\python.exe -m alembic downgrade -1
C:\Users\Jerry\anaconda3\python.exe -m alembic upgrade head
```
Expected: no errors; final state has `ticker_snapshots` table.

- [ ] **Step 7: Commit**

```bash
git add app/backend/database/models.py app/backend/alembic/versions/d4e8a2c1b9f6_add_ticker_snapshots.py tests/test_screener_db_models.py
git commit -m "feat(screener): add TickerSnapshot ORM + alembic migration"
```

---

## Task 2: ScreenerRepository

**Depends on:** Task 1.

**Files:**
- Create: `app/backend/repositories/screener_repository.py`
- Test: `tests/test_screener_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_screener_repository.py`:

```python
"""ScreenerRepository: bulk upsert, filtered query, cleanup."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, TickerSnapshot
from app.backend.repositories.screener_repository import (
    ScreenerRepository,
    SnapshotRow,
)


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield ScreenerRepository(db)
    db.close()


def _row(ticker, market="US", snapshot_date=date(2026, 5, 27), **kw):
    base = dict(
        ticker=ticker, market=market, snapshot_date=snapshot_date,
        price=Decimal("100"), market_cap=Decimal("1000000000"),
        pe_ttm=Decimal("20"), sector="Technology",
        analyst_rating="buy", perf_1d=Decimal("0.01"),
        data_source="test",
    )
    base.update(kw)
    return SnapshotRow(**base)


def test_bulk_upsert_inserts(repo):
    rows = [_row("AAPL"), _row("MSFT"), _row("NVDA")]
    n = repo.bulk_upsert(rows)
    assert n == 3
    assert repo.db.query(TickerSnapshot).count() == 3


def test_bulk_upsert_idempotent_on_same_date(repo):
    repo.bulk_upsert([_row("AAPL", price=Decimal("210"))])
    repo.bulk_upsert([_row("AAPL", price=Decimal("215"))])  # same ticker+date
    assert repo.db.query(TickerSnapshot).count() == 1
    out = repo.db.query(TickerSnapshot).filter_by(ticker="AAPL").one()
    assert out.price == Decimal("215")  # updated


def test_latest_snapshot_date(repo):
    repo.bulk_upsert([_row("AAPL", snapshot_date=date(2026, 5, 26))])
    repo.bulk_upsert([_row("AAPL", snapshot_date=date(2026, 5, 27))])
    assert repo.latest_snapshot_date() == date(2026, 5, 27)
    assert repo.latest_snapshot_date(market="US") == date(2026, 5, 27)
    assert repo.latest_snapshot_date(market="CN") is None


def test_query_no_filter_returns_latest(repo):
    repo.bulk_upsert([
        _row("AAPL", snapshot_date=date(2026, 5, 26)),
        _row("AAPL", snapshot_date=date(2026, 5, 27)),
        _row("MSFT", snapshot_date=date(2026, 5, 27)),
    ])
    rows, total = repo.query()
    assert total == 2  # latest date only
    assert {r.ticker for r in rows} == {"AAPL", "MSFT"}


def test_query_price_range_filter(repo):
    repo.bulk_upsert([
        _row("LOW", price=Decimal("50")),
        _row("MID", price=Decimal("200")),
        _row("HI",  price=Decimal("500")),
    ])
    rows, total = repo.query(filters={"price_min": 100, "price_max": 300})
    assert total == 1
    assert rows[0].ticker == "MID"


def test_query_sector_in_filter(repo):
    repo.bulk_upsert([
        _row("AAPL", sector="Technology"),
        _row("JPM",  sector="Financial Services"),
        _row("XOM",  sector="Energy"),
    ])
    rows, total = repo.query(filters={"sector_in": ["Technology", "Energy"]})
    assert total == 2
    assert {r.ticker for r in rows} == {"AAPL", "XOM"}


def test_query_market_filter(repo):
    repo.bulk_upsert([
        _row("AAPL", market="US"),
        _row("600519.SH", market="CN"),
    ])
    rows, _ = repo.query(market=["CN"])
    assert {r.ticker for r in rows} == {"600519.SH"}


def test_query_sort_and_limit(repo):
    repo.bulk_upsert([
        _row("A", market_cap=Decimal("100")),
        _row("B", market_cap=Decimal("300")),
        _row("C", market_cap=Decimal("200")),
    ])
    rows, total = repo.query(sort_by="market_cap", sort_dir="desc", limit=2)
    assert total == 3
    assert [r.ticker for r in rows] == ["B", "C"]


def test_query_unknown_filter_ignored(repo):
    repo.bulk_upsert([_row("AAPL")])
    rows, total = repo.query(filters={"made_up_filter": 42})
    assert total == 1  # didn't crash, didn't drop the row


def test_cleanup_old_snapshots(repo):
    today = date.today()
    repo.bulk_upsert([
        _row("OLD", snapshot_date=today - timedelta(days=40)),
        _row("RECENT", snapshot_date=today - timedelta(days=10)),
        _row("NEW", snapshot_date=today),
    ])
    n = repo.cleanup_old_snapshots(keep_days=30)
    assert n == 1
    remaining = {r.ticker for r in repo.db.query(TickerSnapshot).all()}
    assert remaining == {"RECENT", "NEW"}
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/test_screener_repository.py -v
```
Expected: `ImportError: cannot import name 'ScreenerRepository' ...`

- [ ] **Step 3: Implement repository**

Create `app/backend/repositories/screener_repository.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/test_screener_repository.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backend/repositories/screener_repository.py tests/test_screener_repository.py
git commit -m "feat(screener): ScreenerRepository with filter-dict query + idempotent upsert"
```

---

## Task 3: SnapshotBuilder — US path (yfinance)

**Depends on:** Task 1.

**Files:**
- Create: `src/screener/__init__.py` (empty package marker)
- Create: `src/screener/snapshot_builder.py`
- Test: `tests/screener/__init__.py` (empty), `tests/screener/test_snapshot_builder_us.py`

- [ ] **Step 1: Create empty package markers**

Create `src/screener/__init__.py` with content:

```python
"""Screener Phase 1 — nightly snapshot + faceted filter backend."""
```

Create `tests/screener/__init__.py` with empty content.

- [ ] **Step 2: Write the failing test**

Create `tests/screener/test_snapshot_builder_us.py`:

```python
"""SnapshotBuilder US path — yfinance .info / .history mocked."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.screener.snapshot_builder import SnapshotBuilder


_FAKE_INFO = {
    "regularMarketPrice": 210.50,
    "regularMarketPreviousClose": 208.00,
    "regularMarketVolume": 65_000_000,
    "averageDailyVolume10Day": 60_000_000,
    "marketCap": 3_200_000_000_000,
    "trailingPE": 32.5,
    "forwardPE": 28.0,
    "priceToBook": 50.0,
    "priceToSalesTrailing12Months": 9.0,
    "pegRatio": 2.8,
    "earningsGrowth": 0.12,
    "revenueGrowth": 0.08,
    "returnOnEquity": 1.45,
    "profitMargins": 0.25,
    "dividendYield": 0.0050,
    "beta": 1.24,
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "exchange": "NMS",
    "recommendationKey": "buy",
    "numberOfAnalystOpinions": 38,
    "targetMeanPrice": 235.00,
    "mostRecentQuarter": 1_714_867_200,  # 2024-05-05 unix
}


def _fake_ticker():
    t = MagicMock()
    t.info = _FAKE_INFO

    # .history(period='1y') used for perf windows + earnings dates
    import pandas as pd
    idx = pd.date_range(end="2026-05-27", periods=260, freq="B")
    closes = pd.Series([100 + i * 0.5 for i in range(260)], index=idx)
    t.history.return_value = pd.DataFrame({"Close": closes,
                                           "Volume": [50_000_000] * 260})
    # earnings_dates: next 2 + last 8 quarters
    t.earnings_dates = pd.DataFrame(
        index=pd.to_datetime(["2026-08-21", "2026-05-22", "2026-02-15"]),
        data={"EPS Estimate": [1.5, 1.4, 1.3]},
    )
    return t


def test_build_for_ticker_us_full_fields():
    builder = SnapshotBuilder()
    with patch("src.screener.snapshot_builder.yf.Ticker", return_value=_fake_ticker()):
        row = builder.build_for_ticker_us("AAPL", date(2026, 5, 27))

    assert row.ticker == "AAPL"
    assert row.market == "US"
    assert row.snapshot_date == date(2026, 5, 27)
    assert row.price == Decimal("210.5")
    assert row.market_cap == Decimal("3200000000000")
    assert row.pe_ttm == Decimal("32.5")
    assert row.eps_growth_yoy == Decimal("0.12")
    assert row.sector == "Technology"
    assert row.analyst_rating == "buy"
    assert row.analyst_count == 38
    assert row.data_source == "yfinance"
    assert row.perf_1d is not None
    assert row.perf_1y is not None


def test_build_for_ticker_us_handles_missing_fields():
    sparse_info = {"regularMarketPrice": 50.0, "marketCap": 1_000_000_000}
    t = MagicMock()
    t.info = sparse_info
    import pandas as pd
    t.history.return_value = pd.DataFrame()
    t.earnings_dates = pd.DataFrame()

    builder = SnapshotBuilder()
    with patch("src.screener.snapshot_builder.yf.Ticker", return_value=t):
        row = builder.build_for_ticker_us("XYZ", date(2026, 5, 27))

    assert row.ticker == "XYZ"
    assert row.price == Decimal("50.0")
    assert row.pe_ttm is None
    assert row.sector is None
    assert row.perf_1y is None


def test_build_for_universe_us_skips_failures(caplog):
    """If yf.Ticker raises for one ticker, the rest still succeed."""
    builder = SnapshotBuilder()

    def fake_ticker(symbol):
        if symbol == "BROKEN":
            raise RuntimeError("yfinance HTTP 500")
        return _fake_ticker()

    with patch("src.screener.snapshot_builder.yf.Ticker", side_effect=fake_ticker), \
         patch("src.screener.snapshot_builder.load_universe",
               return_value=["AAPL", "BROKEN", "MSFT"]):
        rows = builder.build_for_universe("US", "sp500", date(2026, 5, 27))

    assert {r.ticker for r in rows} == {"AAPL", "MSFT"}
    assert "BROKEN" in caplog.text


def test_build_for_universe_us_reports_progress():
    progress_calls = []

    def on_progress(done, total):
        progress_calls.append((done, total))

    builder = SnapshotBuilder()
    with patch("src.screener.snapshot_builder.yf.Ticker", return_value=_fake_ticker()), \
         patch("src.screener.snapshot_builder.load_universe",
               return_value=["AAPL", "MSFT", "NVDA"]):
        builder.build_for_universe("US", "sp500", date(2026, 5, 27),
                                   on_progress=on_progress)
    assert progress_calls[-1] == (3, 3)
```

- [ ] **Step 3: Run test to verify it fails**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_snapshot_builder_us.py -v
```
Expected: `ImportError: cannot import name 'SnapshotBuilder' ...`

- [ ] **Step 4: Implement SnapshotBuilder (US path only — CN comes in Task 4)**

Create `src/screener/snapshot_builder.py`:

```python
"""SnapshotBuilder — pull per-ticker metrics into SnapshotRow.

US path: yfinance .info + .history + .earnings_dates.
CN path: see Task 4 — mootdx + akshare wrapper (`ashare_metrics`).

Per-ticker exceptions are caught + logged; the loop never aborts on
one bad ticker. This matches the v2/scanner runner invariant.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Literal

import yfinance as yf

from app.backend.repositories.screener_repository import SnapshotRow
from v2.scanner.universes.loader import load_universe

logger = logging.getLogger(__name__)


def _to_decimal(value, *, scale: int | None = None) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if scale is not None:
            q = Decimal(10) ** -scale
            d = d.quantize(q)
        return d
    except (ValueError, ArithmeticError):
        return None


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


_RATING_NORMALIZE = {
    "strong_buy": "strong_buy",
    "strongbuy": "strong_buy",
    "buy": "buy",
    "outperform": "buy",
    "hold": "neutral",
    "neutral": "neutral",
    "underperform": "sell",
    "sell": "sell",
    "strong_sell": "strong_sell",
    "strongsell": "strong_sell",
}


def _normalize_rating(raw: str | None) -> str | None:
    if not raw:
        return None
    return _RATING_NORMALIZE.get(raw.lower().replace(" ", ""), None)


class SnapshotBuilder:
    """Iterate a universe; build one SnapshotRow per ticker."""

    def __init__(self, *, ashare_metrics=None) -> None:
        # ashare_metrics is injected in Task 4; US path doesn't need it.
        self._ashare = ashare_metrics

    # ------------------------------------------------------------ US ----

    def build_for_ticker_us(self, ticker: str, asof: date) -> SnapshotRow:
        """Pull yfinance metrics into SnapshotRow. Missing fields → None."""
        t = yf.Ticker(ticker)
        info = getattr(t, "info", None) or {}

        # .history(period='1y') for perf windows
        try:
            hist = t.history(period="1y")
        except Exception as e:
            logger.warning("yfinance history failed for %s: %s", ticker, e)
            hist = None

        perf = self._compute_perf(hist) if hist is not None and not hist.empty else {}

        # earnings dates
        recent_ed, upcoming_ed = self._extract_earnings_dates(t, asof)

        return SnapshotRow(
            ticker=ticker,
            market="US",
            snapshot_date=asof,
            price=_to_decimal(info.get("regularMarketPrice"), scale=4),
            prev_close=_to_decimal(info.get("regularMarketPreviousClose"), scale=4),
            change_pct=self._compute_change_pct(info),
            volume=_to_int(info.get("regularMarketVolume")),
            avg_volume_10d=_to_int(info.get("averageDailyVolume10Day")),
            rel_volume=self._compute_rel_volume(info),
            market_cap=_to_decimal(info.get("marketCap"), scale=2),
            pe_ttm=_to_decimal(info.get("trailingPE"), scale=3),
            pe_forward=_to_decimal(info.get("forwardPE"), scale=3),
            pb=_to_decimal(info.get("priceToBook"), scale=3),
            ps=_to_decimal(info.get("priceToSalesTrailing12Months"), scale=3),
            peg=_to_decimal(info.get("pegRatio"), scale=3),
            eps_growth_yoy=_to_decimal(info.get("earningsGrowth"), scale=4),
            revenue_growth_yoy=_to_decimal(info.get("revenueGrowth"), scale=4),
            roe=_to_decimal(info.get("returnOnEquity"), scale=4),
            profit_margin=_to_decimal(info.get("profitMargins"), scale=4),
            dividend_yield_pct=_to_decimal(info.get("dividendYield"), scale=4),
            beta=_to_decimal(info.get("beta"), scale=3),
            sector=info.get("sector"),
            industry=info.get("industry"),
            exchange=info.get("exchange"),
            analyst_rating=_normalize_rating(info.get("recommendationKey")),
            analyst_count=_to_int(info.get("numberOfAnalystOpinions")),
            target_mean_price=_to_decimal(info.get("targetMeanPrice"), scale=4),
            recent_earnings_date=recent_ed,
            upcoming_earnings_date=upcoming_ed,
            perf_1d=perf.get("perf_1d"),
            perf_5d=perf.get("perf_5d"),
            perf_1m=perf.get("perf_1m"),
            perf_3m=perf.get("perf_3m"),
            perf_ytd=perf.get("perf_ytd"),
            perf_1y=perf.get("perf_1y"),
            data_source="yfinance",
        )

    # ----------------------------------------------------- helpers ----

    def _compute_change_pct(self, info: dict) -> Decimal | None:
        p = info.get("regularMarketPrice")
        pc = info.get("regularMarketPreviousClose")
        if p is None or pc is None or pc == 0:
            return None
        return _to_decimal((p - pc) / pc, scale=4)

    def _compute_rel_volume(self, info: dict) -> Decimal | None:
        v = info.get("regularMarketVolume")
        avg = info.get("averageDailyVolume10Day")
        if v is None or not avg:
            return None
        return _to_decimal(v / avg, scale=3)

    def _compute_perf(self, hist) -> dict:
        """Closes-based perf for {1d, 5d, 1m, 3m, ytd, 1y}."""
        closes = hist["Close"].dropna()
        if closes.empty:
            return {}
        last = float(closes.iloc[-1])

        def _ago(days: int) -> Decimal | None:
            if len(closes) <= days:
                return None
            prev = float(closes.iloc[-1 - days])
            if prev == 0:
                return None
            return _to_decimal((last - prev) / prev, scale=4)

        # YTD = first trading day of current year
        try:
            year_start = closes.index[closes.index.year == closes.index[-1].year][0]
            ytd_prev = float(closes.loc[year_start])
            ytd = _to_decimal((last - ytd_prev) / ytd_prev, scale=4) if ytd_prev else None
        except Exception:
            ytd = None

        return {
            "perf_1d":  _ago(1),
            "perf_5d":  _ago(5),
            "perf_1m":  _ago(21),
            "perf_3m":  _ago(63),
            "perf_ytd": ytd,
            "perf_1y":  _ago(252),
        }

    def _extract_earnings_dates(self, t, asof: date) -> tuple[date | None, date | None]:
        try:
            ed = getattr(t, "earnings_dates", None)
            if ed is None or ed.empty:
                return None, None
            dates = sorted(d.date() for d in ed.index.to_pydatetime())
            past = [d for d in dates if d <= asof]
            future = [d for d in dates if d > asof]
            recent = past[-1] if past else None
            upcoming = future[0] if future else None
            return recent, upcoming
        except Exception as e:
            logger.debug("earnings_dates parse failed: %s", e)
            return None, None

    # --------------------------------------------------- universe ----

    def build_for_universe(
        self,
        market: Literal["US", "CN"],
        universe_kind: str,
        asof: date,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[SnapshotRow]:
        tickers = load_universe(universe_kind)
        if not tickers:
            logger.warning("Empty universe for kind=%s", universe_kind)
            return []

        builder = (self.build_for_ticker_us if market == "US"
                   else self.build_for_ticker_cn)

        rows: list[SnapshotRow] = []
        for i, t in enumerate(tickers, 1):
            try:
                rows.append(builder(t, asof))
            except Exception as e:
                logger.warning("Snapshot failed for %s: %s", t, e)
            if on_progress is not None:
                on_progress(i, len(tickers))
        return rows

    # CN path injected in Task 4
    def build_for_ticker_cn(self, ticker: str, asof: date) -> SnapshotRow:
        raise NotImplementedError("CN path lands in Task 4 (ashare_metrics)")
```

- [ ] **Step 5: Run test to verify it passes**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_snapshot_builder_us.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/screener/__init__.py src/screener/snapshot_builder.py tests/screener/__init__.py tests/screener/test_snapshot_builder_us.py
git commit -m "feat(screener): SnapshotBuilder US path (yfinance)"
```

---

## Task 4: SnapshotBuilder — CN path (mootdx + akshare)

**Depends on:** Task 1.

**Files:**
- Create: `src/screener/ashare_metrics.py`
- Modify: `src/screener/snapshot_builder.py` (implement `build_for_ticker_cn`)
- Test: `tests/screener/test_snapshot_builder_cn.py`

- [ ] **Step 1: Write the failing test**

Create `tests/screener/test_snapshot_builder_cn.py`:

```python
"""SnapshotBuilder CN path — mootdx + akshare mocked through AshareMetrics."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.screener.snapshot_builder import SnapshotBuilder


@pytest.fixture()
def fake_ashare():
    """AshareMetrics duck-typed mock."""
    m = MagicMock()
    m.get_quote.return_value = {
        "price": 1700.50,
        "prev_close": 1685.00,
        "volume": 2_500_000,
        "avg_volume_10d": 2_300_000,
    }
    m.get_fundamentals.return_value = {
        "market_cap": 2_120_000_000_000,
        "pe_ttm": 28.5,
        "pb": 8.2,
        "ps": 9.1,
        "peg": 1.4,
        "eps_growth_yoy": 0.18,
        "revenue_growth_yoy": 0.15,
        "roe": 0.32,
        "profit_margin": 0.35,
        "dividend_yield_pct": 0.012,
        "sector": "白酒",
        "industry": "食品饮料",
        "exchange": "SSE",
    }
    m.get_perf_windows.return_value = {
        "perf_1d": 0.0092, "perf_5d": 0.0210, "perf_1m": 0.0530,
        "perf_3m": 0.1110, "perf_ytd": 0.2200, "perf_1y": 0.4150,
    }
    m.get_earnings_dates.return_value = (date(2026, 4, 28), date(2026, 8, 25))
    return m


def test_build_for_ticker_cn_full(fake_ashare):
    builder = SnapshotBuilder(ashare_metrics=fake_ashare)
    row = builder.build_for_ticker_cn("600519.SH", date(2026, 5, 27))

    assert row.ticker == "600519.SH"
    assert row.market == "CN"
    assert row.snapshot_date == date(2026, 5, 27)
    assert row.price == Decimal("1700.5")
    assert row.market_cap == Decimal("2120000000000")
    assert row.sector == "白酒"
    assert row.exchange == "SSE"
    assert row.perf_ytd == Decimal("0.2200")
    assert row.recent_earnings_date == date(2026, 4, 28)
    assert row.upcoming_earnings_date == date(2026, 8, 25)
    assert row.data_source == "mootdx+akshare"


def test_build_for_ticker_cn_handles_missing(fake_ashare):
    fake_ashare.get_fundamentals.return_value = {}
    fake_ashare.get_perf_windows.return_value = {}
    fake_ashare.get_earnings_dates.return_value = (None, None)

    builder = SnapshotBuilder(ashare_metrics=fake_ashare)
    row = builder.build_for_ticker_cn("000001.SZ", date(2026, 5, 27))

    assert row.ticker == "000001.SZ"
    assert row.price == Decimal("1700.5")  # quote still present
    assert row.market_cap is None
    assert row.sector is None
    assert row.perf_1y is None


def test_build_for_universe_cn_dispatches_to_cn_path(fake_ashare):
    from unittest.mock import patch
    builder = SnapshotBuilder(ashare_metrics=fake_ashare)
    with patch("src.screener.snapshot_builder.load_universe",
               return_value=["600519.SH", "000001.SZ"]):
        rows = builder.build_for_universe("CN", "csi300", date(2026, 5, 27))
    assert {r.ticker for r in rows} == {"600519.SH", "000001.SZ"}
    assert all(r.market == "CN" for r in rows)


def test_build_for_ticker_cn_without_ashare_raises():
    builder = SnapshotBuilder()  # no ashare injected
    with pytest.raises(RuntimeError, match="ashare_metrics"):
        builder.build_for_ticker_cn("600519.SH", date(2026, 5, 27))
```

Also create `tests/screener/test_ashare_metrics.py`:

```python
"""AshareMetrics — thin wrapper test (no real network)."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def test_get_quote_shape():
    from src.screener.ashare_metrics import AshareMetrics
    fake_mootdx = MagicMock()
    fake_mootdx.quotes.return_value = {
        "price": 1700.5, "last_close": 1685.0,
        "vol": 25000, "amount": 4.25e10,
    }
    m = AshareMetrics(mootdx_client=fake_mootdx, akshare_module=MagicMock())
    q = m.get_quote("600519.SH")
    assert q["price"] == 1700.5
    assert q["prev_close"] == 1685.0
    assert q["volume"] == 25000 * 100  # mootdx volume is in 手 (lots of 100)


def test_get_quote_handles_unknown_symbol():
    from src.screener.ashare_metrics import AshareMetrics
    fake_mootdx = MagicMock()
    fake_mootdx.quotes.return_value = None
    m = AshareMetrics(mootdx_client=fake_mootdx, akshare_module=MagicMock())
    q = m.get_quote("BOGUS.SH")
    assert q == {"price": None, "prev_close": None,
                 "volume": None, "avg_volume_10d": None}


def test_get_fundamentals_calls_akshare():
    """akshare returns a DataFrame — wrap it through __getitem__ mocks."""
    from src.screener.ashare_metrics import AshareMetrics
    import pandas as pd
    fake_ak = MagicMock()
    fake_ak.stock_individual_info_em.return_value = pd.DataFrame(
        {"item": ["总市值", "市盈率(动)", "市净率", "行业"],
         "value": [2.12e12, 28.5, 8.2, "白酒"]}
    )
    m = AshareMetrics(mootdx_client=MagicMock(), akshare_module=fake_ak)
    f = m.get_fundamentals("600519")
    assert f["market_cap"] == 2.12e12
    assert f["pe_ttm"] == 28.5
    assert f["pb"] == 8.2
    assert f["sector"] == "白酒"
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_snapshot_builder_cn.py tests/screener/test_ashare_metrics.py -v
```
Expected: ImportError for AshareMetrics + NotImplementedError for build_for_ticker_cn.

- [ ] **Step 3: Implement AshareMetrics wrapper**

Create `src/screener/ashare_metrics.py`:

```python
"""AshareMetrics — thin wrapper around mootdx + akshare for the CN path.

We keep this separate from snapshot_builder.py so the mootdx /
akshare imports are localized (heavy + optional install). Returns plain
dicts; SnapshotBuilder maps them to SnapshotRow.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


_AK_FIELD_MAP = {
    "总市值": "market_cap",
    "市盈率(动)": "pe_ttm",
    "市净率": "pb",
    "市销率": "ps",
    "PEG值": "peg",
    "净资产收益率": "roe",
    "销售毛利率": "profit_margin",
    "股息率": "dividend_yield_pct",
    "行业": "sector",
    "Beta": "beta",
}


class AshareMetrics:
    """Wraps mootdx (quotes) + akshare (fundamentals + earnings).

    Mootdx returns volume in 手 (1 手 = 100 shares); we multiply.
    Akshare's stock_individual_info_em returns a tall DataFrame
    [item, value]; we map known item names to our dict keys.
    """

    def __init__(self, *, mootdx_client=None, akshare_module=None) -> None:
        if mootdx_client is None:
            from mootdx.quotes import Quotes
            mootdx_client = Quotes.factory(market="std")
        if akshare_module is None:
            import akshare as akshare_module
        self._mootdx = mootdx_client
        self._ak = akshare_module

    @staticmethod
    def _strip_suffix(symbol: str) -> str:
        return symbol.split(".", 1)[0]

    def get_quote(self, symbol: str) -> dict[str, Any]:
        code = self._strip_suffix(symbol)
        try:
            q = self._mootdx.quotes(symbol=code)
        except Exception as e:
            logger.debug("mootdx.quotes failed for %s: %s", symbol, e)
            q = None
        if not q:
            return {"price": None, "prev_close": None,
                    "volume": None, "avg_volume_10d": None}
        price = q.get("price") or q.get("now")
        prev = q.get("last_close") or q.get("prev_close")
        vol_lots = q.get("vol") or q.get("volume") or 0
        return {
            "price": price,
            "prev_close": prev,
            "volume": int(vol_lots) * 100 if vol_lots else None,
            "avg_volume_10d": None,  # mootdx single-quote has no 10d avg
        }

    def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        code = self._strip_suffix(symbol)
        try:
            df = self._ak.stock_individual_info_em(symbol=code)
        except Exception as e:
            logger.debug("akshare fundamentals failed for %s: %s", symbol, e)
            return {}
        if df is None or df.empty:
            return {}
        out: dict[str, Any] = {}
        for _, r in df.iterrows():
            key = _AK_FIELD_MAP.get(str(r.get("item", "")))
            if key:
                out[key] = r.get("value")
        # Exchange inferred from symbol
        if symbol.endswith(".SH") or code.startswith(("6", "9")):
            out["exchange"] = "SSE"
        elif symbol.endswith(".SZ") or code.startswith(("0", "3")):
            out["exchange"] = "SZSE"
        elif symbol.endswith(".BJ") or code.startswith("8"):
            out["exchange"] = "BSE"
        return out

    def get_perf_windows(self, symbol: str, asof: date) -> dict[str, Any]:
        """Compute perf_{1d,5d,1m,3m,ytd,1y} from akshare daily hist."""
        code = self._strip_suffix(symbol)
        try:
            df = self._ak.stock_zh_a_hist(symbol=code, period="daily",
                                          adjust="qfq",
                                          end_date=asof.strftime("%Y%m%d"))
        except Exception as e:
            logger.debug("akshare hist failed for %s: %s", symbol, e)
            return {}
        if df is None or df.empty or "收盘" not in df.columns:
            return {}
        closes = df["收盘"].astype(float).tolist()
        if not closes:
            return {}
        last = closes[-1]

        def _ago(n: int):
            if len(closes) <= n:
                return None
            prev = closes[-1 - n]
            return (last - prev) / prev if prev else None

        ytd = None
        try:
            dates = df["日期"].astype(str).tolist()
            this_year = str(asof.year)
            start_idx = next(i for i, d in enumerate(dates) if d.startswith(this_year))
            prev = closes[start_idx]
            ytd = (last - prev) / prev if prev else None
        except StopIteration:
            ytd = None

        return {
            "perf_1d": _ago(1), "perf_5d": _ago(5),
            "perf_1m": _ago(21), "perf_3m": _ago(63),
            "perf_ytd": ytd, "perf_1y": _ago(252),
        }

    def get_earnings_dates(self, symbol: str) -> tuple[date | None, date | None]:
        """Returns (recent, upcoming). Both can be None."""
        # akshare's earnings calendar endpoint is unstable; v1 returns None.
        # Phase 2 will wire akshare.stock_yjbb_em if needed.
        return (None, None)
```

- [ ] **Step 4: Add `build_for_ticker_cn` to SnapshotBuilder**

Open `src/screener/snapshot_builder.py`. Replace the placeholder
`build_for_ticker_cn` method (the one that raises `NotImplementedError`) with:

```python
    def build_for_ticker_cn(self, ticker: str, asof: date) -> SnapshotRow:
        """Pull mootdx quote + akshare fundamentals into SnapshotRow."""
        if self._ashare is None:
            raise RuntimeError("ashare_metrics required for CN path")

        q = self._ashare.get_quote(ticker)
        f = self._ashare.get_fundamentals(ticker)
        p = self._ashare.get_perf_windows(ticker, asof)
        recent_ed, upcoming_ed = self._ashare.get_earnings_dates(ticker)

        price = _to_decimal(q.get("price"), scale=4)
        prev = _to_decimal(q.get("prev_close"), scale=4)
        change_pct = None
        if price is not None and prev is not None and prev != 0:
            change_pct = _to_decimal((float(price) - float(prev)) / float(prev), scale=4)

        return SnapshotRow(
            ticker=ticker,
            market="CN",
            snapshot_date=asof,
            price=price,
            prev_close=prev,
            change_pct=change_pct,
            volume=_to_int(q.get("volume")),
            avg_volume_10d=_to_int(q.get("avg_volume_10d")),
            rel_volume=None,
            market_cap=_to_decimal(f.get("market_cap"), scale=2),
            pe_ttm=_to_decimal(f.get("pe_ttm"), scale=3),
            pe_forward=None,
            pb=_to_decimal(f.get("pb"), scale=3),
            ps=_to_decimal(f.get("ps"), scale=3),
            peg=_to_decimal(f.get("peg"), scale=3),
            eps_growth_yoy=_to_decimal(f.get("eps_growth_yoy"), scale=4),
            revenue_growth_yoy=_to_decimal(f.get("revenue_growth_yoy"), scale=4),
            roe=_to_decimal(f.get("roe"), scale=4),
            profit_margin=_to_decimal(f.get("profit_margin"), scale=4),
            dividend_yield_pct=_to_decimal(f.get("dividend_yield_pct"), scale=4),
            beta=_to_decimal(f.get("beta"), scale=3),
            sector=f.get("sector"),
            industry=f.get("industry"),
            exchange=f.get("exchange"),
            analyst_rating=None,        # A-share lacks consensus rating
            analyst_count=None,
            target_mean_price=None,
            recent_earnings_date=recent_ed,
            upcoming_earnings_date=upcoming_ed,
            perf_1d=_to_decimal(p.get("perf_1d"), scale=4),
            perf_5d=_to_decimal(p.get("perf_5d"), scale=4),
            perf_1m=_to_decimal(p.get("perf_1m"), scale=4),
            perf_3m=_to_decimal(p.get("perf_3m"), scale=4),
            perf_ytd=_to_decimal(p.get("perf_ytd"), scale=4),
            perf_1y=_to_decimal(p.get("perf_1y"), scale=4),
            data_source="mootdx+akshare",
        )
```

- [ ] **Step 5: Run tests to verify pass**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_snapshot_builder_cn.py tests/screener/test_ashare_metrics.py -v
```
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/screener/ashare_metrics.py src/screener/snapshot_builder.py tests/screener/test_snapshot_builder_cn.py tests/screener/test_ashare_metrics.py
git commit -m "feat(screener): SnapshotBuilder CN path via mootdx + akshare"
```

---

## Task 5: Column metadata + Pydantic schemas

**Depends on:** Task 1.

**Files:**
- Create: `src/screener/column_metadata.py`
- Create: `app/backend/models/screener_schemas.py`
- Test: `tests/screener/test_column_metadata.py`

- [ ] **Step 1: Write the failing test**

Create `tests/screener/test_column_metadata.py`:

```python
"""Column metadata smoke test — verifies 16-chip shape + bilingual labels."""
from __future__ import annotations


def test_chip_count():
    from src.screener.column_metadata import COLUMN_METADATA
    assert len(COLUMN_METADATA) == 16


def test_chip_required_fields():
    from src.screener.column_metadata import COLUMN_METADATA
    for chip in COLUMN_METADATA:
        assert "slug" in chip
        assert "label_en" in chip
        assert "label_zh" in chip
        assert "kind" in chip
        assert chip["kind"] in ("range", "multi_select", "date_range")


def test_known_chips_present():
    from src.screener.column_metadata import COLUMN_METADATA
    slugs = {c["slug"] for c in COLUMN_METADATA}
    assert {"price", "chg_pct", "mcap", "pe", "eps_growth",
            "div_yield", "sector", "analyst_rating",
            "perf_1d", "revenue_growth", "peg", "roe", "beta",
            "recent_earnings", "upcoming_earnings"}.issubset(slugs)


def test_range_chips_have_step():
    from src.screener.column_metadata import COLUMN_METADATA
    for c in COLUMN_METADATA:
        if c["kind"] == "range":
            assert "step" in c
            assert "format" in c  # e.g. 'currency' | 'percent' | 'multiplier'


def test_multi_select_options():
    from src.screener.column_metadata import COLUMN_METADATA
    sector = next(c for c in COLUMN_METADATA if c["slug"] == "sector")
    assert "options_us" in sector and len(sector["options_us"]) > 5
    rating = next(c for c in COLUMN_METADATA if c["slug"] == "analyst_rating")
    assert set(o["value"] for o in rating["options"]) == {
        "strong_buy", "buy", "neutral", "sell", "strong_sell",
    }
```

Also create `tests/screener/test_screener_schemas.py`:

```python
"""Pydantic schema smoke."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal


def test_snapshot_row_out_construction():
    from app.backend.models.screener_schemas import SnapshotRowOut
    out = SnapshotRowOut(
        ticker="AAPL", market="US", snapshot_date=date(2026, 5, 27),
        price=Decimal("210.50"), market_cap=Decimal("3.2e12"),
        sector="Technology",
    )
    payload = out.model_dump()
    assert payload["ticker"] == "AAPL"
    assert payload["pe_ttm"] is None


def test_snapshot_response_envelope():
    from app.backend.models.screener_schemas import (
        ScreenerSnapshotResponse, SnapshotRowOut,
    )
    resp = ScreenerSnapshotResponse(
        rows=[],
        total_count=0,
        snapshot_date=date(2026, 5, 27),
        last_updated=datetime.utcnow(),
    )
    assert resp.total_count == 0


def test_status_response():
    from app.backend.models.screener_schemas import ScreenerStatusResponse
    s = ScreenerStatusResponse(
        snapshot_date=date(2026, 5, 27),
        last_updated=datetime.utcnow(),
        row_count=800,
        by_market={"US": 500, "CN": 300},
    )
    assert s.by_market["US"] == 500
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_column_metadata.py tests/screener/test_screener_schemas.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement column_metadata.py**

Create `src/screener/column_metadata.py`:

```python
"""Static metadata for the 16 Screener chips.

Single source of truth for: chip kind, display labels (en/zh), data
type, format hint, step, min/max bounds, multi-select option lists.
The /screener/snapshot/columns endpoint serves this directly.
"""

from __future__ import annotations

from typing import Any


_GICS_SECTORS_US = [
    "Technology", "Healthcare", "Financial Services", "Consumer Cyclical",
    "Communication Services", "Industrials", "Consumer Defensive",
    "Energy", "Utilities", "Real Estate", "Basic Materials",
]

_SHENWAN_SECTORS_CN = [
    "白酒", "食品饮料", "银行", "电力设备", "电子", "医药生物",
    "汽车", "计算机", "通信", "传媒", "化工", "钢铁", "有色金属",
    "国防军工", "建筑材料", "公用事业", "房地产", "商贸零售",
    "纺织服饰", "轻工制造", "机械设备", "煤炭", "石油石化",
    "交通运输", "农林牧渔", "社会服务", "美容护理", "环保",
    "综合", "非银金融",
]

_ANALYST_RATINGS = [
    {"value": "strong_buy",   "label_en": "Strong Buy",   "label_zh": "强力买入"},
    {"value": "buy",          "label_en": "Buy",          "label_zh": "买入"},
    {"value": "neutral",      "label_en": "Neutral",      "label_zh": "中性"},
    {"value": "sell",         "label_en": "Sell",         "label_zh": "卖出"},
    {"value": "strong_sell",  "label_en": "Strong Sell",  "label_zh": "强力卖出"},
]


COLUMN_METADATA: list[dict[str, Any]] = [
    # ---- Row 1 ----
    {"slug": "price", "label_en": "Price", "label_zh": "价格",
     "kind": "range", "format": "currency", "step": 1,
     "filter_min": "price_min", "filter_max": "price_max"},
    {"slug": "chg_pct", "label_en": "Chg %", "label_zh": "涨跌幅",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "chg_pct_min", "filter_max": "chg_pct_max"},
    {"slug": "mcap", "label_en": "Mkt cap", "label_zh": "市值",
     "kind": "range", "format": "abbreviated_currency", "step": 1e9,
     "filter_min": "mcap_min", "filter_max": "mcap_max"},
    {"slug": "pe", "label_en": "P/E", "label_zh": "市盈率",
     "kind": "range", "format": "multiplier", "step": 1,
     "filter_min": "pe_min", "filter_max": "pe_max"},
    {"slug": "eps_growth", "label_en": "EPS dil growth", "label_zh": "EPS 增长",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "eps_growth_min", "filter_max": "eps_growth_max"},
    {"slug": "div_yield", "label_en": "Div yield %", "label_zh": "股息率",
     "kind": "range", "format": "percent", "step": 0.001,
     "filter_min": "div_yield_min", "filter_max": "div_yield_max"},
    {"slug": "sector", "label_en": "Sector", "label_zh": "板块",
     "kind": "multi_select", "filter_key": "sector_in",
     "options_us": [{"value": s, "label_en": s, "label_zh": s} for s in _GICS_SECTORS_US],
     "options_cn": [{"value": s, "label_en": s, "label_zh": s} for s in _SHENWAN_SECTORS_CN]},
    {"slug": "analyst_rating", "label_en": "Analyst rating", "label_zh": "分析师评级",
     "kind": "multi_select", "filter_key": "analyst_rating_in",
     "options": _ANALYST_RATINGS},
    {"slug": "perf_1d", "label_en": "Perf 1D", "label_zh": "1 日表现",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "perf_1d_min", "filter_max": "perf_1d_max"},

    # ---- Row 2 ----
    {"slug": "revenue_growth", "label_en": "Revenue growth", "label_zh": "营收增长",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "revenue_growth_min", "filter_max": "revenue_growth_max"},
    {"slug": "peg", "label_en": "PEG", "label_zh": "PEG",
     "kind": "range", "format": "multiplier", "step": 0.1,
     "filter_min": "peg_min", "filter_max": "peg_max"},
    {"slug": "roe", "label_en": "ROE", "label_zh": "ROE",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "roe_min", "filter_max": "roe_max"},
    {"slug": "beta", "label_en": "Beta", "label_zh": "Beta",
     "kind": "range", "format": "multiplier", "step": 0.1,
     "filter_min": "beta_min", "filter_max": "beta_max"},
    {"slug": "recent_earnings", "label_en": "Recent earnings", "label_zh": "上次财报",
     "kind": "date_range",
     "filter_after": "recent_earnings_after", "filter_before": "recent_earnings_before"},
    {"slug": "upcoming_earnings", "label_en": "Upcoming earnings", "label_zh": "下次财报",
     "kind": "date_range",
     "filter_after": "upcoming_earnings_after", "filter_before": "upcoming_earnings_before"},
    {"slug": "perf_extended", "label_en": "Perf 5D/1M/3M/YTD/1Y", "label_zh": "扩展表现",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "perf_1y_min", "filter_max": "perf_1y_max"},
]
```

- [ ] **Step 4: Implement Pydantic schemas**

Create `app/backend/models/screener_schemas.py`:

```python
"""Pydantic schemas for /screener endpoints. Mirrors TickerSnapshot
fields 1:1 (minus `id` and `last_updated`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class SnapshotRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class ScreenerSnapshotResponse(BaseModel):
    rows: list[SnapshotRowOut]
    total_count: int
    snapshot_date: date
    last_updated: datetime


class ScreenerStatusResponse(BaseModel):
    snapshot_date: date | None
    last_updated: datetime | None
    row_count: int
    by_market: dict[str, int]


class ScreenerColumnMetadata(BaseModel):
    columns: list[dict[str, Any]]
```

- [ ] **Step 5: Run tests to verify pass**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_column_metadata.py tests/screener/test_screener_schemas.py -v
```
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/screener/column_metadata.py app/backend/models/screener_schemas.py tests/screener/test_column_metadata.py tests/screener/test_screener_schemas.py
git commit -m "feat(screener): column metadata + Pydantic schemas"
```

---

## Task 6: REST routes

**Depends on:** Tasks 2, 5.

**Files:**
- Create: `app/backend/routes/screener.py`
- Modify: `app/backend/routes/__init__.py` (register router)
- Test: `tests/screener/test_routes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/screener/test_routes.py`:

```python
"""Screener route tests — TestClient against an in-memory SQLite DB."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database import get_db
from app.backend.database.models import Base
from app.backend.repositories.screener_repository import ScreenerRepository, SnapshotRow
from app.backend.routes.screener import router as screener_router


@pytest.fixture()
def client_and_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(screener_router)
    app.dependency_overrides[get_db] = override_get_db

    db = TestingSession()
    repo = ScreenerRepository(db)
    repo.bulk_upsert([
        SnapshotRow(ticker="AAPL", market="US", snapshot_date=date(2026, 5, 27),
                    price=Decimal("210"), market_cap=Decimal("3.2e12"),
                    pe_ttm=Decimal("32"), sector="Technology",
                    analyst_rating="buy", data_source="yfinance"),
        SnapshotRow(ticker="JPM", market="US", snapshot_date=date(2026, 5, 27),
                    price=Decimal("180"), market_cap=Decimal("5.0e11"),
                    pe_ttm=Decimal("11"), sector="Financial Services",
                    analyst_rating="neutral", data_source="yfinance"),
        SnapshotRow(ticker="600519.SH", market="CN", snapshot_date=date(2026, 5, 27),
                    price=Decimal("1700"), market_cap=Decimal("2.1e12"),
                    pe_ttm=Decimal("28"), sector="白酒",
                    data_source="mootdx+akshare"),
    ])
    db.close()

    yield TestClient(app), TestingSession


def test_get_columns_returns_16_chips(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/columns")
    assert r.status_code == 200
    body = r.json()
    assert len(body["columns"]) == 16


def test_get_status_reports_counts(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/status")
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == 3
    assert body["by_market"] == {"US": 2, "CN": 1}


def test_get_latest_no_filter_returns_all(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 3
    assert len(body["rows"]) == 3


def test_get_latest_market_filter(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?market=CN")
    body = r.json()
    assert body["total_count"] == 1
    assert body["rows"][0]["ticker"] == "600519.SH"


def test_get_latest_range_filter(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?market=US&pe_max=20")
    body = r.json()
    assert body["total_count"] == 1
    assert body["rows"][0]["ticker"] == "JPM"


def test_get_latest_multi_select_filter(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?sector_in=Technology,Financial%20Services")
    body = r.json()
    assert {row["ticker"] for row in body["rows"]} == {"AAPL", "JPM"}


def test_get_latest_sort_desc(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?sort_by=market_cap&sort_dir=desc&limit=10")
    body = r.json()
    tickers = [row["ticker"] for row in body["rows"]]
    assert tickers[0] in ("AAPL", "600519.SH")  # both 2T+ mcap


def test_get_latest_invalid_market_returns_422(client_and_db):
    client, _ = client_and_db
    r = client.get("/screener/snapshot/latest?market=XX")
    assert r.status_code == 422


def test_get_latest_empty_db_returns_empty(client_and_db):
    client, TestingSession = client_and_db
    db = TestingSession()
    from app.backend.database.models import TickerSnapshot
    db.query(TickerSnapshot).delete()
    db.commit()
    db.close()
    r = client.get("/screener/snapshot/latest")
    assert r.status_code == 200
    assert r.json()["total_count"] == 0
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_routes.py -v
```
Expected: ImportError for screener router.

- [ ] **Step 3: Implement route**

Create `app/backend/routes/screener.py`:

```python
"""/screener REST endpoints.

  GET /screener/snapshot/latest    — filtered query (chip-driven)
  GET /screener/snapshot/columns   — static chip metadata
  GET /screener/snapshot/status    — last-built timestamp + per-market counts
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.database.models import TickerSnapshot
from app.backend.models.screener_schemas import (
    ScreenerColumnMetadata,
    ScreenerSnapshotResponse,
    ScreenerStatusResponse,
    SnapshotRowOut,
)
from app.backend.repositories.screener_repository import ScreenerRepository
from src.screener.column_metadata import COLUMN_METADATA

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/screener")


_RESERVED_QUERY_KEYS = {"market", "sort_by", "sort_dir", "limit", "offset"}


def _parse_filters(request: Request) -> dict:
    """Pull every non-reserved query param into the filters dict.
    Multi-value 'sector_in' / 'analyst_rating_in' are CSV-split.
    """
    filters: dict = {}
    for k, v in request.query_params.multi_items():
        if k in _RESERVED_QUERY_KEYS:
            continue
        if k.endswith("_in"):
            filters[k] = [x.strip() for x in v.split(",") if x.strip()]
        else:
            filters[k] = v
    return filters


@router.get("/snapshot/latest", response_model=ScreenerSnapshotResponse)
def get_latest_snapshot(
    request: Request,
    market: Annotated[str | None, Query(pattern="^(US|CN|ALL)$")] = None,
    sort_by: str = "market_cap",
    sort_dir: str = "desc",
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ScreenerSnapshotResponse:
    repo = ScreenerRepository(db)

    market_list: list[str] | None
    if market is None or market == "ALL":
        market_list = None
    else:
        market_list = [market]

    filters = _parse_filters(request)
    rows, total = repo.query(
        market=market_list,
        filters=filters,
        sort_by=sort_by,
        sort_dir=sort_dir if sort_dir in ("asc", "desc") else "desc",
        limit=limit,
        offset=offset,
    )

    if rows:
        snapshot_date = rows[0].snapshot_date
        last_updated = max((r.last_updated for r in rows if r.last_updated),
                           default=datetime.utcnow())
    else:
        snapshot_date = repo.latest_snapshot_date(
            market=market_list[0] if market_list and len(market_list) == 1 else None,
        ) or date.today()
        last_updated = datetime.utcnow()

    return ScreenerSnapshotResponse(
        rows=[SnapshotRowOut.model_validate(r) for r in rows],
        total_count=total,
        snapshot_date=snapshot_date,
        last_updated=last_updated,
    )


@router.get("/snapshot/columns", response_model=ScreenerColumnMetadata)
def get_column_metadata() -> ScreenerColumnMetadata:
    return ScreenerColumnMetadata(columns=COLUMN_METADATA)


@router.get("/snapshot/status", response_model=ScreenerStatusResponse)
def get_snapshot_status(db: Session = Depends(get_db)) -> ScreenerStatusResponse:
    repo = ScreenerRepository(db)
    snapshot_date = repo.latest_snapshot_date()

    row_count = 0
    by_market: dict[str, int] = {}
    last_updated: datetime | None = None
    if snapshot_date is not None:
        result = db.execute(
            select(TickerSnapshot.market, func.count(), func.max(TickerSnapshot.last_updated))
            .where(TickerSnapshot.snapshot_date == snapshot_date)
            .group_by(TickerSnapshot.market)
        ).all()
        for mkt, n, lu in result:
            by_market[mkt] = int(n)
            row_count += int(n)
            if lu is not None and (last_updated is None or lu > last_updated):
                last_updated = lu

    return ScreenerStatusResponse(
        snapshot_date=snapshot_date,
        last_updated=last_updated,
        row_count=row_count,
        by_market=by_market,
    )
```

- [ ] **Step 4: Register router**

Open `app/backend/routes/__init__.py`. Add the import next to the others:

```python
from app.backend.routes.screener import router as screener_phase1_router
```

And register it next to the existing `include_router` lines:

```python
api_router.include_router(screener_phase1_router, tags=["screener"])
```

Use the name `screener_phase1_router` to avoid colliding with the existing
`scanner_router` import (the Scanner panel's REST router).

- [ ] **Step 5: Run tests to verify pass**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_routes.py -v
```
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add app/backend/routes/screener.py app/backend/routes/__init__.py tests/screener/test_routes.py
git commit -m "feat(screener): 3 REST endpoints (snapshot/latest, columns, status)"
```

---

## Task 7: Scheduler cron job

**Depends on:** Tasks 2, 3, 4.

**Files:**
- Modify: `app/backend/services/scheduler_service.py` (add cron + handler)
- Test: `tests/screener/test_scheduler_integration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/screener/test_scheduler_integration.py`:

```python
"""Verify the screener snapshot cron registers + dispatches builder + cleanup."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.backend.repositories.screener_repository import SnapshotRow


def test_constants_present():
    from app.backend.services.scheduler_service import (
        SCREENER_SNAPSHOT_CRON_EXPR,
        SCREENER_SNAPSHOT_JOB_ID,
    )
    assert SCREENER_SNAPSHOT_CRON_EXPR == "0 22 * * *"
    assert SCREENER_SNAPSHOT_JOB_ID == "screener_snapshot"


def test_run_snapshot_job_builds_both_markets_and_cleans_up():
    from app.backend.services import scheduler_service

    fake_us_rows = [
        SnapshotRow(ticker="AAPL", market="US", snapshot_date=date(2026, 5, 27))
    ]
    fake_cn_rows = [
        SnapshotRow(ticker="600519.SH", market="CN", snapshot_date=date(2026, 5, 27))
    ]
    fake_builder = MagicMock()
    fake_builder.build_for_universe.side_effect = [fake_us_rows, fake_cn_rows]
    fake_repo = MagicMock()
    fake_repo.bulk_upsert.return_value = 1
    fake_repo.cleanup_old_snapshots.return_value = 0
    fake_db = MagicMock()

    with patch.object(scheduler_service, "SessionLocal", return_value=fake_db), \
         patch.object(scheduler_service, "ScreenerRepository", return_value=fake_repo), \
         patch.object(scheduler_service, "SnapshotBuilder", return_value=fake_builder), \
         patch.object(scheduler_service, "AshareMetrics", return_value=MagicMock()):
        scheduler_service._run_snapshot_job_body()

    # Both markets dispatched in order
    calls = fake_builder.build_for_universe.call_args_list
    assert calls[0].args[0] == "US"
    assert calls[0].args[1] == "sp500"
    assert calls[1].args[0] == "CN"
    assert calls[1].args[1] == "csi300"

    # Upsert called twice (once per market)
    assert fake_repo.bulk_upsert.call_count == 2
    fake_repo.cleanup_old_snapshots.assert_called_once_with(keep_days=30)
    fake_db.close.assert_called_once()


def test_run_snapshot_job_us_failure_doesnt_block_cn():
    from app.backend.services import scheduler_service

    fake_builder = MagicMock()
    fake_builder.build_for_universe.side_effect = [
        RuntimeError("yfinance down"),
        [SnapshotRow(ticker="600519.SH", market="CN", snapshot_date=date(2026, 5, 27))],
    ]
    fake_repo = MagicMock()
    fake_repo.bulk_upsert.return_value = 1
    fake_repo.cleanup_old_snapshots.return_value = 0

    with patch.object(scheduler_service, "SessionLocal", return_value=MagicMock()), \
         patch.object(scheduler_service, "ScreenerRepository", return_value=fake_repo), \
         patch.object(scheduler_service, "SnapshotBuilder", return_value=fake_builder), \
         patch.object(scheduler_service, "AshareMetrics", return_value=MagicMock()):
        scheduler_service._run_snapshot_job_body()

    # CN still ran + upserted; cleanup still ran.
    assert fake_repo.bulk_upsert.call_count == 1
    fake_repo.cleanup_old_snapshots.assert_called_once()


def test_scheduler_registers_snapshot_job():
    """When SchedulerService starts, it adds the snapshot job via add_job."""
    from app.backend.services.scheduler_service import (
        SchedulerService,
        SCREENER_SNAPSHOT_JOB_ID,
    )

    fake_scanner = MagicMock()
    svc = SchedulerService(session_factory=MagicMock(),
                           scanner_service=fake_scanner)
    # Patch the scheduler's add_job so we don't actually launch APScheduler
    with patch.object(svc, "_scheduler") as fake_scheduler:
        fake_scheduler.get_jobs.return_value = []
        svc.start()

    job_ids = [c.kwargs.get("id") or (c.args[2] if len(c.args) >= 3 else None)
               for c in fake_scheduler.add_job.call_args_list]
    assert SCREENER_SNAPSHOT_JOB_ID in job_ids
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_scheduler_integration.py -v
```
Expected: ImportError for `SCREENER_SNAPSHOT_CRON_EXPR`.

- [ ] **Step 3: Add screener cron to scheduler_service.py**

Open `app/backend/services/scheduler_service.py`. Near the existing
`PIPELINE_CRON_EXPR` / `RESEARCH_CRON_EXPR` constants, append:

```python
# Daily screener-snapshot cron: 22:00 ET every day. Runs after both US
# close (16:00 ET) and CN close (15:00 CST = 03:00 ET next day → previous
# session captured by then). Weekend runs are idempotent — they re-pull
# Friday's close.
SCREENER_SNAPSHOT_CRON_EXPR = "0 22 * * *"
SCREENER_SNAPSHOT_JOB_ID = "screener_snapshot"
```

Add the new imports near the top of the file (alongside other
research/pipeline imports):

```python
from app.backend.repositories.screener_repository import ScreenerRepository
from src.screener.ashare_metrics import AshareMetrics
from src.screener.snapshot_builder import SnapshotBuilder
```

Add the job body as a module-level function (next to
`_run_research_job_body`):

```python
def _run_snapshot_job_body() -> None:
    """Build US then CN snapshot; per-market failures log + continue.
    Cleanup deletes rows older than 30 days. One DB session for the whole job.
    """
    from datetime import date as _date

    db = SessionLocal()
    try:
        repo = ScreenerRepository(db)
        try:
            ashare = AshareMetrics()
        except Exception as e:
            logger.warning("AshareMetrics init failed (CN path disabled): %s", e)
            ashare = None
        builder = SnapshotBuilder(ashare_metrics=ashare)
        asof = _date.today()

        for market, kind in (("US", "sp500"), ("CN", "csi300")):
            try:
                rows = builder.build_for_universe(market, kind, asof)
                inserted = repo.bulk_upsert(rows)
                logger.info("screener snapshot %s: %d rows", market, inserted)
            except Exception as e:
                logger.exception("screener snapshot %s failed: %s", market, e)

        deleted = repo.cleanup_old_snapshots(keep_days=30)
        logger.info("screener snapshot cleanup deleted %d old rows", deleted)
    finally:
        db.close()
```

Inside the `SchedulerService.start()` method (find where it adds the
research job — the snippet near line 240 with `_run_research_job_body`),
add a third `add_job` block immediately after the research one:

```python
        trigger = CronTrigger.from_crontab(SCREENER_SNAPSHOT_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            _run_snapshot_job_body,
            trigger=trigger,
            id=SCREENER_SNAPSHOT_JOB_ID,
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info(
            "Registered cron job %s with expression %s (timezone=%s)",
            SCREENER_SNAPSHOT_JOB_ID, SCREENER_SNAPSHOT_CRON_EXPR, self._tz,
        )
```

- [ ] **Step 4: Run tests to verify pass**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_scheduler_integration.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backend/services/scheduler_service.py tests/screener/test_scheduler_integration.py
git commit -m "feat(screener): nightly snapshot cron at 22:00 ET"
```

---

## Task 8: Frontend types + screener-service

**Depends on:** Task 6.

**Files:**
- Create: `app/frontend/src/types/screener.ts`
- Create: `app/frontend/src/services/screener-service.ts`

No backend test stage here — front-end services aren't TDD'd in this repo.
The integration is validated via the e2e smoke in Task 14.

- [ ] **Step 1: Create the TypeScript types**

Create `app/frontend/src/types/screener.ts`:

```typescript
export type Market = 'US' | 'CN' | 'ALL';

export type AnalystRating =
  | 'strong_buy' | 'buy' | 'neutral' | 'sell' | 'strong_sell';

export interface SnapshotRow {
  ticker: string;
  market: 'US' | 'CN';
  snapshot_date: string;

  price: string | null;
  prev_close: string | null;
  change_pct: string | null;
  volume: number | null;
  avg_volume_10d: number | null;
  rel_volume: string | null;

  market_cap: string | null;
  pe_ttm: string | null;
  pe_forward: string | null;
  pb: string | null;
  ps: string | null;
  peg: string | null;

  eps_growth_yoy: string | null;
  revenue_growth_yoy: string | null;
  roe: string | null;
  profit_margin: string | null;
  dividend_yield_pct: string | null;
  beta: string | null;

  sector: string | null;
  industry: string | null;
  exchange: string | null;

  analyst_rating: AnalystRating | null;
  analyst_count: number | null;
  target_mean_price: string | null;

  recent_earnings_date: string | null;
  upcoming_earnings_date: string | null;

  perf_1d: string | null;
  perf_5d: string | null;
  perf_1m: string | null;
  perf_3m: string | null;
  perf_ytd: string | null;
  perf_1y: string | null;

  data_source: string | null;
}

export interface ScreenerSnapshotResponse {
  rows: SnapshotRow[];
  total_count: number;
  snapshot_date: string;
  last_updated: string;
}

export interface ScreenerStatusResponse {
  snapshot_date: string | null;
  last_updated: string | null;
  row_count: number;
  by_market: Record<string, number>;
}

export type ChipKind = 'range' | 'multi_select' | 'date_range';

export interface ChipOption {
  value: string;
  label_en: string;
  label_zh: string;
}

export interface ColumnMetadata {
  slug: string;
  label_en: string;
  label_zh: string;
  kind: ChipKind;
  format?: 'currency' | 'percent' | 'multiplier' | 'abbreviated_currency';
  step?: number;
  filter_min?: string;
  filter_max?: string;
  filter_key?: string;       // multi_select
  filter_after?: string;     // date_range
  filter_before?: string;    // date_range
  options?: ChipOption[];
  options_us?: ChipOption[];
  options_cn?: ChipOption[];
}

export interface ColumnMetadataResponse {
  columns: ColumnMetadata[];
}

/** Local filter state per chip slug. Sent to the API as flat query params. */
export type ChipValues = Record<string, string | number | string[] | null>;
```

- [ ] **Step 2: Create the REST client**

Create `app/frontend/src/services/screener-service.ts`:

```typescript
import {
  ColumnMetadataResponse,
  Market,
  ScreenerSnapshotResponse,
  ScreenerStatusResponse,
  ChipValues,
} from '@/types/screener';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';

function chipValuesToQuery(values: ChipValues): URLSearchParams {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === '' || v === undefined) continue;
    if (Array.isArray(v)) {
      if (v.length > 0) sp.append(k, v.join(','));
    } else {
      sp.append(k, String(v));
    }
  }
  return sp;
}

export interface SnapshotQuery {
  market?: Market;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
  filters?: ChipValues;
}

export async function getLatestSnapshot(q: SnapshotQuery = {}): Promise<ScreenerSnapshotResponse> {
  const sp = chipValuesToQuery(q.filters || {});
  if (q.market) sp.set('market', q.market);
  if (q.sort_by) sp.set('sort_by', q.sort_by);
  if (q.sort_dir) sp.set('sort_dir', q.sort_dir);
  if (q.limit !== undefined) sp.set('limit', String(q.limit));
  if (q.offset !== undefined) sp.set('offset', String(q.offset));

  const url = `${API_BASE}/screener/snapshot/latest?${sp.toString()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`screener snapshot failed: ${res.status}`);
  return res.json();
}

export async function getColumnMetadata(): Promise<ColumnMetadataResponse> {
  const res = await fetch(`${API_BASE}/screener/snapshot/columns`);
  if (!res.ok) throw new Error(`screener columns failed: ${res.status}`);
  return res.json();
}

export async function getSnapshotStatus(): Promise<ScreenerStatusResponse> {
  const res = await fetch(`${API_BASE}/screener/snapshot/status`);
  if (!res.ok) throw new Error(`screener status failed: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```powershell
cd app/frontend
npx tsc --noEmit
```
Expected: no new errors in `types/screener.ts` or `services/screener-service.ts`.

- [ ] **Step 4: Commit**

```bash
git add app/frontend/src/types/screener.ts app/frontend/src/services/screener-service.ts
git commit -m "feat(screener): frontend types + REST service client"
```

---

## Task 9: Frontend chip components

**Depends on:** Tasks 5, 8.

**Files:**
- Create: `app/frontend/src/components/panels/screener/chips/range-chip.tsx`
- Create: `app/frontend/src/components/panels/screener/chips/multi-select-chip.tsx`
- Create: `app/frontend/src/components/panels/screener/chips/date-range-chip.tsx`

No tests — these are presentational components verified via the e2e
smoke in Task 14.

- [ ] **Step 1: Create the range chip**

Create `app/frontend/src/components/panels/screener/chips/range-chip.tsx`:

```tsx
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { ColumnMetadata } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface RangeChipProps {
  meta: ColumnMetadata;
  minValue: number | null;
  maxValue: number | null;
  onChange: (min: number | null, max: number | null) => void;
}

export function RangeChip({ meta, minValue, maxValue, onChange }: RangeChipProps) {
  const { i18n } = useTranslation();
  const label = i18n.language === 'zh' ? meta.label_zh : meta.label_en;
  const active = minValue !== null || maxValue !== null;

  const labelSummary = active
    ? `${label} ${minValue ?? '...'}-${maxValue ?? '...'}`
    : label;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('rounded-full px-3 h-8 text-xs', active && 'border-primary text-primary')}
        >
          {labelSummary}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3 space-y-2">
        <div className="text-xs font-medium">{label}</div>
        <div className="flex gap-2 items-center">
          <Input
            type="number"
            step={meta.step ?? 1}
            value={minValue ?? ''}
            placeholder="Min"
            onChange={(e) =>
              onChange(e.target.value === '' ? null : Number(e.target.value), maxValue)
            }
            className="h-8 text-xs"
          />
          <span className="text-muted-foreground">—</span>
          <Input
            type="number"
            step={meta.step ?? 1}
            value={maxValue ?? ''}
            placeholder="Max"
            onChange={(e) =>
              onChange(minValue, e.target.value === '' ? null : Number(e.target.value))
            }
            className="h-8 text-xs"
          />
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="w-full h-7 text-xs"
          onClick={() => onChange(null, null)}
        >
          Clear
        </Button>
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 2: Create the multi-select chip**

Create `app/frontend/src/components/panels/screener/chips/multi-select-chip.tsx`:

```tsx
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { ChipOption, ColumnMetadata, Market } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface MultiSelectChipProps {
  meta: ColumnMetadata;
  selectedValues: string[];
  market: Market;
  onChange: (values: string[]) => void;
}

export function MultiSelectChip({ meta, selectedValues, market, onChange }: MultiSelectChipProps) {
  const { i18n } = useTranslation();
  const isZh = i18n.language === 'zh';
  const label = isZh ? meta.label_zh : meta.label_en;

  let options: ChipOption[] = [];
  if (meta.options) options = meta.options;
  else if (market === 'CN' && meta.options_cn) options = meta.options_cn;
  else if (meta.options_us) options = meta.options_us;

  const active = selectedValues.length > 0;
  const summary = active ? `${label} (${selectedValues.length})` : label;

  const toggle = (value: string) => {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter((v) => v !== value));
    } else {
      onChange([...selectedValues, value]);
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('rounded-full px-3 h-8 text-xs', active && 'border-primary text-primary')}
        >
          {summary}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-2">
        <ScrollArea className="h-56">
          <div className="space-y-1">
            {options.map((o) => (
              <label key={o.value} className="flex items-center gap-2 px-1 py-1 text-xs cursor-pointer hover:bg-muted">
                <Checkbox
                  checked={selectedValues.includes(o.value)}
                  onCheckedChange={() => toggle(o.value)}
                />
                {isZh ? o.label_zh : o.label_en}
              </label>
            ))}
          </div>
        </ScrollArea>
        {active && (
          <Button variant="ghost" size="sm" className="w-full h-7 text-xs mt-1"
                  onClick={() => onChange([])}>
            Clear
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 3: Create the date-range chip**

Create `app/frontend/src/components/panels/screener/chips/date-range-chip.tsx`:

```tsx
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { ColumnMetadata } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface DateRangeChipProps {
  meta: ColumnMetadata;
  afterDate: string | null;
  beforeDate: string | null;
  onChange: (after: string | null, before: string | null) => void;
}

export function DateRangeChip({ meta, afterDate, beforeDate, onChange }: DateRangeChipProps) {
  const { i18n } = useTranslation();
  const label = i18n.language === 'zh' ? meta.label_zh : meta.label_en;
  const active = afterDate !== null || beforeDate !== null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('rounded-full px-3 h-8 text-xs', active && 'border-primary text-primary')}
        >
          {active ? `${label} ${afterDate ?? '...'} → ${beforeDate ?? '...'}` : label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3 space-y-2">
        <div className="text-xs font-medium">{label}</div>
        <div className="flex gap-2 items-center">
          <Input
            type="date"
            value={afterDate ?? ''}
            onChange={(e) => onChange(e.target.value || null, beforeDate)}
            className="h-8 text-xs"
          />
          <span className="text-muted-foreground">→</span>
          <Input
            type="date"
            value={beforeDate ?? ''}
            onChange={(e) => onChange(afterDate, e.target.value || null)}
            className="h-8 text-xs"
          />
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="w-full h-7 text-xs"
          onClick={() => onChange(null, null)}
        >
          Clear
        </Button>
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```powershell
cd app/frontend
npx tsc --noEmit
```
Expected: no new errors. If `@/components/ui/checkbox`, `popover`, or
`scroll-area` are missing from the existing shadcn setup, run
`npx shadcn-ui@latest add checkbox popover scroll-area` to install them.

- [ ] **Step 5: Commit**

```bash
git add app/frontend/src/components/panels/screener/chips/
git commit -m "feat(screener): range/multi-select/date-range chip components"
```

---

## Task 10: Frontend snapshot-table component

**Depends on:** Task 8.

**Files:**
- Create: `app/frontend/src/components/panels/screener/snapshot-table.tsx`

- [ ] **Step 1: Create the table component**

Create `app/frontend/src/components/panels/screener/snapshot-table.tsx`:

```tsx
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { useTabsContext } from '@/contexts/tabs-context';
import { cn } from '@/lib/utils';
import { SnapshotRow } from '@/types/screener';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface SnapshotTableProps {
  rows: SnapshotRow[];
  sortBy: string;
  sortDir: 'asc' | 'desc';
  onSort: (column: string) => void;
}

function fmtNum(v: string | null, digits = 2): string {
  if (v === null) return '—';
  const n = Number(v);
  if (!isFinite(n)) return '—';
  return n.toFixed(digits);
}

function fmtPct(v: string | null): string {
  if (v === null) return '—';
  const n = Number(v) * 100;
  if (!isFinite(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function fmtMcap(v: string | null): string {
  if (v === null) return '—';
  const n = Number(v);
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6)  return `${(n / 1e6).toFixed(2)}M`;
  return `${n.toFixed(0)}`;
}

function fmtVol(v: number | null): string {
  if (v === null) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return `${v}`;
}

const RATING_COLOR: Record<string, string> = {
  strong_buy:  'bg-green-600 text-white',
  buy:         'bg-green-500 text-white',
  neutral:     'bg-gray-400 text-white',
  sell:        'bg-orange-500 text-white',
  strong_sell: 'bg-red-600 text-white',
};

export function SnapshotTable({ rows, sortBy, sortDir, onSort }: SnapshotTableProps) {
  const { openTab } = useTabsContext();
  const { t } = useTranslation();

  const headerCell = (column: string, label: string, align: 'left' | 'right' = 'right') => {
    const isActive = sortBy === column;
    return (
      <TableHead
        className={cn('cursor-pointer select-none whitespace-nowrap',
                      align === 'right' ? 'text-right' : 'text-left',
                      isActive && 'text-primary')}
        onClick={() => onSort(column)}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {isActive && (sortDir === 'desc'
            ? <ChevronDown className="w-3 h-3" />
            : <ChevronUp className="w-3 h-3" />)}
        </span>
      </TableHead>
    );
  };

  return (
    <div className="border rounded-md overflow-x-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            {headerCell('ticker', t('screener.col.ticker', 'Ticker'), 'left')}
            <TableHead className="text-left">{t('screener.col.market', 'Mkt')}</TableHead>
            {headerCell('price', t('screener.col.price', 'Price'))}
            {headerCell('change_pct', t('screener.col.chg', 'Chg %'))}
            {headerCell('volume', t('screener.col.vol', 'Vol'))}
            {headerCell('market_cap', t('screener.col.mcap', 'Mkt cap'))}
            {headerCell('pe_ttm', t('screener.col.pe', 'P/E'))}
            {headerCell('eps_growth_yoy', t('screener.col.eps_g', 'EPS gro'))}
            {headerCell('dividend_yield_pct', t('screener.col.div', 'Div %'))}
            <TableHead className="text-left">{t('screener.col.sector', 'Sector')}</TableHead>
            <TableHead className="text-left">{t('screener.col.rating', 'Rating')}</TableHead>
            {headerCell('perf_1m', t('screener.col.perf_1m', '1M'))}
            {headerCell('perf_ytd', t('screener.col.perf_ytd', 'YTD'))}
            {headerCell('perf_1y', t('screener.col.perf_1y', '1Y'))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={14} className="text-center text-muted-foreground py-6">
                {t('screener.table.no_results', 'No tickers match the current filters.')}
              </TableCell>
            </TableRow>
          )}
          {rows.map((r) => {
            const chgN = r.change_pct === null ? 0 : Number(r.change_pct);
            return (
              <TableRow
                key={r.ticker}
                className="cursor-pointer"
                onClick={() => openTab({
                  type: 'analyze',
                  title: r.ticker,
                  content: null,
                  metadata: { ticker: r.ticker },
                })}
              >
                <TableCell className="font-mono font-semibold">{r.ticker}</TableCell>
                <TableCell>
                  <Badge variant="outline" className="h-5 text-[10px]">{r.market}</Badge>
                </TableCell>
                <TableCell className="text-right">{fmtNum(r.price, 2)}</TableCell>
                <TableCell className={cn('text-right',
                  chgN > 0 && 'text-green-500',
                  chgN < 0 && 'text-red-500')}>{fmtPct(r.change_pct)}</TableCell>
                <TableCell className="text-right">{fmtVol(r.volume)}</TableCell>
                <TableCell className="text-right">{fmtMcap(r.market_cap)}</TableCell>
                <TableCell className="text-right">{fmtNum(r.pe_ttm, 1)}</TableCell>
                <TableCell className="text-right">{fmtPct(r.eps_growth_yoy)}</TableCell>
                <TableCell className="text-right">{fmtPct(r.dividend_yield_pct)}</TableCell>
                <TableCell className="text-left truncate max-w-[120px]">{r.sector ?? '—'}</TableCell>
                <TableCell className="text-left">
                  {r.analyst_rating
                    ? <Badge className={cn('h-5 text-[10px]', RATING_COLOR[r.analyst_rating])}>
                        {r.analyst_rating.replace('_', ' ')}
                      </Badge>
                    : '—'}
                </TableCell>
                <TableCell className={cn('text-right',
                  Number(r.perf_1m) > 0 && 'text-green-500',
                  Number(r.perf_1m) < 0 && 'text-red-500')}>{fmtPct(r.perf_1m)}</TableCell>
                <TableCell className={cn('text-right',
                  Number(r.perf_ytd) > 0 && 'text-green-500',
                  Number(r.perf_ytd) < 0 && 'text-red-500')}>{fmtPct(r.perf_ytd)}</TableCell>
                <TableCell className={cn('text-right',
                  Number(r.perf_1y) > 0 && 'text-green-500',
                  Number(r.perf_1y) < 0 && 'text-red-500')}>{fmtPct(r.perf_1y)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```powershell
cd app/frontend
npx tsc --noEmit
```
Expected: no new errors in `snapshot-table.tsx`.

- [ ] **Step 3: Commit**

```bash
git add app/frontend/src/components/panels/screener/snapshot-table.tsx
git commit -m "feat(screener): sortable snapshot table with bilingual headers"
```

---

## Task 11: Frontend screener-tab shell + status-bar + empty-state

**Depends on:** Tasks 9, 10.

**Files:**
- Create: `app/frontend/src/components/panels/screener/status-bar.tsx`
- Create: `app/frontend/src/components/panels/screener/empty-state.tsx`
- Create: `app/frontend/src/components/panels/screener/filter-chip-bar.tsx`
- Create: `app/frontend/src/components/panels/screener/screener-tab.tsx`

- [ ] **Step 1: Create status-bar.tsx**

```tsx
import { ScreenerStatusResponse } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface StatusBarProps {
  status: ScreenerStatusResponse | null;
  matchCount: number;
  totalCount: number;
}

export function StatusBar({ status, matchCount, totalCount }: StatusBarProps) {
  const { t } = useTranslation();
  if (!status || !status.snapshot_date) {
    return (
      <div className="text-xs text-muted-foreground py-1 px-2">
        {t('screener.status.no_data', 'No snapshot yet')}
      </div>
    );
  }
  const updatedLabel = status.last_updated
    ? new Date(status.last_updated).toLocaleString()
    : status.snapshot_date;
  return (
    <div className="text-xs text-muted-foreground py-1 px-2 flex justify-between">
      <span>
        {t('screener.status.matched', 'Matched')}: <b>{matchCount}</b> / {totalCount}
      </span>
      <span>
        {t('screener.status.data_as_of', 'Data as of')} {updatedLabel}
        {' · '}
        US: {status.by_market.US ?? 0} · CN: {status.by_market.CN ?? 0}
      </span>
    </div>
  );
}
```

- [ ] **Step 2: Create empty-state.tsx**

```tsx
import { Database } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function EmptyState() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <Database className="w-10 h-10 mb-3 opacity-40" />
      <div className="text-sm">
        {t('screener.empty.title', 'No snapshot yet')}
      </div>
      <div className="text-xs mt-1">
        {t('screener.empty.body', 'Snapshot runs nightly at 22:00 ET. Check back tomorrow.')}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create filter-chip-bar.tsx**

```tsx
import { ColumnMetadata, Market, ChipValues } from '@/types/screener';
import { RangeChip } from './chips/range-chip';
import { MultiSelectChip } from './chips/multi-select-chip';
import { DateRangeChip } from './chips/date-range-chip';

interface FilterChipBarProps {
  columns: ColumnMetadata[];
  values: ChipValues;
  market: Market;
  onChange: (next: ChipValues) => void;
}

export function FilterChipBar({ columns, values, market, onChange }: FilterChipBarProps) {
  const updateOne = (patch: ChipValues) => onChange({ ...values, ...patch });

  return (
    <div className="flex flex-wrap gap-2 py-2 px-2">
      {columns.map((meta) => {
        if (meta.kind === 'range' && meta.filter_min && meta.filter_max) {
          const minKey = meta.filter_min;
          const maxKey = meta.filter_max;
          return (
            <RangeChip
              key={meta.slug}
              meta={meta}
              minValue={(values[minKey] as number | null) ?? null}
              maxValue={(values[maxKey] as number | null) ?? null}
              onChange={(min, max) => updateOne({ [minKey]: min, [maxKey]: max })}
            />
          );
        }
        if (meta.kind === 'multi_select' && meta.filter_key) {
          const key = meta.filter_key;
          return (
            <MultiSelectChip
              key={meta.slug}
              meta={meta}
              market={market}
              selectedValues={(values[key] as string[]) ?? []}
              onChange={(vals) => updateOne({ [key]: vals })}
            />
          );
        }
        if (meta.kind === 'date_range' && meta.filter_after && meta.filter_before) {
          const a = meta.filter_after;
          const b = meta.filter_before;
          return (
            <DateRangeChip
              key={meta.slug}
              meta={meta}
              afterDate={(values[a] as string | null) ?? null}
              beforeDate={(values[b] as string | null) ?? null}
              onChange={(after, before) => updateOne({ [a]: after, [b]: before })}
            />
          );
        }
        return null;
      })}
    </div>
  );
}
```

- [ ] **Step 4: Create screener-tab.tsx (the shell)**

```tsx
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  getColumnMetadata, getLatestSnapshot, getSnapshotStatus,
} from '@/services/screener-service';
import {
  ChipValues, ColumnMetadata, Market,
  ScreenerSnapshotResponse, ScreenerStatusResponse, SnapshotRow,
} from '@/types/screener';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { EmptyState } from './empty-state';
import { FilterChipBar } from './filter-chip-bar';
import { SnapshotTable } from './snapshot-table';
import { StatusBar } from './status-bar';

export function ScreenerTab() {
  const { t } = useTranslation();
  const [market, setMarket] = useState<Market>('ALL');
  const [columns, setColumns] = useState<ColumnMetadata[]>([]);
  const [filterValues, setFilterValues] = useState<ChipValues>({});
  const [sortBy, setSortBy] = useState('market_cap');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [response, setResponse] = useState<ScreenerSnapshotResponse | null>(null);
  const [status, setStatus] = useState<ScreenerStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    getColumnMetadata()
      .then((r) => { if (alive) setColumns(r.columns); })
      .catch(console.error);
    getSnapshotStatus()
      .then((s) => { if (alive) setStatus(s); })
      .catch(console.error);
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getLatestSnapshot({
      market, sort_by: sortBy, sort_dir: sortDir, limit: 200,
      filters: filterValues,
    })
      .then((r) => { if (alive) setResponse(r); })
      .catch(console.error)
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [market, sortBy, sortDir, filterValues]);

  const rows: SnapshotRow[] = response?.rows ?? [];
  const totalCount = response?.total_count ?? 0;
  const hasAnySnapshot = useMemo(
    () => (status?.row_count ?? 0) > 0, [status]);

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(column);
      setSortDir('desc');
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-2 pt-2">
        <div className="text-sm font-semibold">{t('screener.tab.title', 'Screener')}</div>
        <Select value={market} onValueChange={(v) => setMarket(v as Market)}>
          <SelectTrigger className="h-8 w-32 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">{t('screener.market.all', 'US + CN')}</SelectItem>
            <SelectItem value="US">{t('screener.market.us', 'US')}</SelectItem>
            <SelectItem value="CN">{t('screener.market.cn', 'CN (A股)')}</SelectItem>
          </SelectContent>
        </Select>
        {loading && <span className="text-xs text-muted-foreground">…</span>}
      </div>

      {columns.length > 0 && (
        <FilterChipBar
          columns={columns}
          values={filterValues}
          market={market}
          onChange={setFilterValues}
        />
      )}

      <StatusBar status={status} matchCount={rows.length} totalCount={totalCount} />

      <div className="flex-1 overflow-auto px-2 pb-2">
        {!hasAnySnapshot
          ? <EmptyState />
          : <SnapshotTable rows={rows} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
        }
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Verify TypeScript compiles**

```powershell
cd app/frontend
npx tsc --noEmit
```
Expected: no new errors. If `@/components/ui/select` is missing, install with shadcn.

- [ ] **Step 6: Commit**

```bash
git add app/frontend/src/components/panels/screener/
git commit -m "feat(screener): tab shell + chip bar + status bar + empty state"
```

---

## Task 12: Wire Screener into tabs + sidebar

**Depends on:** Task 11.

**Files:**
- Create: `app/frontend/src/components/panels/left/screener-action.tsx`
- Modify: `app/frontend/src/contexts/tabs-context.tsx` (add `'screener'` to TabType union + generator)
- Modify: `app/frontend/src/components/panels/left/left-sidebar.tsx` (add `<ScreenerAction />`)
- Modify: tab content router — find the file that maps `tab.type` to a rendered component (likely
  `app/frontend/src/components/tabs/tab-content.tsx` or one of the layout files that hosts `<Layout>` /
  `<TabContent />` — search for `case 'lab'` to find it) and add a `case 'screener'` branch.

- [ ] **Step 1: Add 'screener' to TabType union**

Open `app/frontend/src/contexts/tabs-context.tsx`. Change:

```typescript
export type TabType = 'settings' | 'scanner' | 'analyze' | 'lab';
```

to:

```typescript
export type TabType = 'settings' | 'scanner' | 'analyze' | 'lab' | 'screener';
```

Find the `generateTabId` function (around line 60) and add a `screener` branch before
the fallback `return \`${type}-${Date.now()}\`;` line:

```typescript
    if (type === 'screener') {
      // Single screener tab.
      return 'screener';
    }
```

- [ ] **Step 2: Create ScreenerAction sidebar entry**

Create `app/frontend/src/components/panels/left/screener-action.tsx`:

```tsx
import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { ScreenerTab } from '@/components/panels/screener/screener-tab';
import { Filter } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function ScreenerAction() {
  const { openTab, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  return (
    <div className="px-2 py-1">
      <Button
        variant="ghost"
        className="w-full justify-start gap-2 h-8 text-xs"
        onClick={() => {
          openTab({
            type: 'screener',
            title: t('screener.tab.title', 'Screener'),
            content: <ScreenerTab />,
          });
          setActiveTab('screener');
        }}
      >
        <Filter className="w-4 h-4" />
        {t('screener.tab.title', 'Screener')}
      </Button>
    </div>
  );
}
```

- [ ] **Step 3: Mount in LeftSidebar**

Open `app/frontend/src/components/panels/left/left-sidebar.tsx`. Add the import:

```tsx
import { ScreenerAction } from './screener-action';
```

Place `<ScreenerAction />` inside the sidebar, between `<WatchlistSection />` and
`<ScannerAction />`:

```tsx
      <WatchlistSection />

      <ScreenerAction />

      <ScannerAction />
```

- [ ] **Step 4: Wire ScreenerTab into the tab router (if a separate file exists)**

Search for the file that renders tab content based on `tab.type`:

```powershell
C:\Users\Jerry\anaconda3\python.exe -c "import subprocess; subprocess.run(['grep', '-rn', \"tab.type === 'lab'\", 'app/frontend/src/'])"
```

If a file exists that does `tab.type === 'lab'` style dispatch (likely
`app/frontend/src/components/layout/Layout.tsx` or similar), add the same
shape for `'screener'`:

```tsx
{tab.type === 'screener' && <ScreenerTab />}
```

If tabs render directly from `tab.content` (no central router) — the
`openTab` call in `ScreenerAction` already passes the rendered
`<ScreenerTab />` as `content`, so no further wiring is needed.

- [ ] **Step 5: Verify TypeScript compiles**

```powershell
cd app/frontend
npx tsc --noEmit
```
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add app/frontend/src/contexts/tabs-context.tsx app/frontend/src/components/panels/left/screener-action.tsx app/frontend/src/components/panels/left/left-sidebar.tsx
# Add the tab-router file too if you modified one in Step 4
git commit -m "feat(screener): wire Screener tab into left sidebar + tabs context"
```

---

## Task 13: i18n keys (en + zh)

**Depends on:** Task 11.

**Files:**
- Modify: `app/frontend/src/i18n/locales/en.json`
- Modify: `app/frontend/src/i18n/locales/zh.json`

- [ ] **Step 1: Append screener.* keys to en.json**

Add this object to `app/frontend/src/i18n/locales/en.json` at the top level
(next to existing namespaces like `common`):

```json
  "screener": {
    "tab": { "title": "Screener" },
    "market": { "all": "US + CN", "us": "US", "cn": "CN (A-shares)" },
    "status": {
      "no_data": "No snapshot yet",
      "matched": "Matched",
      "data_as_of": "Data as of"
    },
    "empty": {
      "title": "No snapshot yet",
      "body": "Snapshot runs nightly at 22:00 ET. Check back tomorrow."
    },
    "table": { "no_results": "No tickers match the current filters." },
    "col": {
      "ticker": "Ticker", "market": "Mkt", "price": "Price", "chg": "Chg %",
      "vol": "Vol", "mcap": "Mkt cap", "pe": "P/E", "eps_g": "EPS gro",
      "div": "Div %", "sector": "Sector", "rating": "Rating",
      "perf_1d": "1D", "perf_5d": "5D", "perf_1m": "1M", "perf_3m": "3M",
      "perf_ytd": "YTD", "perf_1y": "1Y"
    }
  }
```

- [ ] **Step 2: Append screener.* keys to zh.json**

Add this object to `app/frontend/src/i18n/locales/zh.json`:

```json
  "screener": {
    "tab": { "title": "选股器" },
    "market": { "all": "美股 + A股", "us": "美股", "cn": "A 股" },
    "status": {
      "no_data": "暂无快照数据",
      "matched": "匹配",
      "data_as_of": "数据截至"
    },
    "empty": {
      "title": "暂无快照",
      "body": "快照每日 22:00 (美东) 自动构建，请明日再来。"
    },
    "table": { "no_results": "当前筛选条件下无匹配股票。" },
    "col": {
      "ticker": "代码", "market": "市场", "price": "价格", "chg": "涨跌幅",
      "vol": "成交量", "mcap": "市值", "pe": "市盈率", "eps_g": "EPS 增长",
      "div": "股息率", "sector": "板块", "rating": "评级",
      "perf_1d": "1 日", "perf_5d": "5 日", "perf_1m": "1 月", "perf_3m": "3 月",
      "perf_ytd": "今年", "perf_1y": "1 年"
    }
  }
```

Make sure both files remain valid JSON (mind the trailing comma if you
insert above another top-level key).

- [ ] **Step 3: Verify TypeScript compiles + JSON is valid**

```powershell
cd app/frontend
npx tsc --noEmit
C:\Users\Jerry\anaconda3\python.exe -c "import json; json.load(open('src/i18n/locales/en.json', encoding='utf-8')); json.load(open('src/i18n/locales/zh.json', encoding='utf-8')); print('json ok')"
```
Expected: `json ok` and no TS errors.

- [ ] **Step 4: Commit**

```bash
git add app/frontend/src/i18n/locales/en.json app/frontend/src/i18n/locales/zh.json
git commit -m "feat(screener): i18n keys (en + zh) for tab, chips, status"
```

---

## Task 14: E2E smoke + progress.md

**Depends on:** Tasks 1-13.

**Files:**
- Modify: `progress.md`

- [ ] **Step 1: Run full backend test suite (regression check)**

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/ tests/test_screener_db_models.py tests/test_screener_repository.py -v
```
Expected: all green (≈35 tests).

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/ -q --tb=short -x
```
Expected: full pre-existing suite still green (no regressions in scanner / research / lab tests).

- [ ] **Step 2: Apply migration to the dev DB**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m alembic upgrade head
```
Expected: ticker_snapshots table created.

- [ ] **Step 3: Trigger a one-shot snapshot build manually**

Run a Python one-liner so we don't have to wait for the 22:00 ET cron:

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -c "from app.backend.services.scheduler_service import _run_snapshot_job_body; _run_snapshot_job_body()"
```
Expected: log lines `screener snapshot US: N rows`, `screener snapshot CN: N rows`,
`screener snapshot cleanup deleted 0 old rows`. US may take ~15-20 min (yfinance);
CN ~3-5 min (akshare). If CN fails (network), US-only result still validates Phase 1.

- [ ] **Step 4: Backend smoke**

Start the backend per CLAUDE.md (no `--reload`):

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUNBUFFERED="1"
C:\Users\Jerry\anaconda3\python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 --log-level info
```

In another shell:

```powershell
curl http://127.0.0.1:8001/screener/snapshot/status
curl "http://127.0.0.1:8001/screener/snapshot/latest?market=US&pe_max=20&limit=5"
curl http://127.0.0.1:8001/screener/snapshot/columns | C:\Users\Jerry\anaconda3\python.exe -m json.tool | Select-Object -First 30
```

Verify each returns 200 + the expected shape.

- [ ] **Step 5: Frontend smoke**

```powershell
cd app/frontend
npm run dev
```

Open `http://localhost:5173`. Confirm:

1. Screener entry exists in the left sidebar (between Watchlist and Scanner)
2. Click it → new Screener tab opens
3. Market selector defaults to "US + CN" (or 美股 + A股 in zh)
4. Chip bar shows ~16 chips on two rows
5. Table renders with rows; columns sortable on click
6. Set Price min = 100, P/E max = 30 → table re-queries and shrinks
7. Click Sector chip → checkbox popover lists GICS sectors; selecting Technology
   filters the table
8. Sort by `market_cap` desc → AAPL / MSFT / NVDA appear in the top rows
9. Click a row → Analyze tab opens for that ticker
10. Switch UI language to 中文 (existing language toggle) → chip labels and
    column headers re-render in Chinese
11. Status bar at bottom: "Matched: X / Y · Data as of YYYY-MM-DD HH:MM"

- [ ] **Step 6: Append a Phase 1 Screener entry to progress.md**

Open `progress.md` and append (preserving the existing log style — most recent
entry at the bottom or top per the file's convention):

```markdown
## 2026-05-27 — Screener Phase 1 (M11)

**Goal:** Add a TradingView-style faceted-filter Screener tab over a
nightly snapshot of S&P 500 + CSI 300 (~800 tickers).

**Shipped:**
- New table `ticker_snapshots` (one row per ticker per day, 30-day TTL,
  PK on `(ticker, snapshot_date)`, 3 supporting indices) — alembic
  revision `d4e8a2c1b9f6`.
- `src/screener/snapshot_builder.py` — US path via `yfinance.Ticker.info`
  + `.history` + `.earnings_dates`; CN path via `src/screener/ashare_metrics.py`
  (mootdx quote + akshare fundamentals + akshare hist).
- `app/backend/repositories/screener_repository.py` — filter-dict → SQL
  WHERE translation, idempotent bulk_upsert, 30-day cleanup, multi-market
  query.
- 3 REST endpoints at `/screener/snapshot/{latest,columns,status}`
  (FastAPI + Pydantic, mounted under the global `api_router`).
- APScheduler cron `0 22 * * *` ET — builds US then CN, per-market
  isolated, cleanup after.
- Frontend: new `Screener` tab in the left sidebar (between Watchlist
  and Scanner). 16 chips (range / multi-select / date-range) + sortable
  table + market selector + status bar + empty state. Row click → opens
  Analyze tab. Bilingual labels via `screener.*` i18n keys.

**Tests added:** 35+ tests across `tests/test_screener_db_models.py`,
`tests/test_screener_repository.py`, `tests/screener/test_*.py`. All
new tests green; full backend suite still passes.

**Out of scope (deferred to later phases):**
- Saved filter presets + cron auto-runs + email push (Phase 2).
- Stock logos, column-group tabs (Overview/Performance/Valuation),
  bulk "add to watchlist" (Phase 3).
- Universe expansion beyond SPX + CSI 300, intraday refresh.
```

- [ ] **Step 7: Commit**

```bash
git add progress.md
git commit -m "docs: log Screener Phase 1 shipping"
```

---

## Self-Review

**Spec coverage:**
- ✅ Data model — Task 1
- ✅ Universe loaders — reused via `load_universe` in Tasks 3 + 4 (no new code)
- ✅ Snapshot builder (US + CN) — Tasks 3, 4
- ✅ Repository — Task 2
- ✅ 3 REST endpoints — Task 6
- ✅ Cron job — Task 7
- ✅ Frontend tab + chips + table + status + empty — Tasks 9, 10, 11
- ✅ Sidebar + tab wiring — Task 12
- ✅ i18n — Task 13
- ✅ Tests — Tasks 1, 2, 3, 4, 5, 6, 7 each ship test files
- ✅ E2E smoke — Task 14

**Type consistency check:**
- `SnapshotRow` defined in Task 2, used by Tasks 3, 4, 7 — same import path.
- `ScreenerRepository` methods (`bulk_upsert`, `query`, `latest_snapshot_date`,
  `cleanup_old_snapshots`) defined Task 2, consumed Tasks 6 + 7.
- `SnapshotBuilder.build_for_universe(market, kind, asof, on_progress)`
  signature consistent across Task 3 (US) and Task 4 (CN).
- `COLUMN_METADATA` shape consumed by frontend `ColumnMetadata` TS interface
  in Task 8 — both have `slug`, `label_en`, `label_zh`, `kind`, `format`,
  `step`, `filter_min/max`, `filter_key`, `filter_after/before`, `options`,
  `options_us/cn`.
- Frontend `Market` type matches backend `Query(pattern="^(US|CN|ALL)$")`.

**Placeholder scan:** none. Every code step ships complete code; no
"TBD" / "TODO" / "implement later" / "add appropriate error handling"
phrases.
