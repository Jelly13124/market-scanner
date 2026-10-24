# Scanner signal quality — round 2 (volume confirm + corroboration + gap/rsi calibration)

**Status:** spec written autonomously 2026-06-01 while the user slept; defaults
chosen on every ambiguity and recorded under "Decisions". For morning review →
writing-plans → implementation. Branch `feature/scanner-eval` (continues tonight's
eval work). NOT merged to main.

## Goal

Improve the now-pruned **9-detector** scanner (quant overlay off, 4 detectors
retired tonight) with three changes, each **measured first with the existing eval
harness and built only if it helps**:

1. **Volume confirmation for `intraday_move`** — does a big move *on high volume*
   flag bigger forward moves than a big move alone?
2. **Corroboration weighting** — do tickers where **≥2 detectors co-fire** beat
   single-detector fires (and random)? If so, reward it in the composite.
3. **`gap` / `rsi_divergence` threshold recalibration** — both fire far too often
   (gap ~55% of ticker-days, rsi ~24%), which structurally caps their
   interestingness. Find tighter thresholds that make them discriminating.

**Load-bearing principle: measure → build only if confirmed → re-measure.** We do
NOT blindly add a volume gate or a corroboration bonus; tonight's harness
(`v2/scanner/eval/`) decides each one on evidence. This keeps round 2 honest and
prevents re-introducing noise we just removed.

## Reuse (tonight's harness)

- `v2/scanner/eval/cached_asof_client.py` — `CachedAsOfClient` / `TickerBundle`
  (no-lookahead, the keystone).
- `v2/scanner/eval/detector_scorecard.py` — per-detector interestingness-vs-random
  + dir-alpha; `score_detector`, `evaluate_detector` (abs-move interestingness).
- `v2/scanner/eval/regimes.py` — the 3 SPY regime windows.
- `v2/scanner/eval/phase3_backtest.py` — bounded full-replay (real Top-N alpha,
  quant/feature on-vs-off) with `spread_days` even-sampling + `universe_tickers`
  cap (both fixed tonight).
- `v2/scanner/scoring.py::compute_composite` — where corroboration + the volume
  term plug in. `ScannerWeights` (config) is where new knobs live (default OFF →
  measure first).

Universe + regimes + 80-ticker subset + horizons (5d primary, 20d secondary) are
the same as tonight so results are comparable.

---

## Item 1 — Volume confirmation for `intraday_move`

`intraday_move` is the ONE detector that beat random (interestingness +1.4–1.7pp,
t=4–8 all regimes). It is **price-only** today (close-vs-open / gap / range,
benchmark-adjusted) — it ignores volume. Hypothesis: a big move *confirmed by
volume* is "more real" and has larger forward |move|.

### Measure (new script `scripts/eval_volume_confirm.py`)
- For each `intraday_move` fire (via `CachedAsOfClient`, no-lookahead), compute the
  fire-day **volume z** (today vs trailing 20-bar mean, std floor 10% of mean —
  reuse the formula already in `volume_anomaly.py`).
- Split fires into **high-volume** (`vol_z ≥ V`) vs **low-volume** (`vol_z < V`),
  default `V = 1.0`. Compare interestingness (mean |fwd 5d| ) of the two buckets
  AND each vs the random baseline, per regime. Welch t.
- **Decision rule:** volume confirmation "works" if high-vol fires have
  interestingness meaningfully > low-vol fires (diff > 0, t ≥ 2) in ≥2 regimes.

### Build (only if confirmed)
- Add a **volume severity factor** to `IntradayMoveDetector`: multiply the
  computed severity by `1 + α · clip(vol_z, 0, Z_CAP)` (default `α = 0.0` → no-op
  until enabled; recommended value set from the sweep). NOT a hard gate (gating
  drops events; a boost preserves them and just ranks volume-confirmed moves
  higher). Volume read strictly `≤ asof`.
- New `IntradayMoveDetector(volume_alpha=..., volume_z_cap=...)` ctor args;
  document the std floor. Components dict surfaces `vol_z` + `vol_factor` for
  debugging (must stay `dict[str, float]` per RULE-3).
- Std floor on volume (no `or 1e-6`), signals/detectors-never-raise, `None` vs
  `triggered=False` semantics all preserved.

### Re-measure
Re-run the detector scorecard for `intraday_move` with the volume factor on; confirm
interestingness rises without collapsing n. TDD unit test: a synthetic high-vol
big-move fire gets a higher severity than the same move at low volume.

---

## Item 2 — Corroboration weighting

Tonight's split: individually 12/13 detectors looked weak, but the **combination**
(detector-only Top-N) beat SPY in all 3 regimes. That suggests corroboration —
multiple detectors agreeing — carries the value. Quantify it, then reward it.

### Measure (new script `scripts/eval_corroboration.py`)
- For each (ticker, asof) over the regimes, run ALL 9 detectors via
  `CachedAsOfClient`; record `n_triggered` and the **same-direction** count.
- Bucket fires by `n_triggered` (1, 2, 3+). For each bucket compute mean |fwd 5d|
  + dir-alpha, vs the random baseline, per regime.
- **Decision rule:** corroboration "works" if the ≥2 bucket has interestingness
  (and/or dir-alpha) significantly above the 1 bucket in ≥2 regimes. Also report
  whether **same-direction** corroboration beats mixed-direction.

### Build (only if confirmed)
- Add `corroboration_mult: float = 0.0` to `ScannerWeights` (default 0 → off).
  In `compute_composite`, when `n_triggered ≥ 2`, scale the composite:
  `composite *= 1 + corroboration_mult · (n_triggered − 1)`, then clip to 100.
  (Optionally gate on same-direction corroboration — decided by the measurement.)
- `event_severity` raw tiebreaker unchanged. Document in `README.md` scoring.

### Validate
- Phase-3-style bounded replay (`phase3_backtest`) with `corroboration_mult` set
  vs 0 → does the real Top-N alpha improve? Report the delta like the quant
  on/off ablation. TDD: `compute_composite` with 2 co-firing triggers +
  `corroboration_mult>0` yields a higher composite than the same with mult 0.

---

## Item 3 — `gap` / `rsi_divergence` threshold recalibration

`gap` fired ~55% of ticker-days, `rsi_divergence` ~24% — at those rates the "fired"
set ≈ the whole population, so interestingness is ~0 by construction. These are
**mis-calibrated, not useless** (per tonight's finding). Find tighter thresholds.

### Measure (new script `scripts/eval_threshold_sweep.py`)
- **gap:** sweep the gap σ-threshold (currently ≥3σ) over e.g. {3, 3.5, 4, 4.5, 5}.
- **rsi_divergence:** sweep the RSI-gap magnitude / severity floor and/or the
  divergence window.
- For each threshold value: compute fire-rate + interestingness (vs random) + t,
  per regime. Produce a curve `fire_rate → interestingness(t)`.
- **Decision rule:** pick the threshold at the "knee" — the loosest setting whose
  interestingness is positive AND significant (t ≥ 2) in ≥2 regimes, with
  fire-rate in a sane band (target ≤ ~10% of ticker-days). If no setting clears
  the bar, the detector is genuinely weak → flag for retirement (a separate
  decision, NOT auto-applied here).

### Build
- Update the detector default thresholds (their ctor defaults in `gap.py` /
  `rsi_divergence.py`) to the chosen values. Keep them ctor-overridable.
- Re-run the scorecard; confirm interestingness positive + fire-rate sane. TDD:
  the recalibrated detector does NOT fire on a borderline case that the old
  threshold caught.

---

## Outputs

- `scripts/eval_volume_confirm.py`, `scripts/eval_corroboration.py`,
  `scripts/eval_threshold_sweep.py` + their CSVs under `scanner_eval/`.
- An appended section in `findings_scanner_eval.md` (or a round-2 sibling) with the
  three decisions + the evidence.
- Code changes ONLY where a measurement confirmed value (volume factor,
  corroboration_mult, recalibrated thresholds), each behind a config knob and
  TDD-tested.

## Testing

- Each measurement script: offline unit test on synthetic data (fake detector /
  known volume / known co-fires) asserting the bucketing + metric math.
- Each build change: TDD on `compute_composite` / the detector, no network.
- Full `v2/scanner/` suite stays green; detector-invariants lint stays green.

## Decisions (defaulted while user asleep — confirm in review)

1. **Measure-then-build for all three** (don't blindly change scoring). Default.
2. **Volume = soft boost, not a hard gate** on `intraday_move` (preserve events).
3. **Corroboration = composite multiplier** keyed on `n_triggered ≥ 2`, config
   default 0 (off) until the measurement justifies a value.
4. **gap/rsi = recalibrate, don't retire** — unless the sweep finds NO sane
   threshold clears significance, in which case flag (don't auto-retire).
5. Same 80-ticker subset + 3 regimes + 5d/20d as tonight, for comparability.

## Out of scope

- Re-enabling the quant overlay (separate spec — needs paid fundamental history).
- New detectors beyond the volume term on `intraday_move`.
- Acting on a "retire" flag from Item 3 (surface it; the user decides).
