# Paper-Trading Forward-Test Harness — Design

**Date:** 2026-06-08
**Status:** approved (user greenlit autonomous spec → plan → overnight build)

## Goal

A **zero-financial-risk, live paper-trading system** that runs the
scanner→agent→execute workflow against a broker **PAPER** account (Alpaca) as a
forward test — to prove or disprove, with **real, un-leakable future market
data**, whether the workflow actually makes money, **before any real capital is
risked**.

## Why (session context)

The in-session backtest (171 dates, nasdaq100, DeepSeek) showed the
scanner→agent workflow has **no statistically significant directional edge**
(agent ≈ coin-flip, all |Welch t| < 1.3), and that **shorts bleed in bull
markets** (long-only ≈ 3× better per-bet). The backtest is also vulnerable to
**LLM training-foreknowledge** for pre-2025 dates. A live paper forward-test
removes those doubts: future prices cannot be memorized or look-ahead-leaked.

This harness is the rigorous **instrument** that must validate any strategy
before real money — and the scientific gate for the *next* project (richer
signals: dark-pool / gamma institutional-flow tracking). Build the scale before
weighing things.

## Non-goals (v1)

- **NO real-money trading.** Paper only. Real money is a future, separately
  gated step that requires passing the graduation bar below.
- **NO React dashboard in v1.** v1 emits a generated performance **report**
  (reuse the HTML/markdown report infra). A frontend panel is a fast-follow.
- **NO intraday / HFT.** Weekly cadence, multi-day holds.
- **NO new signal sources** (dark-pool / gamma) — that is the next project;
  this harness exists to test it.

## Strategy under test (locked defaults)

- **Long-only** (drop shorts — the backtest showed they are the leak).
- **Weekly scan + 21-trading-day hold**, equal-weight, capped concurrent
  positions, fixed % of sleeve capital per name.
- **Three parallel sleeves**, each **$100k virtual**, identical cadence, for a
  **live A/B**:
  1. `scanner_agent` — scanner top-N → agent analysis → long the `buy` calls.
  2. `scanner_only` — scanner top-N → long all (equal weight), **no agent**.
  3. `spy_benchmark` — buy-and-hold SPY.

The three-sleeve design answers, with future data, the question the backtest
could only weakly address: *does the agent add value over the raw scanner
picks, and does either beat just holding the index?*

## Graduation bar (fixed upfront — do not move the goalposts)

Over **≥ 3 months / ≥ ~12 weekly cycles**, the `scanner_agent` sleeve must
**simultaneously**:

- Positive absolute return.
- Sharpe ≥ the `spy_benchmark` sleeve's Sharpe.
- Max drawdown < 20%.
- Total return ≥ the `scanner_only` sleeve (else the agent adds no value — just
  use the scanner picks).

Failing **any** → do NOT advance to real money. The test will have done its job.

## Architecture

New backend package: **`src/paper_trading/`**. All broker I/O sits behind an
interface so the engine is fully testable offline.

### Components / files

| File | Responsibility |
|---|---|
| `broker.py` | `BrokerClient` Protocol (`submit_market_order`, `get_positions`, `get_account`, `get_last_price`, `close_position`) + `AlpacaBroker` (live paper impl via `alpaca-py`) + `FakeBroker` (deterministic in-memory — offline tests + dry runs). |
| `models.py` (DB) | SQLAlchemy tables: `paper_sleeve`, `paper_position` (open/closed, entry/exit date+price+shares), `paper_order` (submitted/filled/rejected), `paper_equity_mark` (daily per-sleeve equity). Additive Alembic migration chaining from current head. SQLite. |
| `sleeves.py` | Sleeve registry + per-sleeve **target-position** logic: `scanner_agent` (run_scan → agent buys), `scanner_only` (run_scan → all picks), `spy_benchmark` (100% SPY). Pure given injected `run_scan_fn` / `agent_fn`. |
| `engine.py` | Weekly runner: per sleeve, compute target longs for this scan → **exit** positions aged ≥ `hold_days` → **enter** new targets (equal-weight, cash-aware) via `BrokerClient` → persist orders/positions. Idempotent per `(week_key, sleeve)`. |
| `marks.py` | Daily mark-to-market: last price per held name → per-sleeve equity → append to `paper_equity_mark`. |
| `performance.py` | Per-sleeve metrics (total return, Sharpe, maxDD, n_trades) via the backtest's `PerformanceMetricsCalculator`; the A/B comparison; graduation-bar evaluation → verdict object. |
| `report.py` | Render an HTML/markdown performance report: 3 equity curves + metrics table + graduation status. Reuse `charts/render.py` for the equity-curve PNG. |
| `run.py` | CLI entrypoint (`python -m src.paper_trading.run --once` manual trigger; `--marks` daily marks; `--report`). |
| scheduler glue | Register a **weekly** "scan+trade" job + a **daily** "mark" job in the existing scheduler service. |

### Data flow

```
weekly job ─► run_scan (reuse) ─► top-N
   ├─ scanner_agent: run_agents_only → keep action=="buy"
   ├─ scanner_only : keep all top-N
   └─ spy_benchmark: ["SPY"]
        ─► engine: exit aged positions + enter targets (equal-weight, cash-aware)
        ─► BrokerClient places paper orders ─► fills persisted
daily job ─► marks.py marks every sleeve ─► paper_equity_mark
on demand ─► performance.py + report.py ─► performance report + graduation verdict
```

### Reuse (do not rebuild)

- Scanner: `v2.scanner.runner.run_scan`.
- Agent: `v2.pipeline.orchestrator.run_agents_only` (long-only filter `action=="buy"`).
- Metrics: `src/backtesting/metrics.PerformanceMetricsCalculator` (note: it
  returns `max_drawdown` pre-multiplied ×100 — same gotcha the backtest report hit).
- Scheduler: the existing per-user scheduler service.
- Charts: `src/research/charts/render.render_equity_curve_png`.
- DB: existing SQLAlchemy + Alembic (**SQLite — do NOT switch to Postgres**).

### Error handling

- Broker calls best-effort + retried; a failed order is recorded `rejected`,
  never crashes the run.
- A sleeve's failure **isolates** (the other sleeves continue).
- The engine is **idempotent** per `(week_key, sleeve)` — a re-run loads the
  existing week's actions instead of double-trading.
- Market-closed / holiday: if today is not a trading day, the weekly job no-ops.

### Testing (ALL offline — no network, no LLM, no real orders)

- `FakeBroker` with deterministic fills drives engine tests: entry/exit/hold
  logic, equal-weight cash math, idempotency, P&L marks, performance metrics,
  graduation-bar evaluation. `run_scan_fn` / `agent_fn` are injected stubs.
- Each task is TDD: failing test → minimal impl → green → commit.

## Risks / open items

- **Alpaca paper key** is a user-supplied dependency (`ALPACA_API_KEY` /
  `ALPACA_SECRET_KEY` in `.env`). The **build + tests are fully offline**
  (FakeBroker); the key is only needed to start *live* paper trading. If the
  user prefers no broker account, `FakeBroker` + real market-data marks can run
  a pure-internal simulation, but Alpaca paper is the recommended path (realistic
  fills + the natural on-ramp to real trading).
- The forward-test takes **real calendar time (~3 months)** — by design; there
  is no overnight shortcut (that would just be another backtest).
- `alpaca-py` is a new dependency — pin it; keep all imports lazy so offline
  tests never require it.
- Marks depend on the existing data providers for last prices (reuse hybrid).
