# Paper-Trading Forward-Test Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Each task = failing test → minimal impl → green → commit. Steps use `- [ ]`.

**Goal:** A zero-risk live paper-trading harness (3-sleeve live A/B: scanner+agent vs scanner-only vs SPY) on Alpaca paper, to forward-test whether the workflow makes money before any real capital.

**Architecture:** New `src/paper_trading/` package. All broker I/O behind a `BrokerClient` Protocol (`AlpacaBroker` live paper + `FakeBroker` for offline tests). A weekly engine computes equal-weight long target positions per sleeve, enters/exits via the broker, persists to SQLite; a daily marker writes equity; performance + graduation-bar evaluation drive a report. Reuses `run_scan`, `run_agents_only`, `PerformanceMetricsCalculator`, the scheduler, and `charts/render`.

**Tech Stack:** Python (anaconda `C:\Users\Jerry\anaconda3\python.exe`), SQLAlchemy + Alembic (**SQLite**), pytest (offline), `alpaca-py` (lazy import, live only).

**Constraints (every task):** tests OFFLINE — no network, no LLM, no real orders (FakeBroker + injected `run_scan_fn`/`agent_fn` stubs). Run tests `PYTHONIOENCODING=utf-8 PYTHONPATH=C:/Users/Jerry/Desktop/ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest <path> -q`. Conventional commit per task, **NO Co-Authored-By**, never `--no-verify`, explicit `git add <paths>` (never `-A`, never stage `.claude/settings.local.json`). Branch main. Additive Alembic migration chaining from current head. **Stay on SQLite.**

---

### Task 1: Package skeleton + BrokerClient protocol + FakeBroker

**Files:** Create `src/paper_trading/__init__.py`, `src/paper_trading/broker.py`, `src/paper_trading/test_broker.py`.

- [ ] **Test first:** `FakeBroker` starts with configurable cash; `submit_market_order(symbol, notional|qty, side="buy")` fills deterministically at an injected price map; `get_positions()` returns held qty/avg-price; `get_account()` returns cash + equity; `close_position(symbol)` sells all at the price map; selling more than held or unknown symbol is handled (no raise). Buying respects cash (no negative cash).
- [ ] **Impl:** `BrokerClient` is a `typing.Protocol` with `submit_market_order`, `get_positions`, `get_account`, `get_last_price`, `close_position`. `FakeBroker` is an in-memory deterministic impl taking a `prices: dict[str,float]` (mutable, so tests can move marks). No network. `AlpacaBroker` is a stub class here (filled in Task 8) — do not import alpaca in this task.
- [ ] Green + commit: `feat(paper-trading): BrokerClient protocol + deterministic FakeBroker`.

### Task 2: DB models + Alembic migration

**Files:** Modify `app/backend/database/models.py` (add 4 tables); create migration under `app/backend/alembic/versions/`; create `src/paper_trading/test_models_migration.py`.

- [ ] **Test first:** importing the models exposes `PaperSleeve`, `PaperPosition`, `PaperOrder`, `PaperEquityMark`; a SQLite `create_all` + insert/read round-trips one row of each; the migration's `upgrade()`/`downgrade()` are symmetric on a scratch SQLite engine.
- [ ] **Impl:** `paper_sleeve(id, name UNIQUE, starting_cash, created_at)`. `paper_position(id, sleeve_id FK, ticker, shares, entry_date, entry_price, exit_date NULL, exit_price NULL, status[open|closed])`. `paper_order(id, sleeve_id FK, ticker, side, qty, price, status[filled|rejected], week_key, created_at)`. `paper_equity_mark(id, sleeve_id FK, date, equity)`. Use the existing Integer/`Numeric` patterns; SQLite-compatible types (note the `id` Integer-variant gotcha from prior migrations). Migration `down_revision` = current head (find via `alembic heads` / the latest versions file).
- [ ] Green + commit: `feat(paper-trading): paper sleeve/position/order/equity tables + migration`. **(alembic-migration-reviewer should review.)**

### Task 3: Sleeve target-position logic

**Files:** Create `src/paper_trading/sleeves.py`, `src/paper_trading/test_sleeves.py`.

- [ ] **Test first:** `compute_targets(sleeve_name, scan_date, *, run_scan_fn, agent_fn, top_n)` returns a list of target tickers. `scanner_agent` → only the agent's `buy` calls (agent_fn stub returns a decisions dict). `scanner_only` → all top_n picks. `spy_benchmark` → `["SPY"]`. Empty scan → `[]` (never raise). Agent failure → falls back to empty (logged), never raises.
- [ ] **Impl:** thin functions over injected `run_scan_fn` (returns ranked tickers; mirror how the backtest's `scanner_arm` normalizes `run_scan`) and `agent_fn` (mirror `run_agents_only` → keep `action=="buy"`). No real scan/LLM here — both injected.
- [ ] Green + commit: `feat(paper-trading): per-sleeve long-only target-position logic`.

### Task 4: Engine — weekly enter/exit runner (against FakeBroker)

**Files:** Create `src/paper_trading/engine.py`, `src/paper_trading/test_engine.py`.

- [ ] **Test first:** given a sleeve with open positions and a target list: positions aged ≥ `hold_days` are **exited** (close_position), brand-new targets are **entered** equal-weight from available cash (cash-aware, fractional or whole shares — pick whole, floor), positions still within hold window are **kept**. Re-running the same `week_key` is **idempotent** (no double orders — second run places zero new orders). All against `FakeBroker` + a fake persistence layer (in-memory or a SQLite scratch session). No network.
- [ ] **Impl:** `run_week(sleeve, scan_date, week_key, *, broker, session, run_scan_fn, agent_fn, top_n, hold_days, per_name_fraction)`. Order: load open positions → exit aged → compute targets (Task 3) → enter new (skip names already held) → persist orders/positions. Guard idempotency by checking for existing `paper_order` rows with this `week_key`+sleeve.
- [ ] Green + commit: `feat(paper-trading): weekly equal-weight enter/exit engine (idempotent)`.

### Task 5: Daily mark-to-market

**Files:** Create `src/paper_trading/marks.py`, `src/paper_trading/test_marks.py`.

- [ ] **Test first:** `mark_sleeve(sleeve, date, *, price_fn, session)` computes equity = cash + Σ(shares × price_fn(ticker)) and appends one `paper_equity_mark`; missing price → skip that name (no raise); marking the same date twice **upserts** (one row per date).
- [ ] **Impl:** `price_fn` injected (live wiring uses the hybrid client's `get_last_price` / latest close). Cash tracked from fills (or derived from the broker's `get_account` for the live path; for the sim path, from realized P&L). Keep it pure over the injected `price_fn` + session.
- [ ] Green + commit: `feat(paper-trading): daily mark-to-market equity tracking`.

### Task 6: Performance metrics + A/B + graduation verdict

**Files:** Create `src/paper_trading/performance.py`, `src/paper_trading/test_performance.py`.

- [ ] **Test first:** given equity-mark series per sleeve, `compute_performance(session)` returns per-sleeve `{total_return, sharpe, max_drawdown, n_trades}` (reuse `PerformanceMetricsCalculator`; remember it returns `max_drawdown` ×100 already — do NOT ×100 again). `evaluate_graduation(perf)` returns a verdict object: passes only when `scanner_agent` has positive return AND sharpe ≥ spy sharpe AND maxDD < 20 AND total_return ≥ scanner_only. Construct series that pass and that fail each clause.
- [ ] **Impl:** feed the calculator a `[{Date(datetime), "Portfolio Value"}]` curve per sleeve (same shape the backtest used — pass a real datetime Date to avoid the `idxmin().strftime` crash). Graduation = the 4 AND-clauses from the spec.
- [ ] Green + commit: `feat(paper-trading): per-sleeve metrics + live A/B + graduation-bar verdict`.

### Task 7: Performance report

**Files:** Create `src/paper_trading/report.py`, `src/paper_trading/test_report.py`.

- [ ] **Test first:** `write_report(out_dir, perf, verdict, equity_series)` writes a markdown (and/or HTML) file containing each sleeve's metrics, the graduation verdict, and an embedded equity-curve PNG (reuse `charts/render.render_equity_curve_png` → b64). Assert the file exists + contains the sleeve names + the verdict string. Offline.
- [ ] **Impl:** small renderer; reuse the charts module for the equity-curve image. No LLM.
- [ ] Green + commit: `feat(paper-trading): performance report (metrics + equity curves + verdict)`.

### Task 8: AlpacaBroker (live paper) + CLI + scheduler glue + offline smoke

**Files:** Modify `src/paper_trading/broker.py` (fill `AlpacaBroker`); create `src/paper_trading/run.py`; wire a weekly + daily job into the existing scheduler service; create `src/paper_trading/test_smoke.py`.

- [ ] **Test first:** an offline smoke runs one full `run_week` + `mark_sleeve` + `compute_performance` + `write_report` for all 3 sleeves end-to-end against `FakeBroker` + injected scan/agent stubs + a scratch SQLite session, asserting positions/orders/marks/report all materialize. `AlpacaBroker` is import-guarded so the smoke never imports `alpaca`.
- [ ] **Impl:** `AlpacaBroker` wraps `alpaca-py` TradingClient (paper base URL, keys from `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`), lazy-imported inside `__init__`. `run.py`: `--once` (run this week for all sleeves), `--marks` (daily), `--report`; `load_dotenv()` at top (the backtest-CLI lesson). Register `paper_weekly_job` + `paper_daily_marks_job` in the scheduler. Pin `alpaca-py` in pyproject.
- [ ] Green + commit: `feat(paper-trading): AlpacaBroker live-paper impl + CLI + scheduler jobs + offline smoke`.

---

## Final step (after all tasks)

- [ ] Full offline suite green: `... -m pytest src/paper_trading/ -q`.
- [ ] Dispatch a final reviewer over the whole package.
- [ ] Append per-task lines to `progress.md`.
- [ ] Morning hand-off note: what was built, how to add the Alpaca paper key, how to start the weekly job, and the graduation bar.

## Self-review

- **Spec coverage:** 3 sleeves (T3), Alpaca paper + FakeBroker (T1/T8), weekly engine + hold/exit (T4), persistence + migration (T2), daily marks (T5), metrics + A/B + graduation (T6), report (T7), scheduler + CLI (T8). All spec sections covered.
- **Types consistent:** `BrokerClient` methods, `compute_targets`/`run_week`/`mark_sleeve`/`compute_performance`/`evaluate_graduation`/`write_report` signatures named consistently across tasks.
- **Offline:** every task tests against FakeBroker + injected stubs; no task needs network/LLM/real orders.
- **Known gotchas pre-flagged:** SQLite id-Integer variant (T2), `max_drawdown` ×100 (T6), datetime Date for metrics (T6), `load_dotenv` in CLI (T8), lazy alpaca import (T1/T8).
