# Scanner Self-Evolve (detector thresholds) — Design

**Date:** 2026-06-11
**Status:** approved direction (B+C-sized; spec for a focused subagent build)

## Goal

Apply the `v2/self_evolve/` engine to the SCANNER config — auto-tuning the **event-detector thresholds + severity multipliers + top_n**, NOT the fundamental quant signals (which a rigorous no-lookahead eval already found HURT the scanner in every regime; `quant_weight` stays 0). The detector-only scanner already beats SPY in all 3 regimes; this searches whether tuning the detector parameters improves it further, under sample isolation + an A/B-vs-random fitness.

## What this is NOT (settled by evidence)

The scanner's fundamental quant signals (value/quality/earnings_quality) exist but are off (`ScannerWeights.quant_weight=0.00`, 2026-06-01): a no-lookahead full-replay (CachedAsOfClient + 60d lag) showed quant ON dragged 5d alpha down every regime (−1.83% bear). So we do NOT add/enable fundamental signals; `quant_weight=0` is a fixed kernel constraint here.

## Adjustable config (the scanner "skill_config")

A bounded `ScannerEvolveConfig` over the existing detector params + `ScannerWeights`:
- per-detector windows/lookbacks/thresholds — e.g. `high_breakout.window`, `high_breakout.lookback_days`, `ma_cross.fast/slow`, `gap.threshold`, `rsi_divergence.window` (each with a declared (min,max)).
- per-detector severity multipliers (`severity_mult` in scoring, bounds e.g. 0.5–2.0).
- `top_n`.
- `enabled_detectors` (which subset fires) — optional, discrete.
- FIXED (kernel): `event_weight=1.0`, `quant_weight=0.0`.

## Fitness (per sample) — A/B vs random, NOT directional alpha

`scanner_fitness(config, sample) -> {fitness, diff, t_stat, n_fired, alpha_5d}` reusing the eval:
- Replay the scanner over the sample's regime window with `CachedAsOfClient` (no-lookahead: every read ≤ asof, fundamentals 60d-lagged).
- Primary fitness = the **A/B-vs-random diff** (`detector_ab.evaluate_detector`: mean forward return of the scanner's fired/Top-N set − a random same-universe baseline) + its t_stat. Per the project design intent (scanner = an LLM-cost pre-filter; evaluate vs a random baseline, NOT dir-adjusted alpha). Secondary: 5d alpha vs SPY (Phase 3 metric).
- The loop keeps a config iff val fitness (diff) improves AND guardrails (t_stat not worse, n_fired not collapsed below a floor, doesn't blow up turnover/Top-N churn).

## Sample isolation

Only 3 labelled regimes exist, so: **train** = bear_2022 + bull_2023_24 (propose/screen), **val** = choppy_2025 (keep/rollback decision), **test** = a held-out window NEVER read in the loop (a later window, e.g. 2025-Q4/2026-H1, classified at run time) — read once post-loop for the human verdict + then the live scanner forward-test. The loop reads train+val only (the engine's existing invariant, asserted by a sample-recorder test).

## Engine reuse + the one perf problem

Reuse `v2/self_evolve/`: `proposer.propose` (LLM single-field deltas, now via SiliconFlow DeepSeek), `versioning` (version store + path log), `loop.evolve` (deterministic keep/rollback + guardrails + test-never-read). Swap `backtest_fn` → `scanner_fitness`. New: `scanner_config.py` (the bounded config + ADJUSTABLE) + `scanner_evolve.py` (the fitness adapter over `run_eval`/`run_scan`).

**Perf:** a scanner replay over a regime is heavy (full universe × dates × detectors). Like the factor backtest (17min→sec via caching), the scanner replay must cache the immutable per-(ticker,date) detector inputs across iterations — the prefetched price/fundamental bundles are immutable for the run, so build them ONCE and reuse across all proposer rounds. Most deltas change a threshold (recompute only the affected detector), not the data.

## No-lookahead (load-bearing)

The scanner eval's `CachedAsOfClient` already enforces it (reads ≤ asof, 60d fundamental lag). The self-evolve loop reads train+val only; test is read once post-loop. Forward returns (the fitness outcome) use post-asof prices — correct, not lookahead. Re-assert with a sample-recorder test (test regime never replayed in the loop).

## Honest caveats

- The quant-weight dimension is already searched (OFF wins); this tunes DETECTOR thresholds — a smaller search with modest upside on an already-SPY-beating scanner.
- 3 regimes is thin for train/val/test; the held-out test + the live scanner forward-test are the real judges. A config that wins on val may not generalize — a valid result.
- Self-evolution optimizes within the threshold space; it does not create edge. The detector-only scanner is already decent; this confirms or modestly improves it.

## Testing (offline, deterministic)

- `scanner_config.py`: load/validate/apply_delta over the bounded ADJUSTABLE (reuse the engine's pattern).
- `scanner_evolve.py`: `scanner_fitness` on a small synthetic/cached universe — deterministic, no network; a threshold delta changes the fired set + the diff.
- The loop with a stub proposer + stub fitness: keep/rollback, guardrails, sample isolation (test never replayed), resumable.
- Full regression: `v2/self_evolve/` + `v2/scanner/` suites stay green.

## Out of scope
- Enabling/adding fundamental quant signals (evidence: they hurt).
- A Lab panel for the scanner evolve (fast-follow).
