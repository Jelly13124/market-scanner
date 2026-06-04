# Agent-Workflow Backtest — Design

**Date:** 2026-06-04
**Status:** Approved (ready for implementation plan)
**Scope:** New backend package `v2/workflow_backtest/`. Reuses existing pipeline / agents / as-of client / regimes. No frontend.

---

## Problem & goal

Does the product's core workflow — **daily Scanner picks → multi-agent analysis → execute the PM's decisions** — actually add value? Specifically:

1. **(A/B, the rigorous claim)** Are the Scanner's daily top-N tickers *more valuable to the agents* than random tickers from the same universe? I.e. does feeding Scanner-picked tickers through the same agents beat feeding random tickers?
2. **(Absolute, best-effort)** Run the full workflow as a portfolio — after costs, does it make money? Validated across **bull / bear / sideways** regimes.

Hard constraint from the user: **no lookahead / no future functions.** This has two distinct layers (see below) — one fixable in code, one fundamental to LLMs.

## The two trustworthy claims (and why)

Backtesting an LLM workflow has an unavoidable bias: **the LLM's parametric memory already knows the future** (GPT-4.1 / DeepSeek training cutoffs ~2024, so asking them to "analyze NVDA as of 2023-06" leaks what happened after). Plus residual code-level data leaks (below). We get trustworthy results two ways:

- **A/B is robust to ALL common-mode bias.** The Scanner-arm and Random-arm run the *same agents* on the *same as-of data the same way*; any bias (LLM foreknowledge, residual data leaks) hits **both arms equally** and **cancels in the delta**. So "does the Scanner-arm beat the Random-arm?" is rigorous on **every** regime, including 2022/2023-24. This matches the repo's existing scanner-eval philosophy (A/B vs a seeded RANDOM baseline).
- **Absolute is trustworthy only on the post-cutoff slice.** On dates **after the model's training cutoff** (~2025-01 → today 2026-06) the LLM has no parametric foreknowledge, so the **absolute** equity curve (after costs) is meaningful. Pre-cutoff regimes (2022 bear, 2023-24 bull) report absolute only as caveated colour.

| | bear_2022 / bull_2023-24 | 2025+ post-cutoff |
|---|---|---|
| **A/B delta** (scanner vs random) | ✅ trustworthy | ✅ trustworthy |
| **Absolute** (real money after costs) | ⚠️ LLM-biased, colour only | ✅ trustworthy |

## No-lookahead: the three layers

1. **Code-level (clampable) — enforced.** Inject `v2/scanner/eval/cached_asof_client.py:CachedAsOfClient` in place of the agent path's hybrid singleton and `set_asof(scan_date)` per date. This hard-clamps prices / news / insider / analyst / earnings-history / financial-metrics to `≤ scan_date` (with the harness's 60-day fundamental-availability lag). The default hybrid provider is **NOT** safe (Finnhub returns current-snapshot fundamentals + earnings keyed off `today`) — replacing the singleton is mandatory.
2. **Code-level (residual leaks) — documented, A/B-cancelled.** `search_line_items` (yfinance latest statements), `get_company_facts` / `get_market_cap` (latest snapshot) are NOT historically reconstructable. They leak in BOTH arms equally → A/B unaffected; for the absolute slice they're a documented caveat (slow-moving descriptive data, minor).
3. **LLM-level — handled by the post-cutoff slice** (above). Not fixable in code.

Survivorship bias: universe = current snapshot (no point-in-time membership), same as the existing scanner-eval. Accepted + caveated.

## Architecture

A new package `v2/workflow_backtest/` orchestrates existing pieces. Data flow:

```
pick weekly scan-dates across regime windows (regimes.py) + the post-cutoff window
for each scan_date (processed in a controlled pool):
  set_asof(scan_date) on an injected CachedAsOfClient (agent data path → as-of-safe)
  ├─ Scanner arm:  run_scan(end_date=scan_date) → top_n tickers + scanner_context
  └─ Random arm:   seeded random top_n tickers from the same universe, empty context
  for each arm: run the agents (run_hedge_fund / run_agents_only) on its tickers
                → collect the PM's decisions (action, ticker, conviction)
  record: per (scan_date, arm, ticker) → PM decision + forward 21/42/63d returns
          + benchmark(SPY) alpha   [forward returns use the UNCLAMPED full series:
                                     the decision is clamped, the OUTCOME is not]
→ Deliverable 1 (A/B attribution): per regime, mean forward-return of PM BUYs
   scanner-arm vs random-arm, with a significance test.
→ Deliverable 2 (absolute portfolio): equal-weight the PM BUYs each week, hold H
   days, weekly rebalance, commission+slippage → equity curve + Sharpe/maxDD/win;
   reported per regime; the 2025+ slice is the trustworthy "does it make money".
```

**What the A/B isolates:** the Scanner arm runs the product *as-built* (scanner tickers + `scanner_context` injected into the agent prompt); the Random arm gets random tickers + empty context. So the delta measures the **whole Scanner contribution** (ticker selection *and* the signals it injects) vs random — not pure ticker-selection. A pure-selection ablation (scanner tickers, empty context) is a documented v2 option.

## Components (`v2/workflow_backtest/`)

- `asof_agents.py` — wires the agent data path to as-of safety: a context manager that swaps `src.tools.api._v2_client_cache` for a `CachedAsOfClient`, calls `set_asof(scan_date)`, and restores on exit. One job: "run the agents for `scan_date` with no clampable lookahead."
- `arms.py` — produces the two arms' ticker lists for a scan_date: Scanner arm via `run_scan(end_date=scan_date, use_quant_signals=True)` → top_n; Random arm via a seeded RNG over the same universe (same count, reproducible).
- `decisions.py` — runs the agents for an arm's tickers at a scan_date (reuse `run_pipeline` / `run_agents_only` from `v2/pipeline/orchestrator.py`) and extracts the PM decisions (action ∈ buy/sell/hold/short/cover, ticker, quantity/conviction).
- `attribution.py` — joins each decision with forward 21/42/63d returns + SPY alpha (reuse `v2/backtesting/forward_returns.py:compute_forward_returns`); the A/B significance test (Welch t on scanner-BUY vs random-BUY forward returns, per regime + per horizon).
- `portfolio.py` — the equal-weight weekly-rebalance simulator (hold H days, costs); reuse `src/backtesting/metrics.py:PerformanceMetricsCalculator` (sharpe/sortino/maxDD) where possible. One curve per arm + SPY buy-hold.
- `regime_windows.py` — reuse `v2/scanner/eval/regimes.py` windows (bear_2022, bull_2023-24, choppy_2025) + add a `post_cutoff_2025_26` window (2025-01-01 → run date), classify each via `classify_regime`.
- `run_workflow_backtest.py` — the runner: builds scan-dates, drives the pool (parallel within a scan-date; scan-dates pooled with per-date as-of clients), persists incrementally (resumable), writes the report. CLI entry `python -m v2.workflow_backtest.run_workflow_backtest`.
- `report.py` — writes `findings_agent_backtest.md` + CSVs (`workflow_backtest/decisions.csv`, `ab_by_regime.csv`, `equity_*.csv`) + equity-curve PNGs.

## Reuse (unchanged)
`v2/pipeline/orchestrator.py` (`run_pipeline`, `run_agents_only`), `src/main.py` (`run_hedge_fund`), `v2/scanner/runner.py` (`run_scan`), `v2/scanner/eval/cached_asof_client.py` + `regimes.py`, `v2/backtesting/forward_returns.py`, `src/backtesting/metrics.py`, `v2/scanner/universes/loader.py`.

## Parallelism, cost, overnight, resumability
- **Parallel agents** (user's hard requirement): within a scan-date the agent workflow + the 2 arms × top_n tickers run concurrently. Scan-dates are pooled with a bounded worker count; each worker uses its own as-of client instance (or scan-dates run sequentially with `set_asof` if the global singleton can't be made per-worker — the plan decides based on a quick thread-safety check). Either way the agent calls fan out.
- **Scale (Standard, confirmed):** universe `nasdaq100`, weekly scan-dates (≈ every 5 trading days via `spread_days`), `top_n=5`, full agent pipeline, **DeepSeek** (`model_name`/`model_provider` set to the user's DeepSeek). Est. ≈ (78 dates × 2 arms × 5 tickers × agents) LLM calls ≈ low tens of dollars overnight.
- **Resumable:** persist per-(scan_date, arm) results to disk as they land; on restart, skip completed cells. One failing cell never aborts the run (allSettled semantics).
- **No money spent unattended in this build:** the BUILD delivers the framework + **offline unit tests with MOCKED agents + a MOCKED/cached client** (deterministic, $0). The real (paid) full run is a **separate launch step** the user kicks off after reviewing — or a tiny 1-2-date smoke the agent does to prove the pipe end-to-end.

## Deliverables
- The `v2/workflow_backtest/` package + offline tests, all green.
- `findings_agent_backtest.md`: per-regime A/B delta (scanner-BUY vs random-BUY forward return) with significance; the 2025+ absolute equity curve + Sharpe/maxDD/win after costs; CSVs + charts. (Populated by the user's launched run; the build ships the framework + a smoke-sized example.)

## Out of scope (v1)
- Lab technical-indicator expansion + scanner tuning — separate parallel track, not this spec.
- PM *exit* signals driving the portfolio (v1 holds H days / weekly rebalance; exits = v2).
- Point-in-time universe membership / fundamentals store (accept survivorship + residual leaks, documented).
- The full paid backtest run itself (framework only; run is a gated launch step).

## Risks
1. **Agent data path thread-safety** for cross-date parallelism (global singleton) — mitigate by sequential-dates-with-`set_asof` if needed; agents still parallelize within a date.
2. **Residual code leaks** (line_items/facts/market_cap) — A/B-cancelled; caveated for absolute.
3. **Agent reliability/cost** at scale — bounded by sampling + DeepSeek + resumability + allSettled.
4. **`run_agents_only` / `run_pipeline` return shape** — confirm the PM-decision extraction path during implementation (read the orchestrator's `PipelineResult`).

## Testing
- Offline unit tests (no network, no LLM): mock `run_hedge_fund`/`run_pipeline` to return canned PM decisions; assert arms, attribution math, the A/B t-test, portfolio accounting (costs, equity), regime slicing, and the as-of context manager (swaps + restores the singleton, calls `set_asof`). Run via `C:\Users\Jerry\anaconda3\python.exe -m pytest`.
- A tiny **smoke** (1-2 scan-dates, top_n=2, mocked or 1 real cheap call) proving the end-to-end pipe before any large run.
