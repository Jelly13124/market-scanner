# Scanner signal quality — round 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Steps use `- [ ]` checkboxes. Fresh implementer per task; two-stage review
> (spec-compliance then code-quality); for any detector/scoring task ALSO run the
> scanner-invariant-reviewer.

**Goal:** Validate-then-build three improvements to the pruned 9-detector scanner —
volume confirmation for `intraday_move`, corroboration weighting, and gap/rsi
threshold recalibration — using tonight's eval harness, building only what the data
confirms.

**Architecture:** Three measurement scripts under `scripts/` reuse
`v2/scanner/eval/` (CachedAsOfClient no-lookahead, detector_scorecard,
evaluate_detector, regimes, phase3_backtest). A DECISION GATE after the
measurements decides which of three build changes (in `intraday_move.py`,
`scoring.py`/`ScannerWeights`, `gap.py`/`rsi_divergence.py`) proceed. Validation
re-runs the scorecard/replay.

**Tech stack:** Python 3.13 (anaconda), numpy/pandas, the existing v2 scanner +
eval harness.

**Spec:** `docs/superpowers/specs/2026-06-01-scanner-signal-quality-round2-design.md`

---

## Constraints (paste into every implementer prompt)

- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `-m pytest`; run from repo
  root with `PYTHONPATH=.` and `PYTHONIOENCODING=utf-8`.
- Branch `feature/scanner-eval` (continues tonight's work). Commit per task,
  conventional message, **NO Co-Authored-By; never --no-verify**. Explicit
  `git add <paths>` — never `-A`, never stage `.claude/settings.local.json`.
- All subagents **opus** (CLAUDE.md). Black pre-commit hook may reformat → re-add +
  re-commit.
- Detector/scoring invariants: real std floor on every z (no `or 1e-6`); signals/
  detectors never raise; `None` vs `EventTrigger(triggered=False)` distinct;
  `components: dict[str, float]` (RULE-3); `except` logs (RULE-5). Run
  `pytest tests/test_detector_invariants.py` before marking any detector task done.
- Measurement tests are OFFLINE (synthetic data). Only the Wave-M "run" tasks
  (M4/M5/M6) touch the network — they're compute, not unit tests.
- **Measure-then-build:** the build tasks (B1/B2/B3) are CONDITIONAL on their
  measurement's decision rule. If a measurement fails its rule, SKIP that build and
  record it in `findings_scanner_eval.md` (do not force the change).

---

## Wave M — Measurement (offline tests + real runs)

### Task M1: `eval_volume_confirm.py` — measure volume confirmation

**Files:** Create `scripts/eval_volume_confirm.py`; Test
`scripts/test_eval_volume_confirm.py`.

- [ ] **Step 1 — failing test.** Synthetic: a fake `intraday_move`-like detector that
  fires on known days; per-ticker price+volume bundles where the fire days split into
  high-vol (volume spike) and low-vol; the high-vol fire days are followed by a large
  move, low-vol fire days by a small move. Assert `split_fires_by_volume(...)` returns
  two buckets with the high-vol bucket's mean |fwd5d| > low-vol bucket's, and
  `summarize(...)` reports `diff>0`.
```python
def test_high_vol_bucket_more_interesting():
    res = run_volume_confirm(detector=_FakeIM(fire_on=[...]), bundles=BUNDLES,
                             spy=SPY, regime=REGIME, vol_threshold=1.0, rng_seed=0)
    assert res["high_vol"]["interestingness"] > res["low_vol"]["interestingness"]
    assert res["high_vol"]["n"] >= 1 and res["low_vol"]["n"] >= 1
```
- [ ] **Step 2** — run, expect FAIL (module missing).
- [ ] **Step 3 — implement.** `volume_z(prices, asof_idx, window=20)` reusing
  volume_anomaly's formula (std floor = 10% of mean). `run_volume_confirm(detector,
  bundles, spy, regime, *, vol_threshold=1.0, horizons=(5,20), rng_seed=0)`: replay
  the detector via `CachedAsOfClient` (no-lookahead); for each fire compute `vol_z`
  (≤asof) + the UNCLAMPED fwd |move| + dir-alpha; bucket by `vol_z >= vol_threshold`;
  also build the random baseline (reuse detector_scorecard's approach). Return per
  bucket: `n, interestingness (mean|fwd| − baseline), t`. Per regime.
- [ ] **Step 4** — run test → PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): volume-confirmation measurement for intraday_move`
  + progress.md line.

### Task M2: `eval_corroboration.py` — measure multi-detector co-firing

**Files:** Create `scripts/eval_corroboration.py`; Test `scripts/test_eval_corroboration.py`.

- [ ] **Step 1 — failing test.** Synthetic bundles + 2 fake detectors that co-fire on
  some days, single-fire on others; co-fire days followed by big moves, single by
  small. Assert `run_corroboration(...)` returns buckets keyed by `n_triggered`
  (1, 2+) and the `2+` bucket has higher mean |fwd5d| than the `1` bucket.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `run_corroboration(detectors, bundles, spy, regime, *,
  horizons=(5,20), rng_seed=0)`: for each (ticker, asof) run ALL detectors via one
  `CachedAsOfClient` (set_asof once), collect the triggered set + same-direction
  count; for each fired (ticker, asof) record `n_triggered`, `n_same_dir`, fwd |move|,
  dir-alpha (UNCLAMPED outcome). Bucket by `n_triggered` (1, 2, 3+); compute mean
  |fwd|, dir-alpha, vs random baseline, per regime. Also a same-dir vs mixed-dir
  split. Return the bucket table + write CSV.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): corroboration (multi-detector co-fire) measurement`

### Task M3: `eval_threshold_sweep.py` — sweep gap/rsi thresholds

**Files:** Create `scripts/eval_threshold_sweep.py`; Test `scripts/test_eval_threshold_sweep.py`.

- [ ] **Step 1 — failing test.** Synthetic: a detector whose ctor takes a threshold;
  bundles where a higher threshold fires less often but on bigger moves. Assert
  `sweep_threshold(make_detector, values=[...], ...)` returns one row per value with
  `fire_rate` decreasing and `interestingness` rising, and `pick_knee(rows)` selects
  the loosest value with `interestingness_t >= 2` and `fire_rate <= cap`.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `sweep_threshold(make_detector, values, bundles, spy,
  regimes, *, fire_rate_cap=0.10)`: for each threshold value, build the detector,
  run the scorecard math (reuse `score_detector`), record fire_rate (fires / eligible
  ticker-days) + interestingness + t per regime. `pick_knee(rows, *, fire_rate_cap)`
  applies the decision rule (loosest value with t≥2 positive in ≥2 regimes and
  fire_rate≤cap; else None → "no sane threshold"). Write CSV.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): gap/rsi threshold sweep measurement`

### Task M4: RUN the three measurements (real data, compute)

- [ ] Run each script over the 80-ticker subset × 3 regimes (reuse
  `scripts/rerender_eval_report.py`'s REGIMES + universe slice):
```
PYTHONPATH=. PYTHONIOENCODING=utf-8 C:\Users\Jerry\anaconda3\python.exe scripts/eval_volume_confirm.py
... eval_corroboration.py ; ... eval_threshold_sweep.py --detector gap ; --detector rsi_divergence
```
- [ ] Collect CSVs under `scanner_eval/`. Apply each decision rule; write a
  "Round 2 measurements" section to `findings_scanner_eval.md` recording: for each
  item, the numbers + the **BUILD / SKIP** decision + chosen parameter.
- [ ] Commit artifacts + findings. **This task's output gates Wave B.**

---

## Wave B — Build (CONDITIONAL on M4 decisions)

### Task B1: Volume factor on `IntradayMoveDetector` — *only if M4 says BUILD*

**Files:** Modify `v2/scanner/detectors/intraday_move.py`; Test add to
`v2/scanner/test_detectors.py` (or `test_detector_intraday_move.py`).

- [ ] **Step 1 — failing test.** Two identical big-move bars, one on high volume one
  on low; assert the high-volume one gets a strictly higher `severity_z` when
  `volume_alpha > 0`, and identical severity when `volume_alpha == 0` (default off).
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** Add ctor args `volume_alpha: float = 0.0`,
  `volume_z_cap: float = 3.0`. After computing severity, multiply by
  `1 + volume_alpha * clip(volume_z, 0, volume_z_cap)` where `volume_z` is computed
  ≤asof with the 10%-of-mean std floor. Set `volume_alpha`'s recommended default from
  M4 (keep 0.0 if M4 said the effect was marginal — config-on only). Surface `vol_z`,
  `vol_factor` in `components` (floats). No raise; std floor; RULE-3/5.
- [ ] **Step 4** — PASS + `pytest tests/test_detector_invariants.py`.
- [ ] **Step 5 — commit.** `feat(scanner): optional volume-confirmation boost on intraday_move`

### Task B2: `corroboration_mult` in scoring — *only if M4 says BUILD*

**Files:** Modify `v2/scanner/models.py` (`ScannerWeights`), `v2/scanner/scoring.py`;
Test `v2/scanner/test_detectors.py::TestComputeComposite`.

- [ ] **Step 1 — failing test.** Two co-firing triggers + `corroboration_mult=0.25` →
  composite higher than the same with `corroboration_mult=0.0`; a single trigger is
  unaffected by the mult.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** Add `corroboration_mult: float = 0.0` to `ScannerWeights`
  (range [0, 2], comment referencing the eval). In `compute_composite`, after the
  blend, if `len(triggered) >= 2`: `composite *= 1 + corroboration_mult *
  (len(triggered) - 1)`; then clip to 100. (If M4 found same-direction matters, gate
  on the signed-agreement count instead — implement per the M4 finding.) Document in
  README scoring.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner): corroboration multiplier for multi-detector co-fires`

### Task B3: Recalibrate gap/rsi thresholds — *only for whichever M4 found a knee*

**Files:** Modify `v2/scanner/detectors/gap.py` and/or
`v2/scanner/detectors/rsi_divergence.py`; Tests in their detector test files.

- [ ] **Step 1 — failing test.** Assert the detector with the NEW default threshold
  does NOT fire on a borderline case the OLD threshold caught (and still fires on a
  clearly-extreme case).
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** Update the ctor default threshold(s) to the M4-chosen
  value(s). Keep ctor-overridable. Update the detector docstring + README/DETECTOR_METADATA
  description if it cites the old number. If M4 found NO sane threshold for a
  detector, SKIP it and record a "retire candidate" note (do not auto-retire).
- [ ] **Step 4** — PASS + invariants.
- [ ] **Step 5 — commit.** `feat(scanner): recalibrate gap/rsi thresholds per round-2 sweep`

---

## Wave V — Validate

### Task V1: Re-measure + bounded replay with the builds on

- [ ] Re-run the detector scorecard (`run_eval.py --no-phase3` or a focused re-score)
  with the B-wave changes; confirm `intraday_move` interestingness rises (B1), and the
  recalibrated detectors now show positive interestingness at a sane fire-rate (B3).
- [ ] Run a bounded `phase3_backtest` with `corroboration_mult` set vs 0 (B2) →
  report the real Top-N alpha delta (like the quant on/off ablation).
- [ ] Append the round-2 results + final KEEP/parameter decisions to
  `findings_scanner_eval.md`. Commit artifacts.
- [ ] Final summary: what was built vs skipped, with the evidence.

---

## Self-review (done)

- **Spec coverage:** volume-confirm (M1+B1+V1), corroboration (M2+B2+V1), gap/rsi
  recalibration (M3+B3+V1), measure-then-build gate (M4) — every spec item has
  measure + conditional build + validate. ✓
- **Placeholders:** none — each task has a concrete test + the script/scoring change.
  The recommended parameter values are intentionally resolved at M4 (the measurement),
  not guessed here. ✓
- **Type/invariant consistency:** `volume_alpha`/`corroboration_mult` config fields,
  `components: dict[str,float]`, std floors, detector-invariant lint run on every
  detector/scoring task. Build tasks explicitly conditional on M4. ✓
