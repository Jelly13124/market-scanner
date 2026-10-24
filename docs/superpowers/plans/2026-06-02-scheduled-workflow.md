# Scheduled Watchlist Workflow + Analyze Sidebar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Scheduled scan/screen → email the watchlist → optional top-N auto-analyze → optional email reports, configured on the scanner config (+ manual "send to email"); a per-user timezone; an Analyze concurrent-run sidebar that survives tab switches; remove the Models settings section and the 3 layout icons.

**Architecture:** Extend `ScannerConfig` with workflow toggles + a post-scan step in the scanner cron job that reuses Stage 3's per-user-key `run_sop` + `report_delivery` email helpers. Per-user tz via `User.timezone` consumed by the scheduler's register methods. Frontend: scanner config dialog toggles, an Analyze schedule control (reuse `ReportSchedule`), and a hoisted runs-store + right sidebar.

**Tech stack:** FastAPI + SQLAlchemy + Alembic + APScheduler; Vite/React/TS.

**Constraints (CLAUDE.md):**
- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `-m pytest`; set `$env:PYTHONIOENCODING="utf-8"`.
- Frontend typecheck from `app/frontend/`: `node node_modules/typescript/bin/tsc --noEmit` (npm not on PATH).
- Alembic from `app/backend/` with `PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund`; **additive migrations only**, chain from current head **`dfdecadcbff0`**; new PK/int cols `BigInteger().with_variant(Integer(), "sqlite")` where relevant; `server_default` so existing rows backfill.
- Commit per task; conventional message; **NO Co-Authored-By**; never `--no-verify`.
- Every user-owned query MUST be `user_id`-scoped.
- **ALL subagents dispatched with `model: opus`.** Migration tasks ALSO run `alembic-migration-reviewer`; scanner detector/signal tasks (none here) would run `scanner-invariant-reviewer`.
- `create_all` only creates missing *tables*, not columns — adding columns to existing tables (`scanner_configs`, `users`) REQUIRES a migration.

---

### Task 1: Remove the 3 panel-layout toggle icons (top-right)

**Files:** locate via grep — likely `app/frontend/src/components/Layout.tsx` or a top toolbar/header component (the 3 split-pane icons in the screenshot).
- [ ] Grep the frontend for the layout-toggle control (icons like `PanelLeft`, `Columns`, `SquareSplit`, or a 3-button group toggling panel layout).
- [ ] Remove the 3-icon control + any now-unused handlers/state/imports it owned. Don't touch unrelated layout logic.
- [ ] Verify: `node node_modules/typescript/bin/tsc --noEmit` from `app/frontend/` — zero NEW errors.
- [ ] Commit.

### Task 2: Remove the "Models" section from Settings

**Files:** `app/frontend/src/components/settings/settings.tsx`
- [ ] Remove the `models` nav item (the `{ id: 'models', ... }` entry), its `case 'models': return <Models />;` render branch, and the `Models` import. If `selectedSection` defaults to `'models'` anywhere, change the default to `'api'`.
- [ ] Leave `models/` component files in place (just unlinked).
- [ ] Verify: tsc clean. Settings renders without a Models tab.
- [ ] Commit.

### Task 3: `User.timezone` + Settings timezone dropdown

**Files:** `app/backend/database/models.py`, `app/backend/alembic/versions/<new>.py`, a Settings UI surface, an endpoint to read/update the user's tz.
- [ ] Add `timezone = Column(String(64), nullable=False, server_default="America/New_York")` to the `User` model.
- [ ] Migration chaining from `dfdecadcbff0`: `op.add_column("users", sa.Column("timezone", sa.String(64), nullable=False, server_default="America/New_York"))`; downgrade drops it. SQLite-safe.
- [ ] Backend: add `timezone` to the user-profile read (`/auth/me` response or a `GET /auth/me`) and a `PATCH /auth/me` (or a small `/settings/timezone`) to update it, scoped to `current_user`. Validate against `zoneinfo.available_timezones()` (or a curated list).
- [ ] Frontend: a Settings section (or fold into an existing one) with a timezone `<select>` of common IANA zones (America/New_York, America/Los_Angeles, Europe/London, Asia/Shanghai, Asia/Tokyo, …) wired to the new endpoint.
- [ ] **Also dispatch `alembic-migration-reviewer`** before code-quality review.
- [ ] Verify: migration up/down on a temp DB; backend tests green; tsc clean.
- [ ] Commit.

### Task 4: Scheduler honors each user's timezone

**Files:** `app/backend/services/scheduler_service.py`
- [ ] In `_register` (scanner configs) and `register_report_schedule`, resolve the owner's tz (`User.timezone` via a session lookup by the config/schedule `user_id`) and pass it to `CronTrigger.from_crontab(expr, timezone=owner_tz)` instead of the global `self._tz`. Fall back to `self._tz` if the user has no tz.
- [ ] When a user changes tz (Task 3 endpoint), re-register all of that user's scanner-config crons + report-schedule crons with the new tz.
- [ ] Startup registration uses each owner's tz.
- [ ] Verify: backend tests green; a unit test that a config owned by a user with `timezone="Asia/Shanghai"` registers a trigger in that zone.
- [ ] Commit.

### Task 5: `ScannerConfig` workflow columns + schema + repo

**Files:** `app/backend/database/models.py`, `app/backend/alembic/versions/<new>.py`, `app/backend/models/scanner_schemas.py`, `app/backend/repositories/scanner_repository.py`
- [ ] Add to `ScannerConfig`: `email_watchlist` (Boolean, server_default false), `auto_analyze` (Boolean, false), `analyze_top_n` (Integer, server_default "5"), `email_reports` (Boolean, false).
- [ ] Additive migration chaining from the Task-3 migration (single linear chain): `add_column` ×4 with server_defaults; downgrade drops them.
- [ ] `ScannerConfigCreateRequest` / `ScannerConfigUpdateRequest` / `ScannerConfigResponse`: add the 4 fields (defaults matching). Repository `create`/`update` persist them.
- [ ] **Dispatch `alembic-migration-reviewer`.**
- [ ] Verify: migration up/down; create a config via repo with the new fields; backend tests green.
- [ ] Commit.

### Task 6: Scanner config dialog — workflow toggles

**Files:** `app/frontend/src/components/panels/scanner/scanner-config-dialog.tsx`, scanner types/service.
- [ ] Add a "Schedule & delivery" group: checkbox `email_watchlist`; checkbox `auto_analyze` + a number `analyze_top_n` (1–20, shown only when auto_analyze on); checkbox `email_reports` (shown only when auto_analyze on). Wire into the create/update payload + the scanner service + types.
- [ ] Small helper text: "Emails go to verified addresses in Settings → Report emails."
- [ ] Verify: tsc clean; toggles round-trip (create → reopen shows saved values).
- [ ] Commit.

### Task 7: `report_delivery.email_watchlist`

**Files:** `app/backend/services/report_delivery.py`
- [ ] `email_watchlist(db, user_id, *, config_name, entries) -> dict`: render a compact HTML table (rank, ticker, score, direction) from the watchlist entries; subject `Quant Lab watchlist — {config_name}`; send to `verified_recipients`; return `{sent, failed}`; never raise per-recipient.
- [ ] Verify: unit test with a fake EmailHandler (or RESEND unset → status error path) that it builds HTML + returns the shape.
- [ ] Commit.

### Task 8: Scanner cron post-scan workflow

**Files:** `app/backend/services/scheduler_service.py` (+ a `_post_scan_workflow(config_id, run_id)` helper)
- [ ] After `ScannerService.execute(config_id)` returns in `_run_job`, call `_post_scan_workflow`. It: loads the config + the run's `WatchlistEntry` rows (owner-scoped); if `email_watchlist` → `email_watchlist(...)`; if `auto_analyze` → take top-`analyze_top_n` by score, fetch the OWNER's keys (`ApiKeyService(db, config.user_id)`), for each ticker `run_sop(AnalyzeRequest(...defaults, report_language from?...), api_keys)` → `render_sop` → if `email_reports` → `email_report_html`. Mirror `_run_report_schedule_job` (never raise, skip when no verified recipients / no owner LLM key, top-N cap).
- [ ] Make `_post_scan_workflow` reusable by Task 9 (manual run).
- [ ] Verify: backend tests green; a test that with `auto_analyze` off + `email_watchlist` on, only the watchlist email path is exercised (mock run_sop).
- [ ] Commit.

### Task 9: Manual run "send to email"

**Files:** `app/backend/routes/scanner.py`, `app/frontend/src/components/panels/scanner/scanner-panel.tsx`, scanner service.
- [ ] `POST /scanner/configs/{id}/run` accepts `send_email: bool = False` (query or body). When true, after the manual scan completes, run `_post_scan_workflow` (same as cron). Plumb through `ScannerService.execute_async` completion or have the route schedule the workflow after the run finishes.
- [ ] Run-now button gets a "send to email" checkbox; pass it to `runNow`.
- [ ] Default OFF.
- [ ] Verify: backend tests green; tsc clean.
- [ ] Commit.

### Task 10: Analyze-UI "Schedule" control

**Files:** `app/frontend/src/components/panels/analyze/*` (toolbar or input node), reuse `report-schedules-api`.
- [ ] Add a "Schedule" control near Run: prefill the current ticker, a frequency (daily/weekdays/weekly) + time, language → `reportSchedulesService.create(...)`. Toast on success; link to Settings → 定时报告 to manage.
- [ ] Verify: tsc clean; creating a schedule from Analyze shows up in Settings → Scheduled reports.
- [ ] Commit.

### Task 11: Analyze concurrent-run sidebar (persists across tabs)

**Files:** new `app/frontend/src/contexts/analyze-runs-context.tsx`; mount in `main.tsx`/`Layout.tsx` ABOVE the tab switcher; `analyze-panel.tsx`; new `analyze-runs-sidebar.tsx`.
- [ ] Context store: `runs: {id, ticker, status:'running'|'done'|'failed', startedAt, reportId?, error?}[]` + `startRun(req)` (pushes a run, fires `analyzeService.runAnalyze` NON-blocking, updates the run on settle) + `clear`. Elapsed computed from `startedAt`.
- [ ] Mount the provider above `Layout`/tab switcher so it does NOT unmount on tab switch.
- [ ] `analyze-panel.tsx`: `handleRun` delegates to `startRun` (no local `running` boolean blocking concurrency; keep current-report display working for the latest done run).
- [ ] Right sidebar component: list runs — spinner + live elapsed (running), ✓ + click-to-open report (done), ✗ + message (failed). Render it on the Analyze tab's right edge.
- [ ] Verify: tsc clean; start two analyses, switch to another tab and back — both still show with live timers; a done one opens its report.
- [ ] Commit.

### Task 12: Screener parallel workflow (pending Open Item 1)

- [ ] First investigate: does the Screener (Phase 1) have a per-user *scheduled* config? If yes, add the same 4 workflow toggles + post-run delivery. If its scheduling is global only, STOP and report — per-user screener scheduling is a separate spec (note it; do not invent one).
- [ ] Commit only if there's a clean per-user surface; otherwise document the finding in `findings.md`.

### Task 13: Further enumerated bugs

- [ ] Address any additional specific bugs the user lists (separate discrete tasks, TDD where applicable).

---

## Self-review

- Spec coverage: Tasks 1–11 cover spec sections A–G + the manual-send + persistence additions. Task 12 = Open Item 1. ✓
- Migrations: Tasks 3 & 5 add columns to existing tables (required) — single linear chain from `dfdecadcbff0`, additive, reviewed by `alembic-migration-reviewer`. ✓
- Per-user keys: Task 8 uses the config OWNER's keys (not host) for auto-analyze, mirroring Stage 3. ✓
- Naming consistency: `_post_scan_workflow` defined in Task 8, reused in Task 9. `email_watchlist`/`email_report_html`/`verified_recipients` in `report_delivery`. ✓
