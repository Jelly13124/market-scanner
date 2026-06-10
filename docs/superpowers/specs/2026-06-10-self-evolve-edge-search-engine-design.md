# Self-Evolve as a Real Edge-Search Engine (B+C) — Design

**Date:** 2026-06-10
**Status:** approved (design greenlit; spec pending user review → writing-plans)
**Sub-project:** B+C (of the 4-track roadmap: A clock ✅ / **B+C edge-search engine** / D research tool)

## Goal

Turn the self-evolve factor engine from a slow toy into a fast, well-fed search
engine: (B) make a backtest iteration cost **seconds, not ~17 minutes**, so the
LLM proposer can run hundreds of rounds; (C) widen the factor library from an
effective **3** factors to **11** academically-backed, point-in-time-backtestable
factors so there is real raw material for an edge to be found.

The honest frame (unchanged): this searches a space more thoroughly and broadly;
it does not manufacture edge. The held-out test sample + the live paper
forward-test (sub-project A) remain the only honest judges. More factors also
raise overfitting risk — mitigated by single-hypothesis rounds, keep/rollback
guardrails, the untouched test sample, and the forward-test.

## Findings that shaped this design (verified in code)

1. **The backtest re-computes immutable factor values every iteration.**
   `factors._compute_one(bundle, asof, config)` runs per (ticker × rebalance ×
   iteration); bundles never change across iterations and most config deltas only
   change weights, so the per-(ticker, asof, lookback) factor values are identical
   round to round. Recomputing them is the ~17 min/iteration cost. → **Part B**.
2. **Two of the five existing factors are silently inert.** `metrics_history` is
   populated only by `fetch_financials_history` (yfinance), which sets
   `gross_margin / operating_margin / net_margin / revenue_growth /
   earnings_growth` — **not** `price_to_earnings_ratio` or `return_on_equity`. So
   the existing `value` (E/P) and `quality` (ROE) factors are always `None`
   (neutral). The prior self-evolve run effectively optimized **3 price factors**.
   → **Part C-data fixes this.**
3. **`total_assets` is available but not in the bundle.** It is fetched elsewhere
   via `src.tools.line_items.search_line_items(ticker, [...], period="annual")`
   (yfinance, free, already used by the agents) — just never wired into the
   self-evolve bundles. → **Part C-data adds a line-items enrich.**

## The 11 factors

`FACTOR_KEYS` (in `config.py`) is the single source of truth; the z-score matrix,
composite, weighting, and selection in `strategy_gen.py` all iterate it generically
(`for f in FACTOR_KEYS`). Adding a factor = add its key + compute it in
`factors.py` + give it a default weight + an `ADJUSTABLE` entry. The cache (Part B)
covers new factors automatically.

| # | factor | formula (as-of D) | dir | source | paper |
|---|---|---|---|---|---|
| 1 | momentum | close[D−21d]/close[D−mom_days]−1 | + | OHLCV (have) | Jegadeesh-Titman 1993 |
| 2 | reversal | −(close[D]/close[D−rev_days]−1) | + | OHLCV (have) | Jegadeesh 1990 |
| 3 | low_vol | −pstdev(daily rets, vol_days) | + | OHLCV (have) | Ang et al. 2006 |
| 4 | **max_lottery** | −max(daily ret over last `max_days`≈21) | + | OHLCV | Bali-Cakici-Whitelaw 2011 |
| 5 | **high_52w** | close[D] / max(close over `hi_days`≈252) | + | OHLCV | George-Hwang 2004 |
| 6 | **resid_mom** | momentum of returns residualized vs the universe-average return over the formation window | + | OHLCV | Blitz-Huij-Martens 2011 |
| 7 | **turnover** | −avg(volume/shares or volume trend) over `to_days` | + | OHLCV+vol | Datar-Naik-Radcliffe 1998 |
| 8 | **value** (real) | E/P = EPS_lagged / close[D] (or B/P) | + | line-items EPS + price | Fama-French HML |
| 9 | **gross_prof** | gross_profit / total_assets (Novy-Marx); fallback `gross_margin` (already populated) | + | line-items / metrics | Novy-Marx 2013 |
| 10 | **asset_growth** | −(total_assets_t / total_assets_{t−1} − 1) | + | line-items (2 yrs) | Cooper-Gulen-Schill 2008 (FF5 CMA) |
| 11 | **quality** (real ROE) | net_income / book_equity | + | line-items | — |

Notes:
- "dir +" means: higher factor value → higher expected return AFTER the sign in the
  formula (e.g. `max_lottery` and `asset_growth` carry a leading `−` so the
  cross-sectional z-score is "more is better", consistent with the composite).
- `resid_mom` market proxy = the cross-sectional mean return of the in-universe
  names over the formation window (a 1-factor market model from the bundles
  themselves — no extra data dependency). It is the heaviest factor; the cache
  makes it affordable.
- `gross_prof`: prefer true gross-profit/assets from line-items; if the line-items
  fetch lacks the COGS/gross-profit fields for a name, fall back to the populated
  `gross_margin`. Documented per-name fallback, never a hard failure.

## Part B — factor-value cache (the speed win)

- `compute_factors(bundles, asof, config, *, cache=None)` and the per-ticker
  `_compute_one(..., cache=None)` accept an optional cache dict.
- **Key per factor:** `(ticker, asof, factor_name, lookback_for_that_factor)`.
  Price factors key on their own window (momentum_days / vol_days / reversal_days /
  max_days / hi_days / to_days / resid window); fundamental factors key on
  `(ticker, asof, factor_name)` (the 60-day availability lag is fixed). A different
  lookback ⇒ a different key ⇒ a clean recompute. **No-lookahead is preserved by
  construction** because `asof` is in the key and a cached value used only data ≤ D.
- `backtest(bundles, config, sample, *, cache=None)` threads the cache to
  `generate_holdings(..., cache=None)` → `compute_factors`. `evolve()` creates ONE
  cache and threads it through every iteration (bundles immutable for the whole run).
- Default `cache=None` ⇒ no caching ⇒ existing standalone calls/tests unchanged
  (purely additive seam).
- **Effect:** a weight-only delta = 100% cache hits = the iteration is just
  re-weighting/ranking (seconds). A single-lookback delta recomputes only that one
  factor. Target: ~17 min → seconds.
- **Load-bearing correctness test:** for the same `(ticker, asof, lookback)`, the
  cached value equals the freshly-computed value; a lookback change recomputes.

## Part C-data — line-items enrich for the bundle

- New enrich step (mirrors `fetch_financials_history`'s shape) that attaches a
  `line_items_history` to the bundle: a list of annual records, each with
  `report_period` + `total_assets`, `earnings_per_share`, `book_value_per_share`,
  `revenue`, `net_income`, and (if available) `gross_profit` / `cost_of_revenue`.
- Source: `src.tools.line_items.search_line_items(ticker, [...], period="annual",
  limit=10)` (yfinance, free, already used by the agents). Best-effort + guarded
  (never raises; a name with no statements simply has an empty list → its
  fundamental factors are `None` → neutral, exactly like today).
- **As-of lagging (no lookahead):** factors read the newest line-items record with
  `report_period ≤ asof − FUNDAMENTAL_AVAILABILITY_LAG_DAYS (60d)` — the same
  `_latest_lagged_metric` discipline already proven for metrics_history.
- Wired into `build_bundles(..., enrich=True)` as an additional guarded step (so a
  price-only/offline bundle is unaffected; tests use `SimpleNamespace` fakes).

## Sequencing (each part independently shippable)

1. **B (cache) first** — pure perf, no behavior change; ship + verify the speedup
   on the existing factors. Biggest leverage, lowest risk.
2. **C-data (line-items enrich)** — the fundamental data path + as-of lagging.
3. **C-factors** — add the 8 new/fixed factors (4 price/volume + 4 fundamental) to
   `FACTOR_KEYS` + `config` defaults + `ADJUSTABLE`; each cached, each no-lookahead.
4. A short offline self-evolve smoke proving iterations are now fast and the new
   factors participate (a delta on a new factor's weight changes holdings).

## No-lookahead discipline (load-bearing, unchanged)

Every new factor at rebalance D uses ONLY data ≤ D (prices) or fundamentals with
`report_period ≤ D − 60d`. Forward returns (the outcome) still use prices after D.
The cache cannot introduce lookahead (key includes `asof`). The loop still
backtests **train+val only**; the held-out **test** is read once, post-loop. These
existing invariants (std floor, signals/holdings never raise, metrics conventions)
are re-asserted by the existing suite plus the new tests.

## Testing (offline, deterministic)

- **Cache:** cached == fresh for same key; lookback change recomputes; a weight-only
  delta hits 100%; `compute_factors` is invoked once per distinct (ticker, asof,
  lookback) across a multi-rebalance backtest (assert call count, e.g. via a
  counter), not once per iteration.
- **Each new factor:** correct value on a small synthetic bundle; no-lookahead
  (a bar/record dated > D does not change the value); degenerate input → `None`,
  never raises.
- **Line-items enrich:** as-of lag excludes a too-recent record; missing statements
  → empty list → fundamental factors `None` (ticker kept, neutral).
- **Generic plumbing:** adding the keys to `FACTOR_KEYS` flows through z-score /
  composite / weights / `ADJUSTABLE` with no hardcoded factor name left behind.
- **Regression:** full `v2/self_evolve/` suite stays green; the existing
  no-lookahead + test-never-read invariant tests unchanged.
- The live DeepSeek proposer is exercised only via the CLI, not unit tests.

## Risks / honest caveats

- **Overfitting rises with 11 factors.** Mitigations: single-hypothesis rounds,
  keep/rollback guardrails (turnover ≤ base×1.5, val maxDD not worse > 5pp), the
  untouched test sample, and the live forward-test as final arbiter. A config that
  wins on val may still fail test/forward — a valid, money-saving result.
- **`resid_mom` is the heaviest factor** (a per-name residualization each rebalance);
  the cache makes it affordable, but if it dominates runtime even cached, it may be
  deferred to a second round without blocking the other 10.
- **Shallow fundamentals.** yfinance annual line items are coarse + reporting-lagged;
  the price/volume factors still carry most of the signal. Deep point-in-time
  fundamentals (paid) remain out of scope.
- **Searching a weak space.** Prior results show weak/unproven edge; B+C makes the
  search fast + broad but does not create edge. That is what A (the forward-test)
  is for.

## Out of scope

- `factor_evolved` joining the prod paper forward-test unattended — happens AFTER
  B (its bundle build becomes affordable); already gated out via `PAPER_SLEEVES`.
- A Lab panel to launch/watch evolution runs (fast-follow).
- Deep/paid point-in-time fundamentals; intraday; the scanner-config plugin.
