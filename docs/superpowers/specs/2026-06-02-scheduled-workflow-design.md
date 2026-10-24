# Scheduled Watchlist Workflow + Analyze Sidebar — Design

**Date:** 2026-06-02
**Branch:** feature/per-user-keys (current)

## Goal

A daily, hands-off pipeline the user configures once:

1. A **scheduled scan/screen** produces a watchlist (already exists for the scanner — per-user cron).
2. **Email the watchlist** (tickers + scores) to the user's verified report emails.
3. **Optionally auto-analyze** the top-N watchlist tickers (run the SOP with the owner's keys).
4. **Optionally email** each generated report to the verified recipients.

Configurable directly from the **Scanner** UI (and the **Screener**), plus a standalone "schedule this analysis" entry from the **Analyze** UI. Two side asks bundled in: a right **sidebar in Analyze that tracks concurrently running analyses**, and **removing the 3 panel-layout toggle icons** in the top-right.

## Decisions (from brainstorming, 2026-06-02)

- **Trigger source:** both Scanner (detector scan) and Screener (financial screen).
- **Config home:** extend the existing **Scanner config** (it already has per-user cron + watchlist) with workflow toggles — no separate "workflow" entity. The Screener gets the same toggles on its per-user scheduled config (see Open Items).
- **Auto-analyze scope:** **Top-N** (configurable, default 5) — cost control.

## Current-state facts (load-bearing)

- `ScannerConfig` already has `cron_expr` + the `SchedulerService` registers a per-user cron per config (`scanner-config-{id}`). The cron job calls `ScannerService.execute(config_id)` which produces a `ScanRun` + `WatchlistEntry` rows.
- **Stage 3 already shipped:** `ReportSchedule` model + `/report-schedules` CRUD + `_run_report_schedule_job` (per-user `run_sop` → `render_sop` → `report_delivery.email_report_html`). The standalone analyze schedule reuses this.
- `report_delivery.email_report_html(db, user_id, *, ticker, html)` and `verified_recipients(db, user_id)` exist (Stage 2).
- Adding columns to the **existing** `scanner_configs` table needs an **additive Alembic migration** — `create_all` only creates missing *tables*, not missing *columns*, and the deployed DB already has the table. New tables (e.g. side tables) are still fine via `create_all`.

## Architecture

### A. Workflow fields on the scanner config

Extend `ScannerConfig` (model + additive migration chaining from head `dfdecadcbff0`):

| column | type | default | meaning |
|---|---|---|---|
| `email_watchlist` | Boolean | false | after a scheduled scan, email the watchlist |
| `auto_analyze` | Boolean | false | after a scan, run SOP on the top-N tickers |
| `analyze_top_n` | Integer | 5 | how many top tickers to analyze (1–20) |
| `email_reports` | Boolean | false | email each auto-analyze report |

Migration: `op.add_column(... server_default=...)` for each, SQLite-compatible. Reviewed by `alembic-migration-reviewer`.

### B. Post-scan chaining (the scanner cron job)

In `SchedulerService._run_job(config_id)` (or a `_post_scan_workflow(config_id, run_id)` helper called after `execute`):

1. Load the config + the just-finished run's watchlist entries (owner-scoped).
2. If `email_watchlist`: `report_delivery.email_watchlist(...)`.
3. If `auto_analyze`: take the top-`analyze_top_n` entries by score; fetch the **owner's** keys (`ApiKeyService(db, config.user_id)`); for each ticker `run_sop(AnalyzeRequest(...), api_keys=...)` → `render_sop` → (if `email_reports`) `email_report_html`. Mirror `_run_report_schedule_job` exactly (per-user keys, never-raises, top-N cap).
4. Skip cleanly if no verified recipients / no owner LLM key (log, don't crash the cron).

**Manual run + "send to email" (decided 2026-06-02):** the cron always runs the post-scan workflow per the config toggles. The manual `POST /scanner/configs/{id}/run` also accepts a `send_email` flag and the Run-now button gets a **"send to email" checkbox**; when checked, the same post-scan workflow runs after the manual scan (respecting the config's email_watchlist / auto_analyze / email_reports). Default OFF, so a plain manual scan never emails.

### C. Watchlist email

New `report_delivery.email_watchlist(db, user_id, *, config_name, entries) -> dict`: render a compact HTML table (rank, ticker, score, direction) → email to `verified_recipients`. Returns `{sent, failed}`. Never raises per-recipient.

### D. Standalone analyze schedule from the Analyze UI

Reuse `ReportSchedule` (Stage 3). Add a small "Schedule" control on the Analyze panel: prefill the current ticker(s) + a frequency picker → `POST /report-schedules`. No new backend.

### E. Analyze sidebar — concurrent run tracking

Refactor `analyze-panel.tsx`: replace the single `running: boolean` with a **runs list** `{id, ticker, status: 'running'|'done'|'failed', startedAt, elapsedMs, reportId?, error?}`. `handleRun` becomes non-blocking (pushes a run, fires the fetch, updates on settle) so multiple tickers can run at once. Add a right sidebar listing runs (spinner + live elapsed for running; ✓ + click-to-open for done; ✗ + message for failed).

**Persistence across tab switches (decided 2026-06-02):** the run-state store MUST live in a context/provider mounted ABOVE the tab switcher (e.g. wrapping `Layout`), NOT inside `AnalyzePanel`. Switching tabs unmounts `AnalyzePanel`; if the runs list lived there it would reset. With the store hoisted, switching away and back leaves the sidebar (running spinners, elapsed timers, completed runs) intact, and in-flight fetches keep updating it. `handleRun` dispatches into this store rather than local `useState`.

### F. Remove the 3 panel-layout toggle icons (top-right)

Find the layout-toggle control (3 split-pane icons) in the top toolbar/header and remove it (+ any now-dead handlers/state). Surgical.

### G. Settings cleanup + per-user timezone (added 2026-06-02)

- **Remove the "Models" section** from Settings: drop the `models` nav item + its render case + the `Models` import in `settings.tsx`. The Models component file may stay in the tree, just unlinked.
- **Timezone selector:** add `User.timezone` (String, default `"America/New_York"`; additive migration) + a Settings dropdown of common IANA zones. The scheduler interprets each user's cron in THEIR timezone — the register methods (scanner-config crons AND report-schedule crons) look up the owner's tz and pass it to `CronTrigger.from_crontab(expr, timezone=user_tz)` instead of the global `self._tz`. When a user changes tz, re-register their jobs; startup registration uses each owner's tz.

## Data model summary

- `ScannerConfig` += 4 columns (`email_watchlist`, `auto_analyze`, `analyze_top_n`, `email_reports`) — additive migration.
- `User` += `timezone` (String, default America/New_York) — additive migration.
- `ReportSchedule` — unchanged (reused).

## API summary

- `ScannerConfig` create/update schema + the scanner config dialog gain the 4 workflow fields.
- `/report-schedules` (exists) — reused by the Analyze-UI schedule control.
- No new endpoints strictly required (watchlist email + analyze chaining run inside the cron job).

## UI summary

- **Scanner config dialog:** a "Schedule & delivery" group — email-watchlist toggle; auto-analyze toggle + top-N number; email-reports toggle. (Cron itself already in the dialog.)
- **Analyze panel:** a "Schedule" control (reuse ReportSchedule) + the concurrent-run **sidebar**.
- **Top-right:** remove the 3 layout icons.

## Open items / risks

1. **Screener "both":** confirm the Screener has a per-user *scheduled* config to hang the same toggles on. If its scheduling is global (snapshot/preset crons), per-user screener workflows are a follow-up — flag in the plan, don't block the scanner path.
2. **Migration on a live table:** additive `ADD COLUMN` with server_default — safe on SQLite; verify up/down symmetry.
3. **Cost:** auto-analyze is top-N, needs the owner's LLM key + ≥1 verified recipient; the cron must skip (not crash) when missing.
4. **Per-user keys in the scan cron:** the scan itself may use host data keys, but the analyze chaining MUST use the config owner's keys (like Stage 3).
5. **Sidebar refactor** touches the core analyze run flow — keep the single-run behavior working; concurrency is additive.
6. **"Lots of small bugs":** beyond the 3 icons, the user to enumerate specific bugs — folded into the plan as discrete tasks.

## Task outline (for writing-plans)

1. Remove the 3 layout icons (+ dead code). [trivial, isolated]
2. Remove the "Models" section from Settings (nav item + render case + import). [trivial]
3. `User.timezone`: model + additive migration + Settings timezone dropdown (IANA list).
4. Scheduler per-user timezone: register methods look up the owner's tz; re-register on change; startup uses each owner's tz.
5. `ScannerConfig`: model + additive migration (4 workflow cols) + create/update schema + repository passthrough.
6. Scanner config dialog: the 4 workflow toggles (email watchlist / auto-analyze + top-N / email reports).
7. `report_delivery.email_watchlist`.
8. Scanner cron post-scan workflow (email list → top-N analyze → email reports), owner keys, never-crash.
9. Manual run "send to email": `/run` accepts a `send_email` flag → runs the post-scan workflow; Run-now gets a checkbox.
10. Analyze-UI "Schedule" control (reuse ReportSchedule).
11. Analyze concurrent-run sidebar: runs store **hoisted above the tab switcher** (persists across tab switch) + non-blocking `handleRun` + the sidebar component.
12. Screener parallel workflow (pending Open Item 1).
13. Any further specific bugs the user enumerates.
