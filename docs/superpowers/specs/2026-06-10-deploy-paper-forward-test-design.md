# Deploy the Paper Forward-Test Unattended — Design

**Date:** 2026-06-10
**Status:** approved (design greenlit; spec pending user review → writing-plans)
**Sub-project:** A (of the 4-track roadmap: A clock / B+C edge-search engine / D research tool)

## Goal

Make the multi-sleeve paper-trading forward test run **continuously and unattended** on the
live Fly app, accruing real out-of-sample data, so that in ~3 months we have an honest
verdict on whether any of our machinery (scanner, agent, institutional-flow) has edge. Today
the forward test is **frozen at a single equity mark dated 2026-06-08** because it only runs
when the user manually invokes the CLI on a laptop that sleeps.

## Why this is mostly deploy, not build

The harness + scheduler are already wired end-to-end; nothing in the loop needs writing:

- `fly.toml`: `DATABASE_URL=sqlite:////data/app.db` on a **persisted volume**;
  `auto_stop_machines=false` + `min_machines_running=1` keep one always-on machine for
  APScheduler + the SQLite volume.
- `docker/entrypoint.sh` runs `alembic upgrade head` against the volume on boot → the
  paper-trading migration `f0a1b2c3d4e5` (alembic-reviewer-approved, additive) applies to
  prod automatically.
- `app/backend/main.py` startup event calls `SchedulerService.start()`, wrapped in
  try/except (a scheduler failure logs but never takes the API down).
- `SchedulerService.start()` → `_register_paper_trading_jobs()` registers
  `paper_weekly` (Mon 17:00 ET) + `paper_daily_marks` (weekdays 17:05 ET), both triggered
  in `America/New_York` regardless of the Tokyo machine tz.

**The gap is purely that none of this is deployed:** 23 commits (the entire paper-trading +
institutional-flow + self-evolve work) are unpushed; the live app predates all of it.

## Scope decision — v1 runs the 4 light sleeves only

The forward test has 5 sleeves. Four are cheap (a scan + an agent call over the top-5):
`scanner_agent`, `scanner_only`, `spy_benchmark`, `scanner_agent_flow`. The fifth,
`factor_evolved`, is **not cheap**: its live `factor_fn` rebuilds a full nasdaq100 ×3-year
bundle **with fundamental enrich** on every run — the ~30-minute operation we observed during
the self-evolve run — which on a 2 GB shared prod machine risks a 30-min stall / OOM that
could degrade the live app serving real users. The factor strategy is also **monthly** by
design, so a weekly rebuild is wasteful.

**v1 therefore runs the 4 light sleeves unattended. `factor_evolved` joins the forward test
after sub-project B+C** speeds up the backtest/bundle path — the natural hand-off. This needs
a small, env-gated sleeve filter (below).

## The one code change — env-gated active sleeves

Add a module-level `active_sleeves() -> tuple[str, ...]` to `src/paper_trading/sleeves.py`
that reads `PAPER_SLEEVES` (comma-separated) and falls back to the full `SLEEVE_NAMES` when
unset — so local behavior (all 5) is unchanged and only prod narrows the set.

- `run_once` (in `src/paper_trading/run.py`) iterates `active_sleeves()` instead of
  `SLEEVE_NAMES`, so `factor_evolved` is never seeded/rebalanced on prod.
- `marks` naturally follows: `mark_all` only marks sleeves present in the DB, and an
  unseeded sleeve has no rows.
- Prod sets `PAPER_SLEEVES="scanner_agent,scanner_only,spy_benchmark,scanner_agent_flow"`
  via `fly.toml [env]` (non-secret).
- Tests: `active_sleeves()` returns all 5 when unset; the configured subset when set; an
  unknown name in the env is dropped with a warning (never raises).

This is the only source change in A; everything else is deploy/ops + verification.

## Ownership — "I prepare, you press the buttons"

The live app serves real users; outward/irreversible commands are the user's to run. Claude
prepares every artifact (the source change, the exact command list, a verification script,
the rollback commands) and interprets all output. The **user** executes the `fly` / `git push`
commands in-session via the `!` prefix so output lands in the conversation. Keys are never
echoed or committed.

## Runbook (data flow)

**Claude, local, no outward effect:**
0. Land the `active_sleeves()` change (TDD) + set `PAPER_SLEEVES` in `fly.toml [env]`; run the
   full `src/paper_trading/` + touched suites green; verify the prod import path
   (`src.paper_trading.run` → scheduler job) does **not** import `alpaca` or otherwise need a
   non-prod dependency at module load (AlpacaBroker is lazy; default path is FakeBroker).

**User, outward (each its own `!` command; Claude interprets the output):**
1. `git push origin main` — 23 commits (also the overdue backup).
2. `fly secrets list` — Claude confirms `DEEPSEEK_API_KEY` + a data-provider key
   (EODHD / FINNHUB) are present; Claude supplies `fly secrets set` for any missing.
3. `fly volumes snapshots create <vol-id>` — pre-deploy DB snapshot (insurance).
4. `fly deploy` — entrypoint runs `alembic upgrade head`, uvicorn boots, scheduler registers.
5. `fly logs` — confirm "Registered cron job paper_weekly / paper_daily_marks", scheduler
   started, no startup traceback, `/health` green.
6. `fly ssh console -C "python -m src.paper_trading.run --once --marks"` — **seed now**:
   create the 4 sleeves on the prod DB, open initial positions, write the first marks, so the
   clock starts immediately instead of waiting for Monday's cron.
7. `fly ssh console -C "python -m src.paper_trading.run --report"` — confirm the 4 sleeves
   exist with positions + equity. Forward test is live.

## Verification criteria (definition of done)

- `fly logs` shows both paper cron jobs registered + no boot crash + `/health` 200.
- After step 6, the prod DB has exactly the 4 configured sleeves, each with ≥1 position
  (except spy_benchmark = SPY) and ≥1 equity mark dated today.
- `factor_evolved` is **absent** from the prod DB (proving the env gate works).
- A follow-up `--report` 1–2 days later shows a second daily mark (proving the daily-marks
  cron fires unattended).

## Rollback plan

- Boot failure → `fly releases` + `fly releases rollback` to the prior image (the API is
  back in seconds; the new code is additive so a rollback loses only the forward test, not
  user data).
- DB migration corruption → restore the step-3 volume snapshot.
- Scheduler-only failure → no action needed; main.py isolates it (API stays up); fix forward.

## Risks + mitigations

- **Shipping 23 commits to a live app.** Mitigations: additive migrations
  (alembic-reviewer-approved); startup scheduler try/except-isolated; new surfaces (tables,
  routes, tabs) are additive; pre-deploy snapshot + one-command rollback; watch boot logs.
- **Agent-sleeve keys missing on prod** → those sleeves error per-week (isolated); the others
  still accrue. Verified in step 2 before deploy.
- **Weekly cost on prod**: the weekly job runs the scanner + a DeepSeek agent call (small
  spend) + daily data fetches, on the existing machine that already runs the nightly scanner.
- **factor_evolved OOM risk** — removed from v1 by the env gate.

## Observability

- v1: `fly ssh console -C "... --report"` on demand (Markdown/HTML summary of the 4 sleeves).
- Fast-follow (folds into sub-project D): a read-only frontend paper-trading panel
  (equity curves per sleeve) so the forward test is visible without SSH.

## Out of scope (v1)

- `factor_evolved` unattended — deferred to **after B+C** (needs the fast backtest/bundle).
- A frontend paper-trading dashboard — **sub-project D** (or a fast-follow).
- Migrating the local 1-day forward-test DB to prod — abandoned; prod starts fresh (the local
  DB has a single 2026-06-08 mark; nothing worth porting).
- Litestream / continuous SQLite backup — Fly's daily volume snapshots suffice for v1.

## Testing

- Offline unit tests for `active_sleeves()` (unset → all 5; set → subset; unknown → dropped,
  no raise) + `run_once` iterating the filtered set (stub seams, scratch SQLite).
- The deploy itself is verified live by the step-5/6/7 criteria above (not by the test suite).
