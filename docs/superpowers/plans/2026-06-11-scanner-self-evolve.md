# Scanner Self-Evolve (detector thresholds) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. Spec: `docs/superpowers/specs/2026-06-11-scanner-self-evolve-design.md`.

**Goal:** Auto-tune the scanner's event-detector thresholds (+ severity multipliers + top_n) with the existing `v2/self_evolve/` engine, under sample isolation + an A/B-vs-random fitness, with `quant_weight` fixed at 0 (the fundamental signals are proven to hurt). 

**Architecture:** A new `v2/scanner/evolve/` package that REUSES `v2/self_evolve/`'s `proposer` / `versioning` / `loop.evolve` (keep/rollback + guardrails + test-never-read) — swapping only `backtest_fn` for a `scanner_fitness` adapter that replays the scanner over a regime window (no-lookahead `CachedAsOfClient`) and scores the fired/Top-N set vs a random baseline (`v2/scanner/eval/detector_ab.evaluate_detector`). Bundles are prefetched ONCE per run and reused across iterations.

**Tech Stack:** Python (anaconda interpreter), pytest, `v2/self_evolve/` engine, `v2/scanner/` (detectors, runner, eval), DeepSeek-via-SiliconFlow proposer.

**Global constraints (every task):**
- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest <path> -q` — OFFLINE (synthetic/cached bundles, stub proposer, no network/LLM).
- Commit per task; conventional message; **NO Co-Authored-By**; never `--no-verify`; explicit `git add <paths>`; never stage `.claude/settings.local.json`. `black` on touched `.py`. Branch `main`.

**Load-bearing invariants (hold throughout):**
1. **NO-LOOKAHEAD** — the scanner replay reads only data ≤ asof (the eval's `CachedAsOfClient`, 60d fundamental lag). Forward returns (the fitness outcome) use post-asof prices only. The loop reads **train+val only; test never replayed in the loop** (re-assert with a sample-recorder test).
2. **`quant_weight = 0` is a FIXED kernel constraint** — it is NOT in `SCANNER_ADJUSTABLE`; the proposer can never re-enable the known-bad fundamental signals.
3. **Signals/detectors NEVER raise** (the scanner invariant) — the fitness wraps per-ticker replay so one bad ticker can't sink a config's score.
4. **Std/zero floors** on any normalization in the fitness.

PRE-READ (the templates to mirror/reuse): `v2/self_evolve/config.py` (config + ADJUSTABLE + apply_delta pattern), `v2/self_evolve/loop.py` (`evolve(bundles, base_config, *, iterations, base_dir, propose_fn, backtest_fn)`), `v2/self_evolve/proposer.py`, `v2/self_evolve/versioning.py`; `v2/scanner/eval/run_eval.py` (Phase 3 = the regime replay + quant A/B — the fitness blueprint), `v2/scanner/eval/detector_ab.py` (`forward_return`, `evaluate_detector` = the A/B-vs-random metric), `v2/scanner/eval/cached_asof_client.py`, `v2/scanner/eval/regimes.py` (REGIME windows), `v2/scanner/runner.py` (`run_scan(tickers, end_date, detectors=…, …)`), `v2/scanner/detectors/*.py` (constructor params = the thresholds), `v2/scanner/models.py` (`ScannerWeights`, `ScannerConfig`).

---

## Phase 1 — scanner config protocol

### Task 1: `ScannerEvolveConfig` + `SCANNER_ADJUSTABLE`

**Files:** Create `v2/scanner/evolve/__init__.py`, `v2/scanner/evolve/config.py`, `v2/scanner/evolve/scanner_skill_config.yaml`, `v2/scanner/evolve/test_config.py`.

- [ ] **Step 1: failing tests** — assert `load_config` reads the yaml; `SCANNER_ADJUSTABLE` maps dotted paths to (min,max) for the detector thresholds (`detectors.high_breakout.window` (5,60), `detectors.high_breakout.lookback_days` (60,400), `detectors.ma_cross.fast` (10,100), `detectors.ma_cross.slow` (100,300), `detectors.gap.threshold` …, `detectors.rsi_divergence.window` …) + `severity_mult.<detector>` (0.5,2.0) + `top_n` (10,50); `apply_delta` rejects an out-of-range value and rejects `quant_weight` (NOT adjustable) with `ConfigError`; `validate` passes the baseline. READ each detector's `__init__` to use the REAL param names.
- [ ] **Step 2-4: implement** — mirror `v2/self_evolve/config.py`: a `ScannerEvolveConfig` dataclass (`detectors: dict[str, dict]`, `severity_mult: dict[str, float]`, `top_n: int`, fixed `event_weight=1.0`/`quant_weight=0.0`), `SCANNER_ADJUSTABLE`, `load_config`/`validate`/`apply_delta`/`ConfigError`. Baseline yaml = the current default detector params (read them off the detector constructors). Run → green.
- [ ] **Step 5: commit** `feat(scanner-evolve): bounded scanner config protocol (detector thresholds; quant_weight fixed 0)`.

---

## Phase 2 — the fitness adapter (the crux)

### Task 2: build detectors from a config + replay one regime

**Files:** Create `v2/scanner/evolve/fitness.py`, `v2/scanner/evolve/test_fitness.py`.

- [ ] **Step 1: failing test** — `_detectors_from_config(config)` returns detector instances constructed with the config's thresholds (e.g. a `HighBreakoutDetector` whose `_window` == `config.detectors["high_breakout"]["window"]`). Offline (no run).
- [ ] **Step 2-4: implement** `_detectors_from_config` (map each `config.detectors[name]` → the detector class constructor kwargs; only include detectors in the enabled set). Run → green.
- [ ] **Step 5: commit** `feat(scanner-evolve): construct detectors from an evolve config`.

### Task 3: `scanner_fitness(bundles, config, sample)`

**Files:** Modify `v2/scanner/evolve/fitness.py`; extend `test_fitness.py`.

- [ ] **Step 1: failing test** — on a small SYNTHETIC bundle set + a `sample` whose regime window is covered, `scanner_fitness(bundles, config, "val")` returns a dict `{fitness, diff, t_stat, n_fired, alpha_5d}`; a config whose threshold makes nothing fire → `n_fired==0` and a graceful low/zero fitness (never raises); changing a threshold changes the fired set + the diff.
- [ ] **Step 2-4: implement** — adapt `run_eval.py` Phase 3: for each as-of rebalance date in the sample's regime window, set the `CachedAsOfClient` to that date, run the scanner (`run_scan` with `detectors=_detectors_from_config(config)` + the config's `top_n`/`severity_mult` via a `ScannerConfig`/`ScannerWeights`), collect the Top-N fired tickers, compute their `forward_return` (5d) from the post-asof series, accumulate `fire_returns`; build a same-universe RANDOM `baseline_returns` (seeded RNG for determinism); `evaluate_detector(fire_returns, baseline_returns, horizon=5)` → `diff`/`t_stat`. `fitness = diff` (primary). Also compute `alpha_5d` vs SPY (secondary). Per-ticker replay wrapped so one bad ticker → skipped, never raises. Run → green.
- [ ] **Step 5: commit** `feat(scanner-evolve): scanner_fitness — A/B-vs-random over a regime (no-lookahead)`.

### Task 4: prefetch-once bundle cache

**Files:** Modify `v2/scanner/evolve/fitness.py` (or a `bundles.py`); extend tests.

- [ ] **Step 1: failing test** — a spy/counter proves the per-ticker price series is fetched/parsed ONCE per (ticker) across multiple `scanner_fitness` calls with the same bundles (not re-fetched per iteration); a threshold-only delta reuses the cached series.
- [ ] **Step 2-4: implement** — bundles (prefetched price/fundamental series per ticker over the full train+val+test span) are built once and passed to `scanner_fitness`; the `CachedAsOfClient` wraps the in-memory bundle (no network in the loop). Mirror the factor engine's immutable-bundle reuse. Run → green.
- [ ] **Step 5: commit** `feat(scanner-evolve): prefetch bundles once, reuse across iterations`.

---

## Phase 3 — samples + loop

### Task 5: sample isolation (regimes)

**Files:** Create `v2/scanner/evolve/samples.py` + test.

- [ ] **Step 1: failing test** — `SAMPLES = {"train": [bear_2022, bull_2023_24], "val": [choppy_2025], "test": [<held-out window>]}` (immutable); `window_of(sample)` returns the (start,end) date span(s); `sample_of(date)` classifies. The test window is a later, distinct span (e.g. 2025-09-01..2026-06-01) that does NOT overlap train/val.
- [ ] **Step 2-5: implement + commit** `feat(scanner-evolve): immutable regime sample isolation (train/val/test)`.

### Task 6: `evolve` wiring + run CLI

**Files:** Create `v2/scanner/evolve/run.py` + test.

- [ ] **Step 1: failing test** — `evolve_scanner(bundles, base_config, *, iterations, base_dir, propose_fn=None)` calls `v2.self_evolve.loop.evolve` with `backtest_fn = lambda b,c,s: scanner_fitness(b,c,s)` and a scanner proposer (reuse `v2.self_evolve.proposer.propose` with a scanner `skill_md` describing the kernel + SCANNER_ADJUSTABLE). A stub proposer (weight/threshold deltas) + a stub/real fitness over synthetic bundles → keep/rollback works AND **`"test"` is never passed to scanner_fitness in the loop** (sample-recorder assertion). Resumable.
- [ ] **Step 2-4: implement** — thin wrapper over `loop.evolve`; the proposer gets the scanner skill_md + the SCANNER_ADJUSTABLE list. CLI `python -m v2.scanner.evolve.run --iterations N --universe nasdaq100_sp500 --out-dir <dir>` (load_dotenv; prefetch bundles over the full span; evolve; read TEST once post-loop; write report). Run → green.
- [ ] **Step 5: commit** `feat(scanner-evolve): evolve wiring + CLI (reuses self_evolve loop; test read once post-loop)`.

### Task 7: report + offline smoke + regression

**Files:** Create `v2/scanner/evolve/report.py` + `test_smoke.py`.

- [ ] **Step 1: smoke** — synthetic cached bundles + a stub proposer → `evolve_scanner` for a few iterations → read TEST once → `write_report` (iteration path of val fitness + the retained config + the TEST verdict + an honest "val≠edge; the live scanner forward-test is the judge" caveat). Assert md+html exist, the test fitness renders, and "test" never appeared in the loop's fitness calls.
- [ ] **Step 2: full regression** — `v2/self_evolve/` + `v2/scanner/` suites stay green.
- [ ] **Step 3: commit** `feat(scanner-evolve): run report + offline smoke (test verdict, test-never-read)`.

---

## Self-Review (against the spec)
- Adjustable = detector thresholds + severity_mult + top_n; `quant_weight` fixed 0 (Task 1 rejects it) — spec §config + invariant 2. ✓
- Fitness = A/B-vs-random `diff` (Task 3) + alpha_5d secondary; no-lookahead via CachedAsOfClient — spec §fitness + invariant 1. ✓
- Sample isolation train(bear+bull)/val(choppy)/test(held-out), test never in loop (Task 6 assertion) — spec §isolation. ✓
- Engine reuse (loop/proposer/versioning), bundles prefetched once (Task 4 = the perf fix) — spec §engine. ✓
- Never-raise + floors (Task 3) — invariants 3-4. ✓

## Execution Handoff
Recommended: **Subagent-Driven** (fresh opus per task + two-stage review). Phase 1→2→3 sequential (fitness depends on config; loop depends on fitness+samples). The fitness adapter (Task 3) is the highest-risk task — it reimplements the eval's regime replay; give it the most review. A fresh session can execute this plan end-to-end (spec + plan + the v2/self_evolve engine are all committed).
