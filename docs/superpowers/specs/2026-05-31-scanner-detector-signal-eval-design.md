# Scanner detector/signal usefulness evaluation (regime-segmented)

**Status:** approved 2026-05-31. Overnight autonomous build + run on a dedicated
branch `feature/scanner-eval` off `main` (additive, independent of the unmerged
`feature/multi-tenant-accounts`); commit per task, leave for morning review, do
NOT merge. Deliverable the user reads in the morning: `findings_scanner_eval.md`.

## Goal

Produce a **scorecard** that says, for each of the scanner's **13 detectors**
and **5 quant signals**, whether it is *useful* or *useless* — measured
across three recent market regimes (**bull / bear / choppy**), with statistical
significance attached. "Useful" follows the established project framing
(memory `project_scanner_design_intent`, `feedback_backtest_framing`): the
scanner is an **LLM-cost pre-filter**, so the primary verdict is **A/B vs a
random baseline** ("does this detector surface stocks worth a deeper look more
than random picking?"), NOT directional alpha. Directional alpha is reported
per-regime as secondary colour.

The report must **land in the morning even if later phases fail** — it is
written incrementally.

## Why this design

Two evaluation engines already exist:

- `v2/backtesting/engine.py` — full `run_scan` replay → real Top-N composite +
  forward returns + benchmark alpha + per-detector co-fire breakout. Faithful,
  but **API-bound and slow** (its own docstring: "a 250-day backtest on SP500
  takes hours") and can only ablate quant signals **as a block** (cannot say
  *which* signal is useful).
- `v2/scanner/eval/detector_ab.py` — per-detector "fired vs random baseline"
  forward-return test. Pure, **unit-tested**, but its live entry point is a
  stub (`"[cli] Live run not yet implemented."`) and it reports a signed mean
  only.

Neither alone answers the user's question (per-detector **and** per-signal
usefulness, regime-segmented, overnight). The blocker for any live per-detector
replay is naïve re-fetching: `13 detectors × ~140 tickers × ~250 days` of API
calls is hundreds of thousands of requests. The fix — and the keystone of this
design — is a **`CachedAsOfClient`** that fetches each ticker's full history
**once**, then serves point-in-time (`≤ asof`) slices from memory. This turns
the workload from API-bound to CPU-bound and makes an overnight full sweep
feasible.

## Architecture — three phases, fail-soft, incremental report

```
load universe ─► fetch SPY ─► classify 3 regime windows
      │
      ├─ Phase 1  PRICE SCORECARD  (guaranteed to finish)
      │     prefetch prices once/ticker → CachedAsOfClient
      │     detector_scorecard: 13 detectors × 3 regimes  (price-only data)
      │     signal_ic:           5 signals  × 3 regimes  (price-only data)
      │     ─► write findings_scanner_eval.md  (price components fully scored)
      │
      ├─ Phase 2  EVENT/FUNDAMENTAL FILL-IN  (best-effort, time-boxed, additive)
      │     probe historical sources (yfinance / EODHD / Finnhub)
      │     enrich bundles with historical earnings/financials/sentiment/recs/insider
      │     re-score the 5 event detectors + 3 fundamental signals
      │     ─► rewrite report (fill DATA-LIMITED rows where data was found)
      │
      └─ Phase 3  FULL-REPLAY CONFIRMATION  (bounded, additive)
            v2/backtesting full replay per regime, quant ON and OFF
            ─► rewrite report (append real Top-N alpha + quant ablation)
```

Each phase is wrapped so a failure leaves the prior report intact. Wall-clock
budgets on Phases 2 and 3 guarantee they cannot sink the morning deliverable.

## Components (all new code under `v2/scanner/eval/`)

Each unit is small, single-purpose, and unit-tested with **injected data — no
network in tests**.

### 1. `cached_asof_client.py` — `CachedAsOfClient` (keystone, correctness-critical)

Wraps a pre-fetched per-ticker data **bundle** and serves the `DataClient`
Protocol with a **hard no-lookahead guarantee**.

- Construction: `CachedAsOfClient(bundle: TickerBundle)` where `TickerBundle`
  holds `prices: list[Price]` plus optional `insider`, `earnings`, `news`,
  `metrics_history`, `facts_history` (empty in Phase 1).
- `set_asof(date: str)` sets a hard ceiling. **Every** accessor clamps its
  result to records with `time/date ≤ asof`, regardless of the `start/end` the
  caller passes. This is the bulletproof guard — a detector that mis-computes
  its `end` can never see the future.
- `get_prices(ticker, start, end)` → cached bars in `[start, min(end, asof)]`.
- Event/fundamental accessors filter their bundle list to `≤ asof`, applying
  the **availability lag** below.
- **Availability rules (prevent lookahead on slow-published data):**
  - Prices, intraday: available same day (`≤ asof`).
  - Earnings surprise: available on the **announcement date** (yfinance
    `earnings_dates` gives it) — no lag.
  - **Fundamentals (statements): lag `FUNDAMENTAL_AVAILABILITY_LAG_DAYS = 60`.**
    A statement for period ending `D` is only visible at `D + 60d` (you did not
    know Q1 numbers on the quarter-end date). Conservative; documented.
  - News sentiment: same-day.
  - Analyst recommendation trend: available at its month-stamp.

### 2. `regimes.py` — regime windows

- `RegimeWindow(name, start, end, spy_return, max_drawdown, trend_r2, label)`.
- `classify_regimes(spy_prices, candidates) -> list[RegimeWindow]`: for each
  candidate window compute SPY total return, max drawdown, and trend R² (OLS of
  log-price vs time); label BULL / BEAR / CHOPPY and log the stats so the report
  can justify each window.
- **Default candidates** (exact boundaries confirmed from SPY at runtime; recent
  per the user's "近期"):
  - BEAR  `2022-01-03 → 2022-10-14` (rate-hike bear, SPY ≈ −25%)
  - BULL  `2023-10-27 → 2024-07-16` (AI bull)
  - CHOPPY `2025-02-18 → 2025-08-01` (tariff/DeepSeek high-vol sideways — confirm)
- If a candidate fails its label check (e.g. CHOPPY window actually trended),
  log a warning and keep it but annotate the mismatch in the report.

### 3. `detector_scorecard.py` — per-detector × regime evaluation

For each `(detector, regime)`:
- Over the universe, build a per-ticker `CachedAsOfClient` (price bundle from
  Phase 1, enriched bundle in Phase 2).
- Iterate `asof` over the regime's trading days; `set_asof`; call
  `detector.detect(ticker, asof, fd)`.
- For each FIRED `EventTrigger`, collect forward returns at horizons **5d
  (primary), 20d**:
  - `signed_ret` (raw), `abs_ret = |signed_ret|` (interestingness),
    `dir_ret = direction_adjust(signed_ret, trigger.direction)`,
    `alpha = ret − spy_ret` over the same window, `dir_alpha`.
- Build a **seeded random baseline** per ticker (reuse `detector_ab` approach:
  sample valid start indices, same horizon) and collect the same metrics.
- Call the **extended** `evaluate_detector` (see §8) to get, per horizon:
  `n_fired, coverage, interestingness_diff = mean(|fired|) − mean(|baseline|),
  interestingness_t (Welch), dir_alpha_mean, dir_alpha_t`.
- Emit one CSV row per `(detector, regime, horizon)` to `scanner_eval/detectors.csv`.
- `coverage`: fraction of universe tickers for which the detector had enough
  data to evaluate. Drives DATA-LIMITED.

### 4. `signal_ic.py` — per-signal × regime rank-IC

Signals are point-in-time cross-sectional factors, so the right measure is the
**Information Coefficient**, not a Top-N replay.

For each `(signal, regime)`:
- At **weekly** rebalance dates in the window, for every ticker compute
  `signal.compute(ticker, asof, fd)` (fd = `CachedAsOfClient`) → factor value;
  and the forward 5d/20d return.
- Cross-sectional **Spearman rank-IC** at each date between factor values and
  forward returns.
- Aggregate: `mean_ic`, `ic_t = mean_ic / std_ic × sqrt(n_dates)`, `n_dates`,
  `coverage`. Positive IC = useful; ≈0 = useless; negative = inverted.
- Emit rows to `scanner_eval/signals.csv`.
- momentum, technical → price-only, always covered. value, quality,
  earnings_quality → need Phase-2 historical fundamentals, else DATA-LIMITED.

### 5. `historical_events.py` — Phase 2 best-effort sourcing

- `probe_availability(sample_ticker) -> dict[source -> bool]` run once up front;
  logged. Each fetcher returns `[]`/`None` on failure (never raises).
- `fetch_earnings_history(ticker)` — **yfinance** `Ticker.get_earnings_dates()`
  → `(announce_date, eps_actual, eps_estimate, surprise_pct)`.
- `fetch_financials_history(ticker)` — **yfinance** quarterly
  financials/balance-sheet/cashflow → point-in-time `FinancialMetrics`/
  `CompanyFacts` keyed by period-end (consumed with the 60-day lag).
- `fetch_sentiment_history(ticker)` — **EODHD** `/sentiments` daily series.
- `fetch_recommendation_history(ticker)` — **Finnhub** recommendation-trend
  (monthly history) → net upgrade/downgrade flow for `analyst_rating`.
- `fetch_insider_window(ticker)` — **Finnhub** insider-transactions with a date
  range (depth-limited; document coverage).
- `target_price_change` stays **DATA-LIMITED** — no free historical target-price
  snapshots (the backtest engine already skips it).
- A global wall-clock budget (default 90 min, configurable). When exceeded,
  stop sourcing; un-enriched components stay DATA-LIMITED.

### 6. `report.py` — `findings_scanner_eval.md` renderer

- Reads `detectors.csv`, `signals.csv`, and any Phase-3 backtest CSV.
- Renders:
  - **Headline:** USEFUL list, USELESS list, DATA-LIMITED list (detectors +
    signals).
  - **Detector scorecard table:** rows = 13 detectors; columns per regime show
    `n_fired`, `interestingness_diff (t)`, `dir_alpha_5d`, and a verdict chip.
  - **Signal scorecard table:** rows = 5 signals; columns per regime show
    `mean_IC_5d (t)`, verdict.
  - **Phase 3 confirmation:** real Top-N mean alpha_5d per regime + the quant
    ON-vs-OFF ablation result.
  - **Regime definitions** (SPY return / drawdown / R² per window).
  - **Methodology + caveats** (no-lookahead, survivorship bias, availability
    lag, low-n flags, data coverage per component).
- **Verdict logic:**
  - `KEEP`  — interestingness_diff > 0 with `t ≥ 2` in **≥ 2 of 3** regimes.
  - `WATCH` — positive but weak/significant in only 1 regime, or mixed.
  - `CUT`   — interestingness_diff ≈ 0 or negative with adequate n
    (`n_fired ≥ 30` aggregate) → fired stocks behave like random, not worth the
    compute.
  - `DATA-LIMITED` — `coverage < 0.5` or aggregate `n_fired < 30`.
  - Signals: `KEEP` mean_IC ≥ +0.02 & `t ≥ 2` in ≥2 regimes; `CUT` |IC| < 0.01
    with adequate dates; `INVERTED` IC ≤ −0.02 & t ≤ −2; else `WATCH` /
    `DATA-LIMITED`.
  - Directional alpha is shown but **never** the sole basis for CUT.

### 7. `run_eval.py` — orchestrator CLI

`python -m v2.scanner.eval.run_eval [--universe nasdaq100_sp500] [--max-tickers N]
[--phase2-budget-min 90] [--phase3-max-days 8] [--no-phase3]`

Steps: load universe → fetch SPY + `classify_regimes` → **Phase 1** (prefetch
prices, detector_scorecard + signal_ic on price components, write report) →
**Phase 2** (probe, source, enrich bundles, re-score event/fundamental
components, rewrite report) → **Phase 3** (per-regime bounded
`v2.backtesting` replay, quant on/off, parse, rewrite report) → append a wrap-up
to `progress.md`. Every phase try/except-wrapped with a clear log line.

### 8. Extend `detector_ab.evaluate_detector`

Add, alongside the existing signed mean/diff/t: `abs_mean_fired`,
`abs_mean_baseline`, `interestingness_diff`, `interestingness_t` (Welch on the
abs arrays), and pass-through for direction-adjusted arrays. Keep the existing
keys and tests green (additive change).

## Correctness guards (what makes the report trustworthy)

1. **No lookahead** — `CachedAsOfClient.set_asof` clamps all data to `≤ asof`;
   fundamentals additionally lagged 60d. Unit-tested explicitly.
2. **Adjusted close** for all returns.
3. **Survivorship bias** — universe is the current snapshot (delisted/merged
   names absent). Stated in the report; not fixable without point-in-time
   constituents (out of scope).
4. **Sample size honesty** — low-n verdicts flagged; t-stats always shown.
5. **Seeded RNG** for baselines → deterministic, reproducible.

## Parameters

- Universe: `nasdaq100_sp500` seed (~140). Survivorship caveat noted. (Refresh
  to a real 500 is out of scope this round.)
- Horizons: 5d (primary), 20d.
- Regimes: 3 windows above, runtime-confirmed from SPY.
- Benchmark: SPY.

## Testing

TDD per unit, all offline (mock clients / synthetic series):
- `cached_asof_client`: no-lookahead clamp; slice correctness; 60d fundamental
  lag; empty bundle → empty (not crash).
- `regimes`: monotonic-up SPY → BULL, down → BEAR, flat → CHOPPY.
- `detector_scorecard`: synthetic prices + a fake detector firing on known days
  → expected fire vs baseline metrics.
- `signal_ic`: factor == forward return → IC ≈ +1; negated → ≈ −1; shuffled →
  ≈ 0.
- `evaluate_detector` extension: abs/interestingness metrics on known arrays;
  existing keys unchanged.
- `historical_events`: mocked yfinance/clients → parsing correctness; **no
  network**.
- `report`: fixed CSV fixture → asserts headline lists, table rows, verdict
  strings.
- `run_eval`: monkeypatched phases → asserts fail-soft (Phase 2/3 raising still
  leaves a Phase-1 report) and incremental rewrite.

## Out of scope (this round)

- Wiring per-user API keys into the analyze/scan pipeline (the agreed **next**
  workstream).
- Refreshing universe CSVs to full membership.
- Public deployment (Project 2).
- Acting on the verdicts (pruning/re-weighting detectors) — this round only
  *measures*; the user decides cuts after reading the report.

## Deliverables in the morning

- `findings_scanner_eval.md` — the scorecard report (primary).
- `scanner_eval/detectors.csv`, `scanner_eval/signals.csv`, Phase-3 backtest
  CSV(s) — drill-down.
- `progress.md` wrap-up entry.
- All new code committed per-task on the working branch (NOT merged to main).
