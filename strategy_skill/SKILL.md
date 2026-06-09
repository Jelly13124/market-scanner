---
name: factor-strategy-evolve
description: The fixed factor-strategy kernel + the iteration protocol the self-evolve LLM must follow. Read this before proposing any config delta. Defines what is FIXED (the strategy design) vs ADJUSTABLE (the knobs in skill_config.yaml), the one-hypothesis-per-round discipline, and the train/val/test sample-isolation rules.
disable-model-invocation: true
---

# Factor-strategy self-evolve protocol

You are tuning a **deterministic, long-only, medium-term factor strategy** by
proposing CONFIG deltas. You do NOT write strategy code. You change numbers in
`skill_config.yaml`, one hypothesis at a time, and the harness measures whether
that hypothesis helped — under strict sample isolation.

This document is the contract. The boundary it describes is enforced in code by
`v2/self_evolve/config.py` (`ADJUSTABLE`, `validate`, `apply_delta`): a delta
outside the rules will be rejected before it ever runs. Treat the rules here as
the *intent* behind that gate.

---

## The FIXED kernel (do NOT violate)

The strategy *design* is frozen. These properties define what the strategy IS;
changing them would make it a different strategy and break comparability across
rounds:

- **Long-only.** No shorts, no leverage. Weights are non-negative and sum to 1.
- **Medium-term, price-led.** The signal is a cross-sectional composite whose
  lead factors are price-based:
  - **momentum** — 12-1 month total return (skip the most recent month),
  - **low_vol** — inverse realized volatility,
  - **reversal** — short-horizon (≈1 month) mean reversion,
  with a **shallow fundamental overlay**:
  - **value** — earnings yield (E/P),
  - **quality** — return on equity (ROE).
- **Top-N, volatility-inverse weighted.** Each rebalance: rank the liquid
  universe by the composite, take the top N, weight inversely to volatility
  (the `tilt_strength` knob scales how aggressive that tilt is), cap any single
  name at `max_weight`.
- **Monthly rebalance** with a rank **holding buffer** (hysteresis) to damp
  turnover.
- **Liquidity-filtered universe.** Drop the bottom percentile by market cap and
  by average dollar volume before ranking.
- **Costs modeled.** Round-trip transaction costs (`cost_bps`) are charged on
  turnover; an "improvement" that only exists gross of costs is not an
  improvement.

The composite formula, the rebalance cadence, the weighting scheme, and the set
of factors are **not knobs**. They are not in `ADJUSTABLE` and `apply_delta`
will reject any attempt to edit them (e.g. `rebalance`, `cost_bps`).

---

## What you MAY change (the knobs)

Only the dotted paths declared in `v2/self_evolve/config.py::ADJUSTABLE`, only
within their declared ranges:

| Path | Range | Meaning |
|------|-------|---------|
| `factor_weights.momentum` | [0, 1] | relative weight of each factor in the |
| `factor_weights.low_vol`  | [0, 1] | composite. Sum-normalized to 1.0 on load, |
| `factor_weights.reversal` | [0, 1] | so only the *ratios* matter. |
| `factor_weights.value`    | [0, 1] | |
| `factor_weights.quality`  | [0, 1] | |
| `lookback.momentum_days`  | [120, 300] | momentum formation window (days) |
| `lookback.vol_days`       | [20, 120]  | realized-vol window (days) |
| `lookback.reversal_days`  | [5, 42]    | reversal window (days) |
| `top_n`                   | [20, 50]   | number of names held |
| `holding_buffer`          | [0, 20]    | rank hysteresis band (turnover damp) |
| `max_weight`              | [0.03, 0.08] | per-name weight cap |
| `liquidity_pct.mktcap_pct`| [0, 1]     | fraction dropped by market cap |
| `liquidity_pct.advol_pct` | [0, 1]     | fraction dropped by dollar volume |
| `tilt_strength`           | [0, 1]     | 0 = equal weight, 1 = full vol-inverse |

A delta is a dict mapping one of these paths to a new value, e.g.
`{"factor_weights.momentum": 0.40}` or `{"top_n": 35}`. `apply_delta` returns a
NEW validated config (factor weights re-normalized) and never mutates the input.

---

## Iteration discipline

1. **ONE hypothesis per round.** A round changes a single coherent idea — most
   often a single path. ("Momentum is underweighted given the regime → raise
   `factor_weights.momentum`.") If you must move two paths, they have to be the
   same hypothesis (e.g. shifting weight *from* reversal *to* momentum). Never
   bundle unrelated changes; you won't be able to attribute the result.
2. **Config-only.** You edit `skill_config.yaml` via a delta. You do **not**
   touch shared code — not the strategy, not the data loaders, not the
   evaluator, not `config.py` itself. The kernel is shared infrastructure;
   editing it invalidates every prior and future comparison.
3. **State the hypothesis and the expected effect before you propose the
   delta.** "I expect raising momentum weight to improve validation Sharpe if
   the recent regime is trending." This is what makes a round falsifiable.
4. **Stay inside the ranges.** If your idea needs a value outside `ADJUSTABLE`,
   the hypothesis is out of scope — record it, don't force it.

---

## Train / validation / test permissions

Sample isolation is the whole point — it is what keeps the search honest.

- **train** — fit / form signals. You may look at it freely.
- **validation** — the ONLY set you optimize against. Each round, accept or
  reject the hypothesis based on validation metrics. This is where the loop
  lives.
- **test** — held out. **Test NEVER enters the loop.** You do not look at test
  metrics to decide a delta, you do not tune to test, you do not peek. Test is
  scored **once**, at the very end, on the single config the validation loop
  settled on, to get an unbiased estimate. Touching test during iteration
  silently destroys the experiment — there is no error message for overfitting.

If you are ever unsure whether an action would leak test information into the
loop, the answer is: don't.
