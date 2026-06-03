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

NOTE: the manual `POST /scanner/configs/{id}/run` path should NOT trigger the workflow (only the cron does) — or gate it behind a flag — to avoid surprise emails on a manual run. Decide in the plan.

### C. Watchlist email

New `report_delivery.email_watchlist(db, user_id, *, config_name, entries) -> dict`: render a compact HTML table (rank, ticker, score, direction) → email to `verified_recipients`. Returns `{sent, failed}`. Never raises per-recipient.

### D. Standalone analyze schedule from the Analyze UI

Reuse `ReportSchedule` (Stage 3). Add a small "Schedule" control on the Analyze panel: prefill the current ticker(s) + a frequency picker → `POST /report-schedules`. No new backend.

### E. Analyze sidebar — concurrent run tracking

Refactor `analyze-panel.tsx`: replace the single `running: boolean` with a **runs list** `{id, ticker, status: 'running'|'done'|'failed', startedAt, elapsedMs, reportId?, error?}`. `handleRun` becomes non-blocking (pushes a run, fires the fetch, updates on settle) so multiple tickers can run at once. Add a right sidebar listing runs (spinner + live elapsed for running; ✓ + click-to-open for done; ✗ + message for failed). Run-state lives in a small context/store so it survives within the Analyze tab.

### F. Remove the 3 panel-layout toggle icons (top-right)

Find the layout-toggle control (3 split-pane icons) in the top toolbar/header and remove it (+ any now-dead handlers/state). Surgical.

## Data model summary

- `ScannerConfig` += 4 columns (additive migration).
- `ReportSchedule` — unchanged (reused).
- No other schema changes.

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
2. ScannerConfig: model + additive migration + create/update schema + repository passthrough.
3. Scanner config dialog: the 4 workflow toggles.
4. `report_delivery.email_watchlist`.
5. Scanner cron post-scan workflow (email list → top-N analyze → email reports), owner keys, never-crash.
6. Analyze-UI "Schedule" control (reuse ReportSchedule).
7. Analyze concurrent-run sidebar (runs store + non-blocking handleRun + sidebar component).
8. Screener parallel workflow (pending Open Item 1).
9. Any specific bugs the user enumerates.
