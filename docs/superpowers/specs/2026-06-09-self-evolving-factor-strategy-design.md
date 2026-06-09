# Self-Evolving Factor-Strategy Engine — Design

**Date:** 2026-06-09
**Status:** approved (design greenlit; spec pending user review → writing-plans)

## Goal

Apply the Huatai/Karpathy **AutoResearch "self-evolving Skill"** methodology to our
own quant research: a disciplined, auditable loop in which an LLM agent iterates a
**deterministic factor strategy's CONFIG** under a fixed Skill protocol, with strict
**train/val/test sample isolation** and **version management**, so improvements are
explainable, attributable, and guarded against overfitting — never an unconstrained
parameter search.

The methodology's value is process discipline, NOT edge creation. The val → test →
paper-forward-test gauntlet is what guards against "validation improvement ≠ real
out-of-sample edge" (the paper's own caution, and this codebase's recurring theme).

## Decisions (from brainstorming)

- **Horizon:** medium-term (1-3 month, monthly rebalance). NOT short-term (our EOD +
  fundamental data isn't built for intraday; costs/noise dominate).
- **What evolves (this spec):** a NEW clean, deterministic **price-led factor strategy**
  + the reusable **self-evolution engine**. The scanner config is a *future plugin* to
  the same engine — out of scope here.
- **Factors/data:** price factors lead (momentum / low-vol / reversal — free, deep,
  clean) + a *shallow* value/quality tilt (yfinance annual fundamentals via our existing
  as-of machinery). Deep point-in-time fundamentals (paid: Sharadar / financial_datasets)
  are an explicit non-goal for v1.
- **Home:** Lab.

## Non-goals (v1)

- NO short-term / intraday.
- NO LLM in the per-stock decision path (the strategy is deterministic factors; the LLM
  only proposes CONFIG deltas — cheap, so hundreds of iterations are affordable).
- NO deep paid fundamentals; the value/quality tilt is coarse (annual, reporting-lagged).
- NO full React Lab panel in v1 — v1 ships the engine + CLI + a results report (HTML/md);
  a Lab panel to launch/watch/inspect is the immediate fast-follow.
- NO scanner-config plugin yet (same engine, later).

## Architecture — three layers (per the paper) + the auto-loop

New package **`v2/self_evolve/`** + a strategy directory **`strategy_skill/`**.

```
strategy_skill/
  SKILL.md            Strategy kernel (fixed investment logic) + iteration discipline
                      (one hypothesis/round, config-only, don't touch shared code) +
                      evaluation protocol (train/val/test permissions).
  skill_config.yaml   The ONLY thing the agent edits: factor weights, lookback windows,
                      top_n, holding count, max single-name weight, liquidity thresholds,
                      value/quality tilt strength, rebalance freq, cost bps.
  versions/v0.x.y/    Per iteration: config snapshot, holdings, scores, per-sample
                      metrics, the hypothesis, keep/rollback, attribution note.

v2/self_evolve/
  config.py           Load/validate skill_config.yaml; enforce the adjustable BOUNDARIES
                      (any value outside its declared range is rejected — the protocol).
  factors.py          Deterministic factor computation (as-of, no lookahead): momentum
                      (12-1), low-vol, short-term reversal, shallow value (E/P), shallow
                      quality (ROE). Pure numpy over price/fundamental bundles.
  strategy_gen.py     config -> per rebalance date, score + rank the universe, build the
                      top-N vol-inverse-weighted long-only portfolio -> holdings.
  backtest.py         holdings -> per-SAMPLE metrics (Sharpe, ann return, vol, maxDD,
                      turnover) via PerformanceMetricsCalculator. Splits on the fixed
                      train/val/test boundaries.
  samples.py          The fixed train/val/test time split (declared once, immutable).
  proposer.py         The LLM agent seam: reads SKILL.md + current config + val history,
                      returns ONE single-hypothesis config delta (within boundaries).
                      Injectable (stub for offline tests).
  loop.py             The evolution loop: propose -> apply -> gen+backtest(train+val) ->
                      keep if val improves under guardrails else rollback -> version.
  versioning.py       Write/read versions/v0.x.y/ + the optimization-path log.
  report.py           Render the run report (iteration path, per-version metrics, the
                      retained-path, test verdict) -> md + HTML (reuse charts).
  run.py              CLI: `python -m v2.self_evolve.run --iterations N --out ...`.
```

### Reuse (do not rebuild)
- **No-lookahead data:** `v2/scanner/eval/cached_asof_client.CachedAsOfClient` (price as-of
  + 60d fundamental availability lag) + `v2/workflow_backtest/bundles` for prefetch.
- **Metrics:** `src/backtesting/metrics.PerformanceMetricsCalculator` (max_drawdown is
  already ×100; pass a datetime Date — the known gotchas).
- **Fundamentals history:** `src/research/charts/fundamentals_fetch` (yfinance annual) +
  the as-of client for point-in-time lagging.
- **Proposer LLM:** DeepSeek via `src/llm/models.get_model` (cheap; config deltas only).
- **Final out-of-sample:** the paper-trading harness (`src/paper_trading/`) — graduate the
  best val-retained version to a new sleeve.

## The strategy kernel (fixed) + adjustable boundaries

**Kernel (cannot be violated by the loop):** long-only, medium-term, **price-led** composite
factor strategy on a liquid US universe (nasdaq100 / a liquid large-cap set). Rank by a
weighted composite of: momentum(12-1), low-volatility, short-term reversal, + a shallow
value tilt (E/P) and shallow quality tilt (ROE). Take top-N, vol-inverse weight, cap single
names, rebalance monthly, long-only, no market/position timing.

**Adjustable boundaries (in skill_config.yaml, each with a declared range):**
factor weights (sum-normalized), each factor's lookback window, top_n (e.g. 20-50), holding
count/buffer, max single-name weight (e.g. 3-8%), liquidity percentile thresholds,
value/quality tilt strength, rebalance frequency, cost bps. The loop changes ONE of these
per round.

## Sample isolation (load-bearing) + no-lookahead

- **Fixed time split, declared once in `samples.py`:** train (e.g. 2016-2021), validation
  (2022-2023), test (2024-present). Immutable across the whole run.
- The loop reads **train (propose/screen) + val (keep/rollback decision)** ONLY. **Test is
  never read inside the loop** — only the final human review (and the paper forward-test).
- **No-lookahead enforced by `CachedAsOfClient`:** at each rebalance date D, factors use only
  prices ≤ D and fundamentals with report-period ≤ D-60d. Forward returns (the outcome) use
  prices after D — correct, not lookahead.

## The auto-iteration loop

1. `proposer.propose(skill_md, current_config, val_history)` → ONE config delta + a one-line
   hypothesis (e.g. "raise momentum weight 0.30→0.40 — recent regime favors trend"). The
   LLM is constrained to the declared adjustable boundaries; an out-of-range delta is rejected.
2. Apply the delta → `strategy_gen` + `backtest` on **train + val** (deterministic, no LLM).
3. **Keep iff** val Sharpe improves AND guardrails hold (turnover not blown out, vol/maxDD not
   worse beyond a tolerance — i.e. the gain isn't just more risk). Else **rollback**.
4. Write a version (config, holdings, scores, per-sample metrics, hypothesis, keep/rollback,
   attribution). Append to the optimization-path log.
5. Repeat for N iterations (budget-bounded). One hypothesis per round → clean attribution.

## The final judge (our addition beyond the paper)

- **Test set:** final human review only — never in the loop.
- **Paper forward-test graduation:** the best val-retained version is wired as a new
  `src/paper_trading/` sleeve (e.g. `factor_evolved`), so it accrues a real, un-leakable
  forward-test verdict alongside the existing sleeves. This is the rigor the paper lacked
  (they had only a static test set).

## Lab integration (v1 thin, panel fast-follow)

- v1: the CLI + the run report (HTML/md: the val-Sharpe iteration path, per-version metrics
  table, the retained path, the test verdict).
- Fast-follow: a Lab panel/tab to launch a run, watch the iteration path live, inspect
  versions, and see the test/forward-test verdict.

## Error handling

- A proposer failure / out-of-range delta → skip that round (log), never crash the loop.
- A backtest failure for a config → record the version as "errored", rollback, continue.
- The loop is resumable (versions persisted); re-running continues from the last version.

## Testing (offline, deterministic)

- `factors.py` / `strategy_gen.py` / `backtest.py`: unit tests on small synthetic or cached
  price/fundamental bundles — deterministic, no network/LLM.
- `loop.py`: tested with a STUB proposer (returns canned deltas) + a tiny universe → asserts
  keep/rollback logic, versioning, sample isolation (test never read), guardrails.
- `samples.py`: the split is fixed + asserted.
- The live LLM proposer is exercised only via the CLI (not unit tests).

## Risks / honest caveats (in the design on purpose)

- **Shallow fundamentals** → value/quality tilt is coarse (annual, lagged); price factors
  carry the weight. Deep fundamental factors need paid point-in-time data (out of scope).
- **Self-evolution optimizes within the config space; it does not create edge.** Our prior
  backtests show weak/unproven edge. The val→test→forward-test gauntlet is the guard; a
  config that wins on val may still fail test/forward — and that's a *valid, money-saving*
  result.
- **Overfitting risk is real even with sample isolation** (val can be gamed over many
  rounds). Mitigations: single-hypothesis rounds, guardrails on "keep", a held-out test
  untouched by the loop, and the live forward-test as the final arbiter.
- The LLM proposer can suggest nonsense; the boundary validation + the deterministic
  keep/rollback (not the LLM) decide retention.
