# Phase 1 — Screener: nightly snapshot + interactive faceted filter UI

## Context

The user opened TradingView's stock-screener UI as a reference (16 filter
chips: Price, Chg %, Mkt cap, P/E, EPS growth, Div yield, Sector, Analyst
rating, Perf %, Revenue growth, PEG, ROE, Beta, earnings dates, plus
Watchlist/Index universe filters) and noted that our existing Scanner is
"really bad" by comparison.

Per the brainstorming dialogue:
- The existing Scanner is event-driven (detector pipeline → ranked
  candidates → LLM analyze). It answers "What changed today?"
- The user wants a complementary Screener that answers "What matches my
  criteria?" — faceted filter UI on per-ticker fundamentals + technicals +
  analyst data.
- The two products do NOT merge. Scanner keeps its detector pipeline;
  Screener gets a separate tab with its own data path.

Phase 1 (this spec) builds the snapshot table + interactive faceted UI.
Phase 2 (later spec) adds saved presets + cron auto-runs + email push.
Phase 3 (later spec) adds polish: sector dropdown, logos, column tabs,
"add all to watchlist".

## Approach

```
┌─────────────────────────────────────────────────────────┐
│  Frontend  (new Screener tab)                           │
│  - market selector (US / CN / Both)                     │
│  - 16 filter chips (popovers for min/max or multi-sel)  │
│  - sortable table (10-20 columns)                       │
│  - row click → opens Analyze tab for that ticker        │
└────────────────────┬────────────────────────────────────┘
                     │  GET /screener/snapshot/latest?...
┌────────────────────┴────────────────────────────────────┐
│  Backend                                                │
│  GET /screener/snapshot/latest   (interactive query)    │
│  GET /screener/snapshot/columns  (chip metadata)        │
│  GET /screener/snapshot/status   (last-built timestamp) │
│                                                         │
│  ScreenerRepository (read filters → SQL WHERE)          │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ ticker_snapshots table                           │   │
│  │   ~800 rows × 30-day retention                   │   │
│  │   PK (ticker, snapshot_date)                     │   │
│  └──────────────────────────────────────────────────┘   │
│                       ↑                                 │
│  SnapshotBuilder      │  daily upsert                   │
│  - US: yfinance .info per ticker (S&P 500, ~500)        │
│  - CN: mootdx quotes + akshare fundamentals (CSI 300)   │
│                                                         │
│  Scheduler cron: 22:00 ET daily (after both closes)     │
└─────────────────────────────────────────────────────────┘
```

### Why nightly snapshot, not real-time per-click

TradingView is a commercial CDN with streaming data — we can't match
that. But chip filtering doesn't NEED real-time: a post-close snapshot
covers 95% of use cases (overnight screening, pre-market preparation).
Snapshot table also gives Phase 2 cron-runs zero latency.

### Why S&P 500 + CSI 300 first

The full universe (~13000 tickers) hits two problems:
- yfinance limits ~2000 `.info` calls/hour → 4-5h job, fragile retries
- Field coverage degrades on the long tail (illiquid tickers have null
  P/E, no analyst data, stale earnings dates)

S&P 500 + CSI 300 ≈ 800 tickers:
- yfinance can complete in ~15-20 min with batching
- mootdx + akshare can do CSI 300 in ~5 min
- All fields populated (institutional coverage)
- Bundled CSVs already exist at `v2/scanner/universes/sp500.csv` and
  `v2/scanner/universes/data/csi300.csv` — zero new universe loader work

Expanding universe later = swap the CSV input in one line.

## Architecture

### Data model

New table `ticker_snapshots`:

```python
class TickerSnapshot(Base):
    __tablename__ = "ticker_snapshots"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker          = Column(String(20), nullable=False)
    market          = Column(String(8),  nullable=False)   # 'US' | 'CN'
    snapshot_date   = Column(Date,       nullable=False)

    # Price / volume
    price           = Column(Numeric(12, 4))
    prev_close      = Column(Numeric(12, 4))
    change_pct      = Column(Numeric(8, 4))
    volume          = Column(BigInteger)
    avg_volume_10d  = Column(BigInteger)
    rel_volume      = Column(Numeric(6, 3))

    # Market cap (raw USD/CNY equivalent — frontend formats)
    market_cap      = Column(Numeric(20, 2))

    # Valuation
    pe_ttm          = Column(Numeric(10, 3))
    pe_forward      = Column(Numeric(10, 3))
    pb              = Column(Numeric(10, 3))
    ps              = Column(Numeric(10, 3))
    peg             = Column(Numeric(10, 3))

    # Growth
    eps_growth_yoy      = Column(Numeric(10, 4))
    revenue_growth_yoy  = Column(Numeric(10, 4))

    # Profitability
    roe                 = Column(Numeric(10, 4))
    profit_margin       = Column(Numeric(10, 4))

    # Dividend
    dividend_yield_pct  = Column(Numeric(8, 4))

    # Risk
    beta                = Column(Numeric(8, 3))

    # Classification
    sector              = Column(String(64))
    industry            = Column(String(128))
    exchange            = Column(String(16))

    # Analyst
    analyst_rating      = Column(String(16))   # strong_buy|buy|neutral|sell|strong_sell
    analyst_count       = Column(Integer)
    target_mean_price   = Column(Numeric(12, 4))

    # Earnings dates
    recent_earnings_date    = Column(Date)
    upcoming_earnings_date  = Column(Date)

    # Performance windows
    perf_1d   = Column(Numeric(8, 4))
    perf_5d   = Column(Numeric(8, 4))
    perf_1m   = Column(Numeric(8, 4))
    perf_3m   = Column(Numeric(8, 4))
    perf_ytd  = Column(Numeric(8, 4))
    perf_1y   = Column(Numeric(8, 4))

    # Meta
    data_source     = Column(String(16))       # 'yfinance' | 'mootdx+akshare'
    last_updated    = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", name="uq_snapshot_ticker_date"),
        Index("idx_snapshot_date",        "snapshot_date"),
        Index("idx_snapshot_market_date", "market", "snapshot_date"),
        Index("idx_snapshot_sector",      "sector", "snapshot_date"),
    )
```

Retention: 30 days. A nightly cleanup deletes `snapshot_date < today - 30d`.
30 days lets the UI show "yesterday's filter would have matched X tickers"
without bloating the table beyond ~24000 rows.

### Universe loaders

Reuse `v2.scanner.universes.loader.load_universe()`:
- `load_universe("sp500")` → ~500 US tickers
- `load_universe("csi300")` → ~300 CN tickers like `600519.SH`, `000001.SZ`

No new universe code. The snapshot builder accepts the kind as a parameter.

### Snapshot builder

New module `src/screener/snapshot_builder.py`:

```python
class SnapshotBuilder:
    def __init__(self, us_client: DataClient, cn_client: AShareClient):
        self.us = us_client     # composite client (yfinance default)
        self.cn = cn_client     # mootdx + akshare wrapper

    def build_for_ticker_us(self, ticker: str, asof: date) -> SnapshotRow:
        """Pull yfinance .info + .history → SnapshotRow."""
        ...

    def build_for_ticker_cn(self, ticker: str, asof: date) -> SnapshotRow:
        """Pull mootdx quote + akshare fundamentals → SnapshotRow."""
        ...

    def build_for_universe(
        self,
        market: Literal["US", "CN"],
        universe_kind: str,
        asof: date,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[SnapshotRow]:
        """Iterate the universe, build rows, return list. Per-ticker
        failures log + skip, NOT raise — same invariant as Scanner runner."""
        ...
```

Threading: same pattern as Scanner — `ThreadPoolExecutor(max_workers=4)`
with per-worker `DataClient` instance (per CLAUDE.md invariant: requests.Session
is not thread-safe). Workers pulled from `queue.Queue`.

Rate-limit policy:
- yfinance: 4 workers × ~5 req/sec sustained → ~1200 tickers/min headroom.
  500 S&P tickers complete in ~30s if yfinance is healthy.
- mootdx: local TCP feed, no rate limit. CSI 300 quotes pulled as a single
  batch.
- akshare CSI 300 fundamentals: ~2 req/sec sustained. ~300 tickers takes
  ~3-5 min.

### Repository

New module `app/backend/repositories/screener_repository.py`:

```python
class ScreenerRepository:
    def __init__(self, db: Session):
        self.db = db

    def bulk_upsert(self, rows: list[SnapshotRow]) -> int:
        """INSERT ... ON CONFLICT (ticker, snapshot_date) DO UPDATE."""

    def latest_snapshot_date(self, market: str | None = None) -> date | None:
        """Most recent date with any rows. Used by 'status' endpoint."""

    def query(
        self,
        market: list[str] | None = None,            # ['US'], ['CN'], ['US','CN'], or None
        universe: list[str] | None = None,          # explicit ticker filter (watchlist mode)
        snapshot_date: date | None = None,          # default: latest
        filters: dict[str, Any] = {},                # parsed chip filters
        sort_by: str = "market_cap",
        sort_dir: Literal["asc", "desc"] = "desc",
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[TickerSnapshot], int]:
        """Returns (rows, total_count). Filters dict format:
            price_min / price_max
            chg_pct_min / chg_pct_max
            mcap_min / mcap_max
            pe_min / pe_max
            eps_growth_min / eps_growth_max
            div_yield_min / div_yield_max
            sector_in: list[str]
            analyst_rating_in: list[str]
            perf_1d_min / ... / perf_1y_min / max
            revenue_growth_min / max
            peg_min / max
            roe_min / max
            beta_min / max
            recent_earnings_after / recent_earnings_before
            upcoming_earnings_after / upcoming_earnings_before
        """

    def cleanup_old_snapshots(self, keep_days: int = 30) -> int:
        """DELETE WHERE snapshot_date < today - keep_days. Returns row count."""
```

Implementation note: build the SQL WHERE clause dynamically from filters
dict using SQLAlchemy `select().where()`. Each filter key maps to a
column + comparator. Unknown keys logged + ignored (never raise — keeps
the API forward-compatible with v2 chip additions).

### REST API

3 new endpoints, mounted under `/screener` in `app/backend/routes/screener.py`:

```python
@router.get("/snapshot/latest")
def get_latest_snapshot(
    market: str | None = Query(None, regex="^(US|CN|ALL)$"),
    sort_by: str = "market_cap",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
    # Filters: parsed from query string into the filters dict.
    # ?price_min=10&pe_max=30&sector_in=Technology,Healthcare&...
    request: Request,  # for additional query parsing
) -> ScreenerSnapshotResponse:
    """Returns {rows, total_count, snapshot_date, last_updated}."""

@router.get("/snapshot/columns")
def get_column_metadata() -> ScreenerColumnMetadata:
    """Static metadata for the frontend chip bar:
       - column slug, display name (en/zh), data type, unit, format,
         min/max bounds, options list (for sector / rating chips).
       Pure constant — no DB read.
    """

@router.get("/snapshot/status")
def get_snapshot_status() -> ScreenerStatusResponse:
    """Returns {last_built_at, snapshot_date, row_count, by_market: {US: 500, CN: 300}}.
       Used by frontend to show 'Data as of YYYY-MM-DD HH:MM ET'."""
```

Pydantic schemas in `app/backend/models/screener_schemas.py`:

```python
class SnapshotRowOut(BaseModel):
    ticker: str
    market: str
    snapshot_date: date
    price: Decimal | None
    change_pct: Decimal | None
    market_cap: Decimal | None
    pe_ttm: Decimal | None
    eps_growth_yoy: Decimal | None
    dividend_yield_pct: Decimal | None
    sector: str | None
    analyst_rating: str | None
    perf_1d: Decimal | None
    perf_5d: Decimal | None
    perf_1m: Decimal | None
    perf_3m: Decimal | None
    perf_ytd: Decimal | None
    perf_1y: Decimal | None
    revenue_growth_yoy: Decimal | None
    peg: Decimal | None
    roe: Decimal | None
    beta: Decimal | None
    recent_earnings_date: date | None
    upcoming_earnings_date: date | None
    # ... all snapshot columns (frontend can pick what to show per column-tab)

class ScreenerSnapshotResponse(BaseModel):
    rows: list[SnapshotRowOut]
    total_count: int
    snapshot_date: date
    last_updated: datetime
```

### Cron job

Add to `app/backend/services/scheduler_service.py`:

```python
SCREENER_SNAPSHOT_CRON_EXPR = "0 22 * * *"   # 22:00 ET daily (all 7 days
                                              # — CN runs on Sat/Sun no-op)
SCREENER_SNAPSHOT_JOB_ID = "screener_snapshot"

def _run_snapshot_job():
    """Build US snapshot then CN snapshot. Each market is independent
    — failure in one logs + continues to the other. Cleanup runs after."""
    db = SessionLocal()
    repo = ScreenerRepository(db)
    builder = SnapshotBuilder(us_client=..., cn_client=...)
    asof = date.today()

    for market, kind in (("US", "sp500"), ("CN", "csi300")):
        try:
            rows = builder.build_for_universe(market, kind, asof)
            inserted = repo.bulk_upsert(rows)
            logger.info("screener snapshot %s: %d rows", market, inserted)
        except Exception as e:
            logger.exception("screener snapshot %s failed: %s", market, e)

    repo.cleanup_old_snapshots(keep_days=30)
    db.close()
```

### Frontend

New top-level tab "Screener" sitting next to Scanner / Analyze / Lab.
Tab plumbing reuses the existing `tabs-context.tsx` system (display:none
state preservation per memory invariant).

Component tree:

```
app/frontend/src/components/panels/screener/
  screener-tab.tsx                  # tab shell — market selector + chip bar + table
  filter-chip-bar.tsx               # horizontal scrolling chip row
  chips/
    range-chip.tsx                  # min/max popover (Price, P/E, etc.)
    multi-select-chip.tsx           # checkbox popover (Sector, Rating)
    date-range-chip.tsx             # date popover (earnings dates)
  snapshot-table.tsx                # sortable table (TanStack Table)
  status-bar.tsx                    # "Data as of ..." + match count
  empty-state.tsx                   # "No snapshot yet — runs nightly 22:00 ET"

app/frontend/src/services/
  screener-service.ts               # REST client: getLatest, getColumns, getStatus

app/frontend/src/types/
  screener.ts                       # SnapshotRow, FilterValues, ColumnMetadata
```

Filter chip layout matches TradingView's reference screenshot:
Row 1: Price, Chg %, Mkt cap, P/E, EPS dil growth, Div yield %, Sector,
       Analyst rating, Perf %
Row 2: Revenue growth, PEG, ROE, Beta, Recent earnings date,
       Upcoming earnings date, + (more chips later)

Defaults:
- market = ALL
- sort_by = market_cap desc
- limit = 200 (page size; pagination via Load More button)

Row click → opens Analyze tab pre-filled with that ticker (reuses
existing `openTab({ kind: 'analyze', ticker })` pattern).

Filter state is local component state in v1 (NOT persisted to URL).
Phase 2 will URL-persist + save as preset.

### i18n

Reuse Phase 7 i18n keys. New namespace `screener.*`:
- `screener.tab.title` = "Screener" / "选股器"
- `screener.chip.price` = "Price" / "价格"
- `screener.chip.pe` = "P/E" / "市盈率"
- ... (~30 keys total — column names + chip labels)

## Files

### New (backend)

| File | Purpose |
|---|---|
| `app/backend/database/models.py` | Append `TickerSnapshot` class |
| `app/backend/alembic/versions/<sha>_add_ticker_snapshots.py` | Migration |
| `app/backend/repositories/screener_repository.py` | CRUD + filter query |
| `app/backend/models/screener_schemas.py` | Pydantic request/response |
| `app/backend/routes/screener.py` | 3 REST endpoints |
| `app/backend/routes/__init__.py` | Register screener router |
| `app/backend/services/scheduler_service.py` | Add cron job + handler |
| `src/screener/__init__.py` | Package marker |
| `src/screener/snapshot_builder.py` | US + CN snapshot builder |
| `src/screener/ashare_metrics.py` | mootdx + akshare wrapper |
| `src/screener/column_metadata.py` | Static column metadata (also imported by route) |

### New (frontend)

| File | Purpose |
|---|---|
| `app/frontend/src/components/panels/screener/screener-tab.tsx` | Tab shell |
| `app/frontend/src/components/panels/screener/filter-chip-bar.tsx` | Chip row |
| `app/frontend/src/components/panels/screener/chips/range-chip.tsx` | Min/max chip |
| `app/frontend/src/components/panels/screener/chips/multi-select-chip.tsx` | Multi-sel chip |
| `app/frontend/src/components/panels/screener/chips/date-range-chip.tsx` | Date chip |
| `app/frontend/src/components/panels/screener/snapshot-table.tsx` | Sortable table |
| `app/frontend/src/components/panels/screener/status-bar.tsx` | Last-built bar |
| `app/frontend/src/components/panels/screener/empty-state.tsx` | First-run empty |
| `app/frontend/src/services/screener-service.ts` | REST client |
| `app/frontend/src/types/screener.ts` | TS types |
| `app/frontend/src/i18n/locales/{en,zh}.json` | Append `screener.*` keys |

### Modified

| File | Change |
|---|---|
| `app/frontend/src/components/panels/left/left-sidebar.tsx` | Add Screener nav item |
| `app/frontend/src/contexts/tabs-context.tsx` | Add `'screener'` to TabKind union |
| `app/frontend/src/components/tabs/tab-content.tsx` | Route 'screener' kind to ScreenerTab |

### Tests

| File | What it covers |
|---|---|
| `tests/screener/test_snapshot_builder_us.py` | Mock yfinance → SnapshotRow shape |
| `tests/screener/test_snapshot_builder_cn.py` | Mock mootdx + akshare → SnapshotRow |
| `tests/screener/test_repository.py` | upsert, query w/ filters, cleanup |
| `tests/screener/test_routes.py` | GET endpoints (auth, validation, filter parsing) |
| `tests/screener/test_column_metadata.py` | Static metadata shape |
| `tests/screener/test_scheduler_integration.py` | Cron job triggers builder + cleanup |

Pure-mock unit tests (no live yfinance/mootdx). Existing test patterns
from `tests/scanner/` and `tests/research/` directly reusable.

## Verification

### Backend

```powershell
$env:PYTHONIOENCODING="utf-8"
# All new screener tests pass
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/ -v
# Full suite stays green
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/ -q --tb=short
```

### Manual smoke

1. Apply Alembic migration:
   `C:\Users\Jerry\anaconda3\python.exe -m alembic upgrade head`
2. Trigger snapshot manually (skip waiting for 22:00 ET cron):
   `POST /screener/snapshot/build?market=US` (admin-only endpoint OR
   run `python -m src.screener.snapshot_builder --market=US` CLI)
3. Verify rows: `SELECT count(*) FROM ticker_snapshots WHERE market='US'`
   → expect ~500
4. Open `http://localhost:5173` → click Screener tab
5. Verify chip bar renders all 16 chips
6. Set Price > 100, P/E < 20, Sector = Technology → table filters live
7. Sort by Mkt cap desc → AAPL/MSFT/NVDA at top
8. Click row → Analyze tab opens for that ticker
9. Switch market to CN → table refreshes with 600/000-prefixed tickers
10. Status bar shows "Data as of 2026-05-27 22:05 ET, 800 tickers"

## Risks / unknowns

1. **yfinance `.info` field reliability**: occasionally returns
   `None` for `trailingPE` / `forwardEps` / `recommendationKey` even on
   healthy tickers. Mitigation: SnapshotRow allows None for all metric
   fields; the frontend renders `—` for nulls. Per-ticker exceptions
   logged + skipped (don't fail the whole job for 5 bad tickers).
2. **akshare CSI 300 fundamentals endpoint stability**: Eastmoney's
   constituent API is occasionally unreachable from outside China. The
   bundled `csi300.csv` already handles the universe side; for
   per-ticker fundamentals, fall back to `recent_earnings_date=None`
   etc. rather than failing.
3. **Currency mixing in Mkt cap column**: US in USD, CN in CNY. v1
   shows raw values + a market badge ("US" / "CN") next to each row.
   v2 can add a "convert all to USD" toggle (need FX rate source).
4. **Sector taxonomy mismatch**: yfinance uses GICS sectors
   ("Technology"), akshare uses 申万 sectors ("信息技术"). v1 stores
   both raw; the Sector chip's dropdown shows market-grouped subheaders
   so the user knows the difference.
5. **First-run race**: if the cron hasn't fired yet on day 1, the
   Screener tab is empty. Empty-state component explains this + offers
   a "Run snapshot now" button (admin-gated).
6. **Cron timing on weekends**: 22:00 ET Sat builds last-Friday data
   for US, last-Friday data for CN. That's fine for a weekend screen.
   The cron always runs; per-market builders can no-op if the source
   feeds are closed.

## Out of scope (Phase 1)

- Saved filter presets (Phase 2)
- Cron auto-runs of saved presets (Phase 2)
- Email / webhook notifications on preset match (Phase 2)
- Multi-row select + bulk "add to watchlist" (Phase 3)
- Stock logos (Phase 3)
- Column tab grouping like TradingView (Overview/Performance/Valuation
  tabs over the same row set) (Phase 3)
- Mini-chart per row (Phase 3)
- Universe expansion beyond S&P 500 + CSI 300 (post-Phase 3)
- Real-time / intraday refresh (probably never — different product)
- Lab/strategy integration ("screen this filter then backtest matches")
  (separate spec)
