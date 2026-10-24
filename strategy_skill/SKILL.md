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
- **Medium-term, price-led.** The signal is a cross-sectional composite of **11
  factors** (see the factor kernel below). It is price-led: the price/volume
  factors carry the bulk of the blend and momentum leads, with a shallow
  fundamental overlay. Signs are baked so HIGHER composite = more attractive.
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

## The factor kernel (the 11 factors)

The composite is a cross-sectional z-score blend of these 11 factors, computed
as-of each rebalance date in `v2/self_evolve/factors.py`. Each factor's sign is
baked so **HIGHER z = more attractive**. Their relative weights live in
`factor_weights` (the seven price/volume factors carry ~72% of the v0 book, the
four fundamentals ~28% — momentum leads).

**Price / volume factors** (the lead block; computed from as-of close/volume bars):

| Factor | One-line definition | Anchor paper |
|--------|---------------------|--------------|
| `momentum` | 12-1 month total return — trailing 12-month return skipping the most recent ~1 month. | Jegadeesh & Titman (1993), momentum |
| `reversal` | Negated short-horizon (≈1 month) return — recent winners revert down. | Jegadeesh (1990), short-term reversal |
| `low_vol` | Negated realized volatility (stdev of daily returns) — low-vol names score high. | Ang, Hodrick, Xing & Zhang (2006), IVOL / low-vol anomaly |
| `resid_mom` | Idiosyncratic momentum — intercept of a 1-factor OLS of the stock's daily returns on the equal-weight cross-sectional market. | Blitz, Huij & Martens (2011), residual momentum |
| `high_52w` | Proximity to the 52-week high — `close / max(close)` over the trailing ~252 bars. | George & Hwang (2004), 52-week-high momentum |
| `max_lottery` | Negated max single-day return over the trailing ~1 month — lottery-like spikes are penalised. | Bali, Cakici & Whitelaw (2011), MAX effect |
| `turnover` | Negated relative recent turnover — `mean(recent vol) / mean(full-series vol)`; elevated turnover is penalised (illiquidity premium). | Datar, Naik & Radcliffe (1998), turnover / liquidity |

**Shallow-fundamental overlay** (computed from line items, lagged 60 days — see below):

| Factor | One-line definition | Anchor paper |
|--------|---------------------|--------------|
| `value` | Earnings yield E/P — `EPS / close` (positive only) — cheap stocks score high. | Fama & French (1992/1993), value / HML |
| `gross_prof` | Gross profitability — `gross_profit / total_assets` (metrics `gross_margin` fallback). | Novy-Marx (2013), gross profitability |
| `asset_growth` | Negated YoY change in total assets — `-(ta_t / ta_prev − 1)`; conservative (low-growth) firms score high. | Cooper, Gulen & Schill (2008) / Fama-French (2015) CMA, investment factor |
| `quality` | Return on equity — `EPS / book_value_per_share` (a loss is admissible). | ROE quality (Fama-French RMW family) |

### No-lookahead discipline

Every factor is computed AS-OF the rebalance date with a hard ceiling, mirroring
the backtest replay client (`v2/scanner/eval/cached_asof_client.py`):

- **Prices** use only bars dated `<= asof`. A future bar — even one present in
  the bundle — can never enter a factor; series are clamped before any math.
- **Fundamentals** are lagged: a statement for fiscal period `D` is only
  knowable at `D + 60d` (`FUNDAMENTAL_AVAILABILITY_LAG_DAYS`), so at ceiling
  `asof` only records with `report_period <= asof − 60d` are read.

A ticker with insufficient price history is omitted entirely; an individual
fundamental factor degrades to a neutral z (the name is kept) when its statement
field is missing. The computation never raises.

**The proposer does NOT change the factors or the formula.** It only adjusts the
`ADJUSTABLE` weights (`factor_weights.*`) and lookback windows below — one
hypothesis per round. The factor set, the signs, and the composite/weighting
scheme are part of the fixed kernel.

---

## What you MAY change (the knobs)

Only the dotted paths declared in `v2/self_evolve/config.py::ADJUSTABLE`, only
within their declared ranges:

| Path | Range | Meaning |
|------|-------|---------|
| `factor_weights.momentum` | [0, 1] | relative weight of each of the 11 factors |
| `factor_weights.reversal` | [0, 1] | in the composite. Sum-normalized to 1.0 |
| `factor_weights.low_vol`  | [0, 1] | on load, so only the *ratios* matter. |
| `factor_weights.resid_mom`| [0, 1] | |
| `factor_weights.high_52w` | [0, 1] | |
| `factor_weights.max_lottery` | [0, 1] | |
| `factor_weights.turnover` | [0, 1] | |
| `factor_weights.value`    | [0, 1] | |
| `factor_weights.gross_prof` | [0, 1] | |
| `factor_weights.asset_growth` | [0, 1] | |
| `factor_weights.quality`  | [0, 1] | |
| `lookback.momentum_days`  | [120, 300] | momentum formation window (days) |
| `lookback.vol_days`       | [20, 120]  | realized-vol window (days) |
| `lookback.reversal_days`  | [5, 42]    | reversal window (days) |
| `lookback.max_days`       | [10, 42]   | max-daily-return (lottery) window (days) |
| `lookback.hi_days`        | [120, 300] | 52-week-high window (days) |
| `lookback.to_days`        | [10, 63]   | turnover averaging window (days) |
| `lookback.resid_days`     | [120, 300] | residual-momentum window (days) |
| `top_n`                   | [20, 50]   | number of names held |
| `max_weight`              | [0.03, 0.08] | per-name weight cap |
| `liquidity_pct.mktcap_pct`| [0, 1]     | fraction dropped by market cap |
| `liquidity_pct.advol_pct` | [0, 1]     | fraction dropped by dollar volume |
| `cost_bps`                | [0, 50]    | round-trip transaction cost (bps) |

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
