# Self-Evolving Factor-Strategy Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Each task = failing test → minimal impl → green → commit. Steps use `- [ ]`.

**Goal:** A disciplined self-evolution loop — an LLM proposes single-hypothesis CONFIG deltas to a deterministic price-led factor strategy, evaluated under strict train/val/test sample isolation, versioned, with the best val-retained version graduating to the paper forward-test.

**Architecture:** New `v2/self_evolve/` package + a `strategy_skill/` protocol dir. Deterministic factor gen + backtest (no LLM, cheap, no-lookahead via CachedAsOfClient); the LLM only proposes config deltas; the keep/rollback decision is deterministic (val Sharpe + guardrails). Reuses CachedAsOfClient, PerformanceMetricsCalculator, fundamentals_fetch, the data factory, DeepSeek, and the paper-trading harness.

**Tech Stack:** Python (anaconda `C:\Users\Jerry\anaconda3\python.exe`), numpy, PyYAML, pytest (offline), DeepSeek (live proposer only).

**Constraints (every task):** tests OFFLINE — no network, no LLM (stub the proposer; synthetic/cached price+fundamental bundles). Run tests `PYTHONIOENCODING=utf-8 PYTHONPATH=C:/Users/Jerry/Desktop/ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest <path> -q`. Conventional commit per task, **NO Co-Authored-By**, never `--no-verify`, explicit `git add <paths>` (never `-A`, never stage `.claude/settings.local.json`). Branch main. black hook — run black on new .py. **Stay on SQLite.** No-lookahead is load-bearing: factors at date D use only data ≤ D (prices ≤ D, fundamentals report-period ≤ D−60d).

---

### Task 1: Package skeleton + Skill protocol + config loader/validator

**Files:** Create `v2/self_evolve/__init__.py`, `v2/self_evolve/config.py`, `strategy_skill/SKILL.md`, `strategy_skill/skill_config.yaml`, `v2/self_evolve/test_config.py`.

- [ ] **Test first:** `load_config(path)` parses the yaml into a `StrategyConfig`; `validate(config)` accepts an in-bounds config and REJECTS (raises `ConfigError`) any field outside its declared range (e.g. a factor weight <0 or >1, top_n outside [20,50], max_weight outside [0.03,0.08]); factor weights are sum-normalized to 1.0; `apply_delta(config, {"factor_weights.momentum": 0.4})` returns a new validated config (out-of-range delta → ConfigError).
- [ ] **Impl:** `StrategyConfig` dataclass mirroring `skill_config.yaml`: `factor_weights` (momentum/low_vol/reversal/value/quality, each [0,1], sum-normalized), lookback windows, `top_n` [20,50], `holding_buffer`, `max_weight` [0.03,0.08], `liquidity_pct` thresholds, `tilt_strength`, `rebalance` ("monthly"), `cost_bps`. `ADJUSTABLE` dict declares each path's range. `SKILL.md` documents the fixed kernel + the one-hypothesis-per-round + config-only discipline. `skill_config.yaml` is the v0 baseline.
- [ ] Green + commit: `feat(self-evolve): Skill protocol + bounded config loader/validator`.

### Task 2: Fixed train/val/test sample split

**Files:** Create `v2/self_evolve/samples.py`, `v2/self_evolve/test_samples.py`.

- [ ] **Test first:** `SAMPLES` declares immutable train/val/test date windows; `sample_of(date)` returns "train"/"val"/"test"/None; a date in the test window classifies "test"; windows don't overlap; `rebalance_dates(sample, trading_days, freq="monthly")` returns the month-end (or month-start) trading days within that sample's window.
- [ ] **Impl:** `SAMPLES = {"train": ("2016-01-01","2021-12-31"), "val": ("2022-01-01","2023-12-31"), "test": ("2024-01-01","2030-12-31")}` (fixed). `sample_of` + `rebalance_dates`. Pure, deterministic.
- [ ] Green + commit: `feat(self-evolve): immutable train/val/test sample split + rebalance dates`.

### Task 3: Deterministic factors (no-lookahead)

**Files:** Create `v2/self_evolve/factors.py`, `v2/self_evolve/test_factors.py`.

- [ ] **Test first:** on a small SYNTHETIC bundle (constructed price series + annual fundamentals), `compute_factors(bundles, asof, config)` returns a `{ticker: {momentum, low_vol, reversal, value, quality}}` dict where: momentum(12-1) = return from asof-252d to asof-21d; low_vol = −(trailing 60d vol); reversal = −(trailing 21d return); value = E/P from the latest fundamental with report-period ≤ asof−60d (None if none); quality = ROE same lag. A ticker with insufficient history → omitted (no crash). NO bar after asof is read (assert via a bundle with a future spike that must NOT affect the value).
- [ ] **Impl:** pure numpy over the bundle's `prices` (as-of clamped) + fundamentals (report-period ≤ asof−60d, mirroring `CachedAsOfClient`'s FUNDAMENTAL_AVAILABILITY_LAG_DAYS). Each factor a small helper. Never raises.
- [ ] Green + commit: `feat(self-evolve): no-lookahead factor computation (momentum/low-vol/reversal/value/quality)`.

### Task 4: Strategy generation (config → holdings)

**Files:** Create `v2/self_evolve/strategy_gen.py`, `v2/self_evolve/test_strategy_gen.py`.

- [ ] **Test first:** `generate_holdings(bundles, asof, config) -> {ticker: weight}`: applies the liquidity filter, z-scores each factor cross-sectionally, composites with `config.factor_weights`, ranks, takes `top_n`, weights inverse-to-vol, caps each at `max_weight`, renormalizes to sum 1.0. Assert: only top-N held, weights sum≈1, none exceeds max_weight, higher composite → selected. Empty/degenerate universe → `{}` (no crash).
- [ ] **Impl:** reuse `compute_factors`; cross-sectional z-score (guard zero-std per the std-floor invariant); composite; rank; vol-inverse weight + cap + renormalize.
- [ ] Green + commit: `feat(self-evolve): config-driven long-only top-N vol-weighted portfolio generation`.

### Task 5: Backtest per sample

**Files:** Create `v2/self_evolve/backtest.py`, `v2/self_evolve/test_backtest.py`.

- [ ] **Test first:** `backtest(bundles, config, sample) -> {sharpe, ann_return, ann_vol, max_drawdown, turnover, n_rebalances}`: for each rebalance date in the sample, `generate_holdings`, hold to next rebalance, mark with forward prices, build the equity curve, compute metrics via `PerformanceMetricsCalculator` (pass datetime Date; max_drawdown already ×100 — don't re-multiply). turnover = mean Σ|w_t − w_{t−1}|. Construct a rising synthetic market → positive return; a curve with a dip → negative maxDD as a percent (not ×100 twice).
- [ ] **Impl:** weekly/monthly hold loop on the sample's rebalance_dates; equity curve `[{Date: datetime, "Portfolio Value": v}]`; reuse the metrics calc (the workflow_backtest/portfolio gotchas).
- [ ] Green + commit: `feat(self-evolve): per-sample factor backtest (Sharpe/return/vol/maxDD/turnover)`.

### Task 6: Versioning + proposer seam

**Files:** Create `v2/self_evolve/versioning.py`, `v2/self_evolve/proposer.py`, `v2/self_evolve/test_versioning.py`.

- [ ] **Test first:** `write_version(dir, v_id, {config, train_metrics, val_metrics, hypothesis, kept, attribution})` then `read_version` round-trips; `append_path_log` + `read_path_log` accumulate the optimization path. `propose(skill_md, config, val_history, *, llm_fn=None)` with a STUB `llm_fn` returning a canned delta JSON → returns a validated single-field delta; an out-of-range/garbage delta → returns None (logged), never raises.
- [ ] **Impl:** versioning writes JSON under `strategy_skill/versions/<v_id>/`. `proposer.propose` builds the prompt (kernel + current config + val history + the one-hypothesis instruction), calls `llm_fn` (default lazily binds DeepSeek `get_model`), parses+validates the delta against `config.ADJUSTABLE`. Injectable seam.
- [ ] Green + commit: `feat(self-evolve): version store + optimization-path log + LLM config-delta proposer seam`.

### Task 7: The evolution loop (keep/rollback under sample isolation)

**Files:** Create `v2/self_evolve/loop.py`, `v2/self_evolve/test_loop.py`.

- [ ] **Test first:** `evolve(bundles, base_config, *, iterations, propose_fn) -> path`: each round propose a delta (stub `propose_fn`), apply, backtest TRAIN+VAL only, **keep iff val Sharpe improves AND guardrails (turnover ≤ baseline×1.5, val maxDD not worse by >5pp)**, else rollback; write a version each round. Assert: a val-improving delta is kept + becomes the new base; a val-worsening or guardrail-violating delta is rolled back; **TEST sample is NEVER backtested inside the loop** (spy on backtest calls → assert no call with sample="test"); resumable (re-running continues from the last version).
- [ ] **Impl:** the loop over `iterations`; deterministic keep/rollback (NOT the LLM); guardrails; versioning each round; resumability via the version store.
- [ ] Green + commit: `feat(self-evolve): evolution loop — deterministic keep/rollback, guardrails, test untouched`.

### Task 8: Report + CLI + offline smoke

**Files:** Create `v2/self_evolve/report.py`, `v2/self_evolve/run.py`, `v2/self_evolve/test_smoke.py`.

- [ ] **Test first:** OFFLINE end-to-end: synthetic bundles + a STUB proposer → `evolve` for a few iterations → `write_report(out_dir, path)` writes md+HTML containing the val-Sharpe iteration path, a per-version metrics table, the retained path, and the **test verdict** (test backtest run ONCE here, post-loop, for the final number). Assert files exist + contain the version ids + a test-Sharpe. The smoke never imports the LLM (stub proposer).
- [ ] **Impl:** `report.py` renders the run (reuse `charts/render` for an iteration-path PNG). `run.py`: `load_dotenv()`, build bundles (CachedAsOfClient/prefetch), run `evolve` live (DeepSeek proposer), then the one-time test backtest + report. CLI `--iterations N --universe --out-dir`.
- [ ] Green + commit: `feat(self-evolve): run report (iteration path + test verdict) + CLI + offline smoke`.

### Task 9: Graduate best version to a paper-trading sleeve

**Files:** Modify `src/paper_trading/sleeves.py` (+ `run.py`); create `v2/self_evolve/graduate.py`; tests.

- [ ] **Test first:** `compute_targets("factor_evolved", scan_date, *, ...)` reads the retained-best `skill_config.yaml` version, runs `generate_holdings` as-of `scan_date`, returns the target tickers (long-only). A `factor_evolved` sleeve in `SLEEVE_NAMES`; the paper engine enters those targets. Offline (synthetic bundles + a fixed best-config fixture).
- [ ] **Impl:** `graduate.load_best_config()` reads the top val-retained version; `sleeves.compute_targets` gains a `factor_evolved` branch calling `generate_holdings`. The paper forward-test now A/Bs the evolved factor strategy against the existing sleeves with real future data.
- [ ] Green + commit: `feat(self-evolve): graduate best version to a paper-trading factor_evolved sleeve (live forward-test)`.

---

## Final step (after all tasks)
- [ ] Full offline suite green: `... -m pytest v2/self_evolve/ -q`.
- [ ] Final reviewer over the whole package (esp. the no-lookahead invariant in factors/backtest + the test-never-read-in-loop invariant).
- [ ] Append per-task lines to progress.md.
- [ ] Hand-off note: how to run a live evolution (`python -m v2.self_evolve.run`), where versions land, the graduation step, and the honest caveat (val win ≠ proven edge; forward-test decides).

## Self-review
- **Spec coverage:** protocol+config (T1), sample isolation (T2,T7), no-lookahead factors (T3), gen (T4), backtest (T5), versioning+proposer (T6), loop+keep/rollback (T7), report+CLI (T8), paper graduation (T9). All spec sections covered.
- **Type consistency:** `StrategyConfig`, `compute_factors`, `generate_holdings`, `backtest`, `propose`, `evolve`, `compute_targets("factor_evolved")` named consistently across tasks.
- **Offline:** every task tests on synthetic/cached bundles + stub proposer; no network/LLM.
- **Load-bearing invariants pre-flagged:** no-lookahead (T3 future-spike test; T5 forward-return-is-outcome), test-never-read-in-loop (T7 spy assertion), std-floor on z-scores (T4), metrics gotchas datetime-Date/×100 (T5).
