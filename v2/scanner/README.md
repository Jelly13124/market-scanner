# v2/scanner — Daily Market Scanner

Quant-only ticker selection. Runs a 7-detector pass + 5 quant signals over a
US-stock universe, ranks the Top-N by a 60/40 (event/quant) composite score.
No LLM, no LangGraph. Pure Python — typical NASDAQ-100 + S&P 500 scan in
3–6 min on a single laptop.

## Pipeline

```
universe (loader) ──► run_scan(benchmark_ticker=…) ──► ThreadPoolExecutor
                          │
                          ├─ pre-fetch benchmark (SPY/QQQ) once → ScanContext.benchmark_prices
                          │
                          └─ per-ticker worker:
                               ├─ N EventDetectors  ── any triggered?
                               │  (filtered by config.weights.enabled_detectors)
                               │                       └─ yes ──┐
                               └─ 5 quant Signals ◄────────────┘
                                    │
                                    └─ compute_composite ──► ScoredEntry
```

Failure isolation is total: a single detector or signal raising an exception
is logged + counted; the run continues. The benchmark pre-fetch is also
non-fatal — if it fails, IDAY falls back to raw (un-adjusted) values.

## Detectors (`v2/scanner/detectors/`)

All registered in `ALL_DETECTORS`; each ScannerConfig may filter the set
via `weights.enabled_detectors` (None = all).

| File | Fires when | Severity |
|---|---|---|
| `earnings.py` | Last filing ≤ 5 biz-days old AND BEAT/MISS | z of EPS surprise % vs trailing 4Q std |
| `insider.py` | ≥3 distinct insiders same direction in 30d, OR single trade > 1% market cap | z of recent gross vs monthly-baseline std (M-coded option exercises map to 0) |
| `volume_anomaly.py` | Volume z ≥ 2.5 **AND** \|today_ret\| < 1.5% (anti-gate) | z_volume signed by return direction. The anti-gate carves out Wyckoff stopping/distribution; the price-moves-AND-volume case is now owned by `intraday_move`. Stable `.name = "price_volume_anomaly"` for DB row backward-compat. |
| `news_sentiment.py` | ≥3 scored articles in 7d AND ≥10 baseline articles | z of 7d polarity mean shift vs 90d baseline. Scheduled for removal once LLM agents pick up sentiment via web search; kept in registry but transitionally under-weighted (default mult 0.50). |
| `intraday_move.py` | Outsized intraday return / overnight gap / range — applied to **benchmark-adjusted** values when `ScanContext.benchmark_prices` is set | z of cvo / gap / range vs trailing window (also adjusted). Range stays raw — volatility is not a market-relative quantity. |
| `breakout_52w.py` | First-day close above trailing 52-week high (or below low) | Categorical magnitude ~2.0 |
| `analyst_rating.py` | Net upgrade z ≥ 2.0 (action flow only — `gap_hit` removed M9.c.1 because Wall St consensus is structurally bullish) | net_z |

### Std floors (load-bearing — see `findings.md`)

Every detector that takes a z-score has a hard std floor. Without them,
ultra-stable baselines (e.g. four identical EPS surprises, or all-M-code
insider history mapping to zero shares) collapse the denominator and z
explodes by 10+ orders of magnitude. Floors:

| Detector | Floor |
|---|---|
| earnings | 0.05 (5% of EPS estimate) |
| insider | `max(mean * 0.10, $1000)` |
| volume_anomaly | `mean * 0.10` |
| news (polarity) | 0.10 |
| intraday_move (cvo/gap/range) | 0.005 |
| analyst_rating (action score) | 0.5 weight-points |
| high_breakout (daily-return std) | 0.005 (50 bps) — `max(returns.std(ddof=1), 0.005)` |

Below the floor, the detector falls back to the categorical "trigger fired,
baseline uninformative" magnitude (typically 2.0–2.5).

### Benchmark-relative IDAY

`IntradayMoveDetector` reads `ScanContext.benchmark_prices` (SPY for sp500/
russell3000/all_us, QQQ for nasdaq100; selected per-config in
`scanner_service._run_phase`). The runner pre-fetches the benchmark series
once via `clients[0]` before the worker pool starts and shares the same
list reference into every per-ticker context.

For each historical bar AND today's bar, the detector subtracts
`(bench.close/bench.open - 1)` and `(bench.open/prev_bench.close - 1)`
from the ticker's cvo and gap before z-scoring. This way a stock that
just tracks the market on a -2% NDX day doesn't trigger IDAY — only
genuinely idiosyncratic moves do. Range stays raw.

If the benchmark fetch fails or returns <30 bars, `benchmark_prices` is
left None and IDAY transparently uses raw values (preserves pre-feature
behavior). Components surface both `raw_cvo` / `raw_gap` and
`adjusted_cvo` / `adjusted_gap` plus a `benchmark_used: 0|1` flag for
debugging.

## Quant Signals (`v2/signals/`)

Run only on tickers that triggered ≥1 event. Each returns
`SignalResult(value ∈ [-1, +1])` mapped to a 0–100 sub-score by `scoring.py`.

| Signal | What it measures | Bullish when |
|---|---|---|
| `momentum.py` | 12-1 month return (skip last month to dodge reversal) | strong uptrend |
| `value.py` | Composite of P/E, P/B, P/S, FCF yield | cheap |
| `quality.py` | ROIC, ROE, op margin, gross margin | profitable + capital-efficient |
| `earnings_quality.py` | Revenue / earnings / FCF / EPS growth | growing across all 4 |
| `technical.py` | RSI(14) + close vs 50-day SMA | oversold + uptrend (or vice versa) |

Signals **never raise**. On missing data they return `value=0.0` plus a
`metadata["reason"]` explaining why. The runner isolates per-signal
exceptions anyway — but treat raises as a bug to investigate.

## Scoring (`scoring.py`)

```
mults              = weights.detector_severity_mult            # missing keys → 1.0
weighted_severity  = max(|t.severity_z| * mults.get(t.detector, 1.0))
event_score        = clip(weighted_severity / 5σ, 0, 1) * 100  # 0..100
quant_score        = weighted mean of (value + 1) / 2 * 100    # 0..100, weights renormalized
composite          = 0.60 * event_score + 0.40 * quant_score   # 0..100
event_severity     = max(|severity_z|)  RAW, used as tiebreaker at composite=100
direction          = sign of  Σ (t.severity_z * mults.get(t.detector, 1.0))
```

Per-detector severity multipliers come from `ScannerWeights.detector_severity_mult`
(JSON dict on `ScannerConfig.weights`). Missing entries default to 1.0
(neutral). Default values per detector live in `DETECTOR_METADATA` and
match academic priors (earnings 1.20 strongest PEAD, news 0.50 transitional
under-weight, intraday 1.10, analyst 0.90, etc. — see
`task_plan_scanner_v2.md` §4.2).

`event_severity` reports the **un-multiplied** raw max so the deterministic
tiebreaker at composite=100 stays stable across mult changes.

## Per-config detector picker

Each `ScannerConfig.weights` JSON may carry:
- `enabled_detectors: list[str] | null` — `null` (or missing) means all
  detectors registered in `ALL_DETECTORS` run. A non-null list filters the
  set in `scanner_service._run_phase` before `run_scan` is called. Empty
  list rejected at validation (`ScannerWeights` field validator).
- `detector_severity_mult: dict[str, float]` — per-detector severity
  multipliers, range [0.0, 5.0], unknown names rejected.

Surfaced to the UI via `GET /scanner/detectors` (returns `name`, `label`,
`default_mult`, `description` per detector — sourced from
`DETECTOR_METADATA` in `detectors/__init__.py`). The frontend dialog
renders one checkbox + slider per detector with a "Recommended Defaults"
preset button that fills the academic-prior values.

## Adding a new detector

1. Subclass `EventDetector` in `v2/scanner/detectors/new_thing.py`.
2. Implement `detect(ticker, end_date, fd, *, ctx) -> EventTrigger | None`.
   Return `EventTrigger(triggered=False, ...)` for "ran cleanly, nothing
   fired" — `None` means "no data, exclude this ticker entirely."
3. Apply a std floor on any z-score you compute. **No `or 1e-6` patterns.**
4. Add the class to `ALL_DETECTORS` in `detectors/__init__.py`.
5. Add an entry to `DETECTOR_METADATA` in the same file with `label`,
   `default_mult`, and `description`. Without this the picker UI shows
   the bare name and a "(no description registered)" fallback.
6. Unit test it in `v2/scanner/test_detectors.py` with a `MagicMock` FDClient.

## Adding a new quant signal

1. Subclass `BaseSignal` in `v2/signals/new_factor.py`. Set `name` to a
   short stable identifier.
2. Implement `compute(ticker, end_date, fd) -> SignalResult`. Map to
   `[-1, +1]` and **never raise** — return `value=0.0` + metadata when
   inputs are insufficient.
3. Add to `ALL_SIGNALS` in `v2/signals/__init__.py`.
4. Add a weight to `ScannerWeights.factor_weights` in
   `v2/scanner/models.py`. Renormalization handles it automatically.

## Universe refresh

Universes are bundled CSVs under `v2/scanner/universes/` to avoid a flaky
boot-time dependency on Wikipedia / iShares / NASDAQ Trader. They're
quarterly-refreshed manually:

```bash
python -m v2.scanner.universes.refresh_universes --kind sp500 --verbose
python -m v2.scanner.universes.refresh_universes --kind nasdaq100 --verbose
python -m v2.scanner.universes.refresh_universes --kind russell3000 --verbose
python -m v2.scanner.universes.refresh_universes --kind all_us --verbose
```

`_EXPECTED_SIZES` in that script will reject implausibly small fetches
(e.g. a 50-row S&P 500 means Wikipedia changed its layout — keep the
existing CSV until investigated).

## Live smoke tests

Network-touching tests are off by default. Enable with:

```powershell
$env:SCANNER_LIVE_TEST = "1"
pytest v2/scanner/test_live_smoke.py
```

Or the per-provider gates already in place:

```powershell
$env:FINANCIAL_DATASETS_API_KEY = "..."   # unlocks v2/data/test_client.py
$env:FINNHUB_API_KEY = "..."              # unlocks v2/data/test_finnhub_client.py
$env:EODHD_API_KEY = "..."                # unlocks v2/data/test_eodhd_client.py
```

## Debugging a scan

If a Top-N entry looks wrong:

1. Look at its `triggers` JSON — each `EventTrigger` carries
   `components` with the raw inputs that produced the severity.
2. Suspiciously large `|severity_z|` (> 10): check that detector's std
   floor is firing. Grep for `sigma_floor` / `_std_floor` in the relevant detector.
3. IDAY firing on a market-moving day across many tickers: check
   `components.benchmark_used` — should be 1.0 on nasdaq100/sp500 scans.
   If 0.0, the runner couldn't fetch SPY/QQQ; check uvicorn log for
   `Benchmark … fetch failed` or `returned only N bars`.
4. Way too many triggers per scan: temporarily drop one or more detectors
   via the config dialog's Detectors picker (uncheck → save → re-run).
   `weights.enabled_detectors` filters `ALL_DETECTORS` at the
   `scanner_service._run_phase` boundary.
5. `quant_score` = None: no signal ran (likely all signals returned
   data-missing). Check the `metadata.reason` in `SignalResult`.
6. Composite > 95 but all triggers small: probably ties at the 5σ clip.
   `event_severity` (raw max |z|) breaks ties deterministically.

## Forward-looking work

See `task_plan_scanner_v2.md` for the planned 8-detector redesign. As of
2026-05-15, P0 of that plan (SPY-relative IDAY, volume anomaly slim,
per-detector severity weights) is shipped. P1+ remaining: estimate_revision,
multi-horizon breakout, insider asymmetric, bollinger squeeze, news
removal once the LLM agent layer takes over sentiment.
