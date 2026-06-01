# Scanner round-2 — measurement results (2026-06-01)

Three "measure-then-build" hypotheses from the round-2 spec, on the 80-ticker × 3-regime
grid (same as the Phase-1–3 eval). **None of the three earned a clean "build it"** — a
valuable negative result that kept us from adding noise. Raw CSVs:
`scanner_eval/{volume_confirm,threshold_sweep_gap,corroboration}.csv`.

## ① Volume confirmation for `intraday_move` → ❌ HYPOTHESIS REJECTED (do not build)

Hypothesis: a big intraday move ON high volume flags bigger forward moves than on low
volume. **The data says the opposite.** `interestingness` (mean |fwd move| vs random),
high-vol vs low-vol bucket:

| regime | horizon | high_vol | low_vol |
|---|---|---|---|
| BEAR | 5d | +1.03pp (t=4.3) | **+1.70pp (t=8.7)** |
| BEAR | 20d | +1.03pp | **+3.32pp** |
| BULL | 5d | +1.05pp | **+1.68pp** |
| BULL | 20d | +1.86pp | **+4.40pp** |
| CHOPPY | 5d | +1.73pp | +1.58pp (≈tie, high slightly bigger) |
| CHOPPY | 20d | +3.28pp | **+7.34pp** |

In 5 of 6 cells, **LOW-volume** intraday moves have the bigger forward move. Interpretation:
a big move on low volume is "unconfirmed/fragile" → larger subsequent move (continuation
or violent reversal); on high volume it's "absorbed" → settles down. **Verdict: do NOT add
a high-volume gate/boost** — it would prefer the LESS interesting moves. `intraday_move`
stays price-only. (Both buckets are positive — the detector is good regardless of volume.)

## ② `gap` threshold recalibration → 🔴 RETIRE (not a calibration fix — it's broken)

Swept the gap σ-threshold 3.0 → 5.0. Two damning facts:

| threshold | BEAR fire-rate | BULL | CHOPPY | interestingness (all regimes) |
|---|---|---|---|---|
| 3.0σ | 57% | 44% | 21% | negative (t = −8 / −4 / −10) |
| 5.0σ | **49%** | 37% | 10% | still negative (t = −8 / −4 / −8) |

A **5-sigma** gap event firing on **49%** of bear ticker-days is impossible if the z-score
were sound → `gap`'s z-scoring is **mis-scaled/broken** (the threshold barely changes the
fire rate). And interestingness is **negative at every threshold** (gap-flagged stocks move
LESS than random). No sane threshold exists. **Verdict: RETIRE `gap`** (same treatment as the
4 retired in the Phase-1 eval). Fixing its z-scoring is a separate, deeper investigation.

## ③ Corroboration (≥2 detectors co-firing) → ⚠️ PARTIAL (directional only, not magnitude)

Bucketed fires by `n_triggered` (1 / 2 / 3+) + same-vs-mixed direction. Two metrics:
`interestingness` (does a co-fire flag a bigger move — the pre-filter lens) and `dir_alpha`
(does the agreed direction pay — the directional lens).

- **Interestingness: NO.** Co-fire buckets (2, 3+) are negative or insignificant vs random
  — multi-detector agreement does NOT flag bigger-magnitude moves. So corroboration is
  worthless as an LLM-cost pre-filter booster.
- **Directional alpha: YES, for SAME-direction agreement.**
  - BEAR, 3+ co-fire: dir-α **+0.96pp (t=3.6)**.
  - CHOPPY, ≥2 same-direction: dir-α **+0.86pp (t=3.1)**.
  - Mixed-direction co-fires: noise (negative interestingness, ~0 dir-α).

**Verdict:** corroboration carries a **directional** edge when detectors agree on direction
— reconciles with the Phase-3 finding that the detector composite had directional value.
Worth an OPTIONAL **same-direction corroboration boost** in scoring (default off), enabled
only when the scanner is used directionally; SKIP it for the pure pre-filter use.

## Recommended actions

1. **RETIRE `gap`** — broken z-scoring (5σ fires 49%), negative interestingness everywhere.
   Unregister like the other retired detectors (reversible). After this the scanner is
   **8 registered detectors**.
2. **Do NOT add volume confirmation** to `intraday_move` — the hypothesis was rejected.
3. **Corroboration:** optional `corroboration_mult` keyed on *same-direction* ≥2 agreement,
   default 0 (off); enable only for directional use. Not worth it for the pre-filter use.
4. **`rsi_divergence`** still couldn't be swept (no tunable fire threshold) — a separate
   `min_rsi_gap` param would be needed first; deferred.

## Net scanner state after round-2

The useful core is **`intraday_move`** (price-only, the one detector that beats random on
magnitude). Quant overlay off. `gap` joins the retired set. Corroboration is a directional
nicety, not a pre-filter win. The honest conclusion from two rounds: the scanner's
*pre-filter* value is concentrated in `intraday_move`; its *directional* value is in the
detector composite + same-direction corroboration.
