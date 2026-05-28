---
name: screener-snapshot-trigger
description: Manually trigger the Screener nightly snapshot build (S&P 500 + CSI 300) without waiting for the 22:00 ET cron, then verify rows landed. Use when the user wants Screener data NOW, says "trigger snapshot", "build the screener snapshot", "跑一下快照", or the Screener tab shows the empty state and they want real data.
disable-model-invocation: true
---

# Trigger Screener snapshot build

Runs the same job the 22:00 ET cron runs (`_run_snapshot_job_body`): builds the
US snapshot (yfinance, S&P 500) then the CN snapshot (mootdx + akshare, CSI 300),
upserts into `ticker_snapshots`, then cleans up rows older than 30 days.

## Cost / time

- **US (~500 tickers via yfinance): ~15-20 min.**
- **CN (~300 tickers via mootdx + akshare): ~3-5 min.**
- It hits live data APIs. Per-ticker failures are logged + skipped (the job never
  aborts on one bad ticker). If a whole market's source is down it logs and moves
  on; the other market still builds.

Warn the user about the runtime before starting. Consider `run_in_background: true`
so you don't block, then poll the output.

## Steps

### 1. Ensure the migration is applied

```
C:\Users\Jerry\anaconda3\python.exe -m alembic upgrade head
```
(no-op if already at head `d4e8a2c1b9f6` or later)

### 2. Run the snapshot job

Run with the Bash tool (consider `run_in_background: true` given the runtime):
```
PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 /c/Users/Jerry/anaconda3/python.exe -c "from app.backend.services.scheduler_service import _run_snapshot_job_body; _run_snapshot_job_body()"
```
Expected log lines:
```
screener snapshot US: <N> rows
screener snapshot CN: <N> rows
screener snapshot cleanup deleted <N> old rows
```

### 3. Verify rows landed

If the backend is running on :8001:
```
curl -s http://127.0.0.1:8001/screener/snapshot/status
```
Expect `row_count` ~800 and `by_market` like `{"US": ~500, "CN": ~300}`.

Or query the DB directly:
```
C:\Users\Jerry\anaconda3\python.exe -c "from app.backend.database import SessionLocal; from app.backend.repositories.screener_repository import ScreenerRepository; db=SessionLocal(); r=ScreenerRepository(db); print('latest:', r.latest_snapshot_date()); rows,total=r.query(limit=5); print('total:', total, '| sample:', [x.ticker for x in rows]); db.close()"
```

## Notes

- US-only is a valid partial result if CN (akshare/mootdx) is unreachable from
  outside China — that still proves the pipeline end-to-end.
- After a successful build, the frontend Screener tab will show data instead of
  the empty state (refresh the tab; it re-queries on mount).
- Do NOT pass `--reload` anywhere; this is a one-shot script, not a server.
