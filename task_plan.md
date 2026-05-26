# Daily Market Scanner — Task Plan

## Goal

Build a daily-scheduled market scanner inside `ai-hedge-fund` that:
1. Each scheduled tick scans a stock universe (default = nasdaq100 ∪ sp500, ~140 tickers)
2. Runs 4 event detectors (earnings / insider / price-volume / news-sentiment)
3. Produces a Top-N composite-scored watchlist (default 20)
4. Lets users click a ticker → launches existing v1 LLM Stage-2 deep analysis (unchanged)

Architecture: `v2/scanner/` (pure quant, no LLM) + existing `app/backend/` (FastAPI + APScheduler) + new "scanner" tab in `app/frontend/`.

Reference: full design in `C:\Users\Jerry\.claude\plans\a-synchronous-kite.md`.

## Status Overview

| Milestone | Description | Status |
|---|---|---|
| **M1** | DB tables + universe CSVs + repositories + Pydantic schemas | ✅ complete |
| **M2** | 4 event detectors + composite scoring | ✅ complete |
| **M3** | ThreadPool runner + service + SSE broadcaster | ✅ complete |
| **M3.5** | DataClient Protocol + FDClient/FinnhubClient + provider factory | ✅ complete |
| **M3.6** | EODHDClient + CompositeClient (hybrid EODHD+Finnhub) + std-floor bugfix | ✅ complete |
| **M4** | APScheduler + `/scanner/*` REST API + start/shutdown wiring | ✅ complete |
| **M5** | Frontend scanner tab + sortable watchlist table + click-through to flow tab | ⏳ **next** |
| **M6** | Hardening: universe refresh script, interrupted-run cleanup, doc | pending |
| **M3.7** *(optional)* | yfinance adapter for v1 LLM agents' `search_line_items` (unlock from FD trial) | deferred |

## Current Phase: M5 — Frontend scanner tab

### M5 Sub-tasks (to be expanded)

| ID | Task | Status |
|---|---|---|
| M5.a | Explore frontend conventions (tabs-context, services/api.ts SSE pattern, flow-tab creation) | pending |
| M5.b | TS types (`types/scanner.ts`) + REST service (`services/scanner-service.ts`) | pending |
| M5.c | Components: scanner-panel, scanner-config-dialog, watchlist-table | pending |
| M5.d | Wire into tabs-context (new `'scanner'` TabType) + left sidebar entry | pending |
| M5.e | Click-through: createFlowTab with initialTickers seeded from clicked row | pending |
| M5.f | Manual e2e: open Scanner tab → run config → see SSE progress → click row → land in flow tab | pending |

## Previous Phase: M4 — APScheduler + REST API ✅

### M4 Sub-tasks

| ID | Task | Status |
|---|---|---|
| M4.a | Add `apscheduler = "^3.10"` to `pyproject.toml`; `poetry lock` | pending |
| M4.b | Create `app/backend/services/scheduler_service.py` (`SchedulerService` class) | pending |
| M4.c | Create `app/backend/routes/scanner.py` with the 8 endpoints | pending |
| M4.d | Wire into `app/backend/routes/__init__.py` + `app/backend/main.py` startup/shutdown | pending |
| M4.e | Tests: scheduler register/unregister/reschedule; REST endpoint integration | pending |
| M4.f | Manual curl smoke: create config → run-now → SSE stream → list entries | pending |

### M4 REST surface

```
GET    /scanner/configs                     List all configs
POST   /scanner/configs                     Create + register with scheduler
GET    /scanner/configs/{id}                Get one
PATCH  /scanner/configs/{id}                Update + reschedule
DELETE /scanner/configs/{id}                Delete + unregister
POST   /scanner/configs/{id}/run            Manual trigger → returns {run_id}
GET    /scanner/runs/{run_id}               Run status + summary
GET    /scanner/runs/{run_id}/entries       Full Top-N entries
GET    /scanner/runs/{run_id}/stream        SSE proxy to ScanBroadcaster
```

### M4 Implementation notes

- Use `BackgroundScheduler` (not `AsyncIOScheduler`) — the runner is thread-based already.
- Job IDs: `f"scanner-config-{cfg.id}"`, `replace_existing=True`.
- Cron timezone: `America/New_York`. Validate via `CronTrigger.from_crontab()`.
- Cron presets in UI (M5): pre-market `0 6 * * 1-5`, after-close `30 16 * * 1-5`, late-evening `0 21 * * 1-5` (default).
- `shutdown(wait=False)` to avoid blocking on a long-running scan.

## Decisions Locked

| Decision | Choice | Date |
|---|---|---|
| Default universe | `nasdaq100_sp500` (NDX100 ∪ SP500, deduped, ~140 in seed CSVs) | 2026-05-13 |
| Default provider | `hybrid` (EODHD prices+news + Finnhub insider+earnings+facts) | 2026-05-14 |
| Provider override | env var `SCANNER_DATA_PROVIDER=fd|finnhub|eodhd|hybrid` | 2026-05-13 |
| Composite score | `0.6 × event_score + 0.4 × quant_score`, capped at 100 (5σ severity clip) | 2026-05-13 |
| Top-N | Default 20, configurable per-config | 2026-05-13 |
| Worker count | `recommend_max_workers(provider)`: 16 for FD/EODHD, 4 for Finnhub/hybrid | 2026-05-14 |
| News sentiment | Via FD `sentiment` field, or EODHD `/sentiments` daily aggregate (overlay on per-article) | 2026-05-13 |
| EODHD ticker format | Auto-append `.US` if no exchange suffix | 2026-05-14 |
| Std-floor for z-scores | News polarity ≥ 0.10, daily returns ≥ 0.005, volume std ≥ 10% of mean | 2026-05-14 |
| Extreme z-scores | NOT clipped at trigger level — `composite_score` already capped at 100 | 2026-05-14 |

## Performance Baseline (2026-05-14)

| Metric | Value |
|---|---|
| nasdaq100_sp500 scan time (hybrid, 4 workers) | **~330s (5.5min)** |
| Tickers triggered | 55 / 140 (39%) |
| Watchlist top-20 detector coverage | INSDR + PV + NEWS (3/4) |
| Earnings detector | 0 triggers (no fresh BEAT/MISS in last 5 biz days for these megacaps) |
| Total tests | **251 passing** (across M1-M3.6) |
| Data cost | $20/mo (EODHD basic) + $0 (Finnhub free) = **$20/mo total** |

## Errors Encountered

| Date | Error | Cause | Resolution |
|---|---|---|---|
| 2026-05-13 | FD `/insider-trades`, `/news`, etc. → 402 Payment Required | FD trial tier doesn't grant access beyond 5 free tickers | Add Finnhub provider as fallback (M3.5) |
| 2026-05-13 | FD `/news` → 400 Bad Request | Used `end_date=` but FD expects `end_date_lte=` | Changed FDClient.get_news to use `_lte/_gte` suffix |
| 2026-05-13 | FD `/news` → 400 "Invalid limit" | FD `/news` caps `limit ≤ 10`, we passed 1000 | Clip limit in FDClient.get_news |
| 2026-05-13 | `'CompanyFacts' object has no attribute 'market_cap'` | v2/data/models.py CompanyFacts missing market_cap field | Added `market_cap: float \| None` |
| 2026-05-13 | `EarningsRecord.filing_date` pydantic ValueError | FD returns null filing_date for some records (GOOGL) | Made field Optional + earnings detector filters |
| 2026-05-14 | Finnhub `/stock/candle` → 403 (free tier) | Endpoint moved to paid tier | Use EODHD `/eod/` for prices in hybrid mode |
| 2026-05-14 | EODHD `/insider-transactions`, `/calendar/earnings`, `/fundamentals/*` → 403 | Basic $20 tier doesn't include these endpoints | EODHDClient returns empty/None gracefully + hybrid uses Finnhub for these |
| 2026-05-14 | `NEWS(-333333.3)` extreme z-score | `or 1e-6` floor too low when baseline std = 0 (all-same labels) | Replaced with `max(std, 0.10)` for polarity, `max(std, 0.005)` for returns |
| 2026-05-14 | Existing test `test_unknown_kind_raises("nasdaq100")` failed | We added `nasdaq100` as a valid kind in M3.5.b | Changed test to use unknown kind `"fang_stocks"` |
| 2026-05-14 | `v2/event_study/test_event_study.py::test_compute_car_live` failed | Live FD smoke now runs (env var present) but FD tier blocks data | Out of scope — these are SKIP-by-design tests |

## Key Files

### v2 module (scanner core)
```
v2/data/
  protocol.py              DataClient Protocol (8 methods)
  models.py                Pydantic for Price/News/Insider/Earnings/CompanyFacts/FinancialMetrics
  client.py                FDClient
  finnhub_client.py        FinnhubClient
  eodhd_client.py          EODHDClient
  composite_client.py      CompositeClient + make_hybrid_client
  factory.py               make_data_client, get_provider_factory, recommend_max_workers
  __init__.py              Public exports

v2/scanner/
  models.py                ScoredEntry, ScannerWeights, ScanContext, Direction
  scoring.py               compute_composite (60/40 event/quant blend, 5σ severity clip)
  runner.py                run_scan(provider_factory, ...) + ScanProgress
  __main__.py              python -m v2.scanner CLI for smoke runs
  detectors/
    base.py                EventDetector ABC + EventTrigger pydantic
    earnings.py            EarningsSurpriseDetector (5 biz days window)
    insider.py             InsiderClusterDetector (≥3 distinct insiders or single > 1% MC)
    price_volume.py        PriceVolumeAnomalyDetector (uses adjusted_close when available)
    news_sentiment.py      NewsSentimentShiftDetector (7d vs 90d polarity z-shift)
  universes/
    sp500.csv              ~60 seed tickers (refresh in M6)
    nasdaq100.csv          ~100 seed tickers
    nyse_nasdaq_all.csv    ~100 seed tickers
    loader.py              load_universe(kind, custom) + _COMPOSITE map
    refresh_universes.py   Stub for M6
  event_study/
    filters.py             filter_retrospective_earnings (45-day rule, shared util)
    engine.py              compute_car (existing, FD-only)
```

### Backend
```
app/backend/
  database/models.py                       3 new tables: ScannerConfig, ScanRun, WatchlistEntry
  alembic/versions/e1f5a8c3b4d7_*.py       Migration for above
  repositories/scanner_repository.py       3 repos: ScannerConfigRepository, ScanRunRepository, WatchlistEntryRepository
  models/scanner_schemas.py                Pydantic Request/Response for /scanner/* (M4)
  services/scanner_service.py              ScannerService — orchestrates run, persists results
  services/scan_broadcaster.py             ScanBroadcaster — thread→asyncio pub/sub for SSE
  services/scheduler_service.py            ⏳ M4 — SchedulerService wrapping APScheduler
  routes/scanner.py                        ⏳ M4 — 8 REST endpoints
```

### Tests
```
tests/test_scanner_repository.py          M1 repository tests
tests/test_scanner_service.py             M3 service integration tests (in-memory SQLite)
tests/test_scan_broadcaster.py            M3 async pub/sub tests
v2/scanner/test_detectors.py              M2 detector tests + bug regression tests
v2/scanner/test_runner.py                 M3 runner tests + fd_factory deprecation
v2/data/test_finnhub_client.py            M3.5 Finnhub adapter
v2/data/test_eodhd_client.py              M3.6 EODHD adapter
v2/data/test_composite_client.py          M3.6 CompositeClient routing
v2/data/test_factory.py                   M3.5+M3.6 provider factory
v2/data/test_protocol_conformance.py      All 3 clients satisfy DataClient Protocol
```

## Environment

- **Python**: anaconda 3.13 at `C:\Users\Jerry\anaconda3\python.exe`. Poetry NOT on PATH.
- **Test runner**: `$env:PYTHONPATH = "C:\Users\Jerry\Desktop\ai-hedge-fund"; & "C:\Users\Jerry\anaconda3\python.exe" -m pytest ...`
- **Smoke runner**: `& "C:\Users\Jerry\anaconda3\python.exe" -m v2.scanner --provider hybrid --top 20`
- **Console**: PowerShell on Windows. Need `$env:PYTHONIOENCODING = "utf-8"` for the colored CLI output.
- **API keys**: `.env` has FINANCIAL_DATASETS_API_KEY, FINNHUB_API_KEY, EODHD_API_KEY, ALPHA_VANTAGE_API_KEY, FRED_API_KEY. `.env` is gitignored.

## Test Commands

Quick regression (excluding live FD smoke + LLM-dep tests):
```powershell
$env:PYTHONPATH = "C:\Users\Jerry\Desktop\ai-hedge-fund"
& "C:\Users\Jerry\anaconda3\python.exe" -m pytest v2 tests `
  --ignore=v2/event_study/test_event_study.py `
  --ignore=tests/backtesting `
  --ignore=v2/data/test_client.py `
  -q
```

Expected: **251 passed**.

Live smoke (hybrid, costs ~5 min wall-clock + FD/Finnhub/EODHD API calls):
```powershell
$env:PYTHONPATH = "C:\Users\Jerry\Desktop\ai-hedge-fund"
$env:PYTHONIOENCODING = "utf-8"
& "C:\Users\Jerry\anaconda3\python.exe" -m v2.scanner --provider hybrid --top 20
```
