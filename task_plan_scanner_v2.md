# Scanner v2 — 8 Trigger Redesign

**Status**: design / partial implementation (see "Implementation status" below)
**Date**: 2026-05-15
**Supersedes**: current 7 detectors in `v2/scanner/detectors/` after M9.c.1 hot-fix
**Owner**: Jerry
**Read first**: `CLAUDE.md` (project invariants — std floors, None vs triggered=False, per-worker DataClient, anaconda Python)

---

## Implementation status (as of 2026-05-15)

| Section | Status | Notes |
|---|---|---|
| §3.1 earnings_surprise (UNCHANGED) | ✅ | No code change |
| §3.2 insider_action (asymmetric refactor) | ⏳ pending | Deferred — current insider runs reasonably |
| §3.3 volume_anomaly slim (drop return-z, add anti-gate) | ✅ **DONE** | `price_volume.py` → `volume_anomaly.py`, class renamed, `.name` kept for DB compat. UI label: PV → VOL |
| §3.4 intraday_move SPY-relative | ✅ **DONE** | Universe-aware benchmark (nasdaq100→QQQ, others→SPY) injected via `ScanContext.benchmark_prices` |
| §3.5 multi-horizon breakout | ✅ **DONE** | Replaced `breakout_52w.py`. Class `MultiHorizonBreakoutDetector`, `.name="breakout_52w"` kept for DB compat. 63/126/252 horizons additive (2.0 + 0.5 + 1.0). First-day rule per horizon. Bearish requires volume confirmation; bullish gets full severity always. UI label "Multi-Horizon Breakout" / badge "BREAK". |
| §3.6 analyst_rating (UNCHANGED post M9.c.1) | ✅ | M9.c.1 already removed `gap_hit` gate |
| §3.7 bollinger_squeeze (NEW) | ⏳ pending | Note: design needs first-day-entry gate before shipping |
| §3.8 estimate_revision (NEW) | ⚠️ **BLOCKED / UNREGISTERED 2026-05-15** | Class + tests retained, but removed from `ALL_DETECTORS`. Live probe showed yfinance's `eps_revisions` field doesn't follow rolling-count semantics: for AAPL/MSFT/TSLA on 2026-05-15, `upLast7days > upLast30days` — impossible if both are cumulative counts of distinct revision events. Most likely the columns are some sort of "current estimates above/below recent consensus" bias rather than event counts, which makes the detector fire 87/100 in earnings season. Replaced by M9.d (`target_price_change` detector with DB-backed snapshots — actually fits the user's intuitive "analyst raised target by X% in 7d" signal). |
| §4.1 multi-trigger corroboration mult | ⏳ pending | Wait until detector set stabilizes |
| §4.2 per-detector severity weight | ✅ **DONE** | Bundled with user-selectable-detector picker (separate feature shipped same day, see `progress.md` 2026-05-15). `weights.detector_severity_mult` JSON; missing keys → 1.0; range [0.0, 5.0] enforced |
| §4.3 combined event_score formula | ✅ **DONE** | `weighted_severity = max(abs(z) * mult)` drives event_score; `event_severity` (raw) preserved for tiebreaker |
| §5 remove news_sentiment_shift | ⏳ pending | DO NOT delete until LLM-agent web-search wired up; transitional under-weight (0.50) shipped via §4.2 |

Companion feature (not in original §3-§5 plan, shipped 2026-05-15):

- **User-selectable detectors per config** — `weights.enabled_detectors: list[str] | None` (None = all enabled). UI picker with checkbox + slider per detector + Recommended Defaults preset button. Backed by new `GET /scanner/detectors` endpoint and `DETECTOR_METADATA` registry in `v2/scanner/detectors/__init__.py`. Empty selection rejected at validation.

---

## 1. Motivation

Real-run analysis of the current 7-detector set (Run #14, 2026-05-15, nasdaq100, triggered=84/101) surfaced these problems:

| Problem | Detector(s) | Impact |
|---|---|---|
| Return z-score appears in two detectors → double counting | `price_volume_anomaly` + `intraday_move` | composite over-weights correlated signals |
| Symmetric buy/sell treatment | `insider_cluster` | sell signals are ~10x weaker than buy (Cohen-Malloy-Pomorski 2012); current treats them as equal |
| EODHD sentiment label quality | `news_sentiment_shift` | aggregates headlines without context; LLM agents at the analysis layer do better via web search |
| 52-week window too sparse | `breakout_52w` | 0-2 triggers/day on nasdaq100, contributes ~zero to watchlist |
| No "setup" detector | (all 7) | all current triggers fire on action, none captures pre-move consolidation |

The redesign moves to **8 detectors** — swaps in higher-quality, orthogonal triggers, fixes overlap / asymmetry / sparsity / data-quality issues, and adds analyst **estimate revisions** (Stickel 1991 — leads earnings surprises by weeks). All within the existing data budget (EODHD $20/mo + Finnhub free + yfinance free).

---

## 2. Target trigger set

| # | name | UI label | dimension captured | data source | severity weight |
|---|---|---|---|---|---|
| 1 | `earnings_surprise` | EARN | financial reporting event | Finnhub | **1.20** |
| 2 | `insider_action` | INSDR | informed trading (asymmetric) | Finnhub | **1.00** |
| 3 | `volume_anomaly` | VOL | institutional footprint (volume-only) | EODHD | **0.90** |
| 4 | `intraday_move` | IDAY | market action (SPY-relative) | EODHD + yfinance `^SPY` | **1.10** |
| 5 | `breakout_multi_horizon` | BREAK | technical breakout (63/126/252d) | EODHD | **1.00** |
| 6 | `analyst_rating` | ANLY | sell-side opinion (rating actions) | yfinance | **0.90** |
| 7 | `bollinger_squeeze` | SQZ | pre-move consolidation setup | EODHD | **0.80** |
| 8 | `estimate_revision` | EREV | EPS consensus revision pre-earnings | yfinance | **1.10** |

**Information dimensions** (all orthogonal): financials · informed trading · volume · price action · trend · sell-side rating · setup · forward earnings expectations.
**Sentiment dimension** → moved to LLM agent layer via web search; no longer a scanner trigger.

**Severity weights** are quality-of-signal multipliers applied before max-takes-all in event_score. See §4.2 for rationale.

---

## 3. Per-trigger specifications

### 3.1 `earnings_surprise` — UNCHANGED

Current implementation in `v2/scanner/detectors/earnings.py` is correct. No code change.

- Trigger: latest filing within 5 business days AND label ∈ {BEAT, MISS}
- Severity: z-score of current surprise vs trailing 4 quarters, std floor 5%, fallback z = ±2.0
- Direction: BEAT → bullish, MISS → bearish

### 3.2 `insider_action` — REFACTOR `insider_cluster`

Rename detector class: `InsiderClusterDetector` → `InsiderActionDetector`. Keep file at `v2/scanner/detectors/insider.py`. Keep stable name attribute `"insider_cluster"` for backward-compat with existing DB rows, OR migrate — see §6.

**Asymmetric triggers:**

| Direction | Cluster threshold | Single-trade threshold | severity multiplier |
|---|---|---|---|
| Buy (bullish) | **≥ 2 insiders** same direction | **\|x\| ≥ $250,000** AND `transactionCode = "P"` | **× 1.3** |
| Sell (bearish) | **≥ 4 insiders** same direction | **\|x\| ≥ 1% market cap** | **× 0.7** |

Constructor params:
```python
__init__(
    self,
    *,
    cluster_window_days: int = 30,
    cluster_min_buyers: int = 2,
    cluster_min_sellers: int = 4,
    single_buy_dollar_threshold: float = 250_000.0,
    single_sell_mc_pct: float = 0.01,
    history_days: int = 365,
    fetch_limit: int = 1000,
    buy_severity_mult: float = 1.3,
    sell_severity_mult: float = 0.7,
)
```

**Implementation notes:**
- `transactionCode = "P"` (open-market purchase) is the high-conviction signal — only this code qualifies for the single-buy path
- Existing M/A/D/F → 0 shares mapping (M6.b) **must stay** — option exercises shouldn't count as cluster members
- z-score baseline and std floor logic unchanged from current implementation
- The two thresholds (cluster_min_buyers=2 vs cluster_min_sellers=4) reflect the empirical asymmetry, not a typo

**Components additions:**
```python
"buy_count": float(len(buyers)),
"sell_count": float(len(sellers)),
"biggest_buy_dollar": float(biggest_buy_abs),
"biggest_sell_dollar": float(biggest_sell_abs),
"direction_path": "cluster" | "single_buy" | "single_sell",  # which path triggered
```

### 3.3 `volume_anomaly` — SLIM `price_volume_anomaly`

Rename `PriceVolumeAnomalyDetector` → `VolumeAnomalyDetector`. File: `v2/scanner/detectors/price_volume.py` → `v2/scanner/detectors/volume_anomaly.py`. Name attribute: `"price_volume_anomaly"` → `"volume_anomaly"`.

**Why**: return z-score is mathematically `gap + close_vs_open`, both already covered by `intraday_move`. Removing it eliminates double-counting in composite. The unique signal kept is volume z-score (Wyckoff stopping volume / distribution day pattern).

**Trigger:**
- `z_vol ≥ 2.5` (volume z-score against 20-day trailing mean)
- AND `|close-to-close return| < 1.5%` (the **anti-gate** — IDAY handles the price-moves-and-volume case; this detector specifically captures price-flat-but-volume-anomalous)

**Severity:**
- `severity_mag = z_vol`
- Sign by today's return direction: `+1e-4 < ret → bullish`, `ret < -1e-4 → bearish`, else neutral
- std floor on volume: `max(z_vol_std, 0.10 * vol_mean)` (unchanged from current)

Constructor:
```python
__init__(
    self,
    *,
    lookback_days: int = 60,
    volume_window: int = 20,
    volume_z_threshold: float = 2.5,
    return_max_pct: float = 0.015,    # NEW: only fire when price didn't move
)
```

Delete the entire `return z-score` branch from the current detector.

### 3.4 `intraday_move` — ENHANCE with SPY-relative

Keep existing `IntradayMoveDetector` structure. Add SPY-relative adjustment to gap and close-vs-open (NOT range — volatility isn't a market-relative quantity).

**SPY fetch:**
- Fetch `^SPY` (or `SPY`) OHLC once per scan, cache in `ScanContext` to share across all tickers in the run
- Provider: yfinance (free) — index/ETF ticker; works reliably with `Ticker("SPY").history(period="6mo")`
- Cache key in `ScanContext`: `spy_prices: list[Price] | None`
- Loader function: `v2/scanner/runner.py` populates this once before the thread pool starts
- Fallback: if SPY fetch fails, skip SPY adjustment (use raw values), log warning once

**Adjusted formulas:**
```python
spy_cvo = spy_close / spy_open - 1
spy_gap = spy_open / spy_prev_close - 1

adjusted_cvo = (close / open - 1) - spy_cvo
adjusted_gap = (open / prev_close - 1) - spy_gap
# range stays raw: (high - low) / open
```

**z-score computation** runs on adjusted values, not raw. Trailing window for the z-distribution should also use adjusted values (so the comparison is apples-to-apples).

**Components additions:**
```python
"spy_cvo": float(spy_cvo),
"spy_gap": float(spy_gap),
"raw_cvo": float(raw_cvo),         # pre-adjustment, for debugging
"raw_gap": float(raw_gap),
"adjusted_cvo": float(adjusted_cvo),
"adjusted_gap": float(adjusted_gap),
```

**Thresholds unchanged** (still 4% / 3% / 6% absolute or z ≥ 2.5), but apply to **adjusted** values.

### 3.5 `breakout_multi_horizon` — REPLACE `breakout_52w`

Rename `FiftyTwoWeekBreakoutDetector` → `MultiHorizonBreakoutDetector`. File: `v2/scanner/detectors/breakout_52w.py` → `v2/scanner/detectors/breakout_multi_horizon.py`. Name attribute: `"breakout_52w"` → `"breakout_multi_horizon"`.

**Three horizons checked simultaneously:**

| Horizon | Trading days | Base severity contribution |
|---|---|---|
| Short | 63 (3 months) | +2.0 (base on hit) |
| Medium | 126 (6 months) | +0.5 (added if also hit) |
| Long | 252 (52 weeks) | +1.0 (added if also hit) |

**"First-day" definition** (kept from current): yesterday's close was inside the range, today's close clears it. Prevents firing every day a stock stays above the level.

**Severity examples:**
- Only 63d high broken: severity = +2.0
- 63d + 126d highs broken (same day): severity = +2.5
- All three highs broken: severity = +3.5 (rare but high-quality signal)

**Low side (bearish):** mirror logic, **BUT** require today's volume z-score ≥ 1.5 (un-confirmed breakdowns are often fake-outs). If volume not confirmed: severity halved (× 0.5).

**Direction:** highs → bullish, lows → bearish. Never both at once.

Constructor:
```python
__init__(
    self,
    *,
    lookback_days: int = 380,           # ≈ 270 trading days, enough buffer
    horizons: tuple[int, ...] = (63, 126, 252),
    horizon_severity_contrib: tuple[float, ...] = (2.0, 0.5, 1.0),  # parallel to horizons
    volume_confirm_z: float = 1.5,
    volume_window: int = 20,
    low_unconfirmed_mult: float = 0.5,
)
```

**Components:**
```python
"horizons_broken": list[int],          # e.g. [63] or [63, 126, 252]
"breakout_level_63d": float | None,
"breakout_level_126d": float | None,
"breakout_level_252d": float | None,
"volume_z_today": float,
"volume_confirmed": bool,
"breakout_pct": float,                  # how far past 63d level (closest)
```

Expected trigger rate on nasdaq100: 5-15 / day (compared to 0-2 / day for the old 52w-only version).

### 3.6 `analyst_rating` — UNCHANGED (post M9.c.1)

`AnalystRatingDetector` already had the `gap_hit` gate removed in M9.c.1. No further changes in this redesign.

M9.d (target_median 5-day change via DB snapshot) remains in `task_plan.md` as deferred work.

### 3.7 `bollinger_squeeze` — NEW

New file: `v2/scanner/detectors/bollinger_squeeze.py`.

**Concept**: detects volatility compression — when 20-day Bollinger band width hits a low percentile of its own 6-month distribution, the stock is statistically primed for a directional move (~80% break out within 20 trading days per Bollinger's own empirical work).

**Trigger:**
- Compute 20-day Bollinger band: `mid = MA(close, 20)`, `upper = mid + 2σ`, `lower = mid - 2σ`
- Bandwidth: `bw = (upper - lower) / mid`
- Compute today's bandwidth percentile rank within the past 126 days of bandwidths
- **Fire if percentile ≤ 10**

**Severity:** fixed magnitude **2.0** when triggered. Squeezes are statistical states, not directional — severity reflects "we detected one", not "how strong".

**Direction:** **neutral** (a squeeze doesn't predict direction, only magnitude of imminent move). The downstream LLM agent / user is responsible for picking direction.

**Why neutral**: includes the stock in watchlist but doesn't bias the composite toward bull/bear. composite direction logic sums signed severities — neutral contributes 0, so a SQZ-only ticker shows up as "needs investigation" without a bull/bear stance.

Constructor:
```python
__init__(
    self,
    *,
    lookback_days: int = 200,           # need 126 + 20 + buffer
    bb_window: int = 20,
    bb_std_mult: float = 2.0,
    percentile_window: int = 126,
    percentile_threshold: float = 0.10, # bottom decile = squeeze
    severity: float = 2.0,
)
```

**Components:**
```python
"bandwidth_today": float,
"bandwidth_percentile": float,           # 0.0 to 1.0
"bb_mid": float,
"bb_upper": float,
"bb_lower": float,
"days_in_squeeze": int,                  # consecutive days below threshold
```

**No std floor needed** — percentile rank is bounded [0, 1] by construction.

**Reason example**: `"Bollinger bandwidth 4.2% (pctl=7th in 126d), 3 days in squeeze"`

Expected trigger rate on nasdaq100: 3-10 / day.

### 3.8 `estimate_revision` — NEW

New file: `v2/scanner/detectors/estimate_revision.py`.

**Concept**: tracks analyst EPS estimate revisions for the next quarter / next fiscal year. Stickel 1991 ("Common Stock Returns Surrounding Earnings Forecast Revisions") and Womack 1996 both find that **estimate revisions lead price reactions by 1-4 weeks** — stronger and earlier signal than rating word changes.

**Data source**: yfinance `Ticker.eps_revisions` — returns a DataFrame with rows per forecast period (`0q`, `+1q`, `0y`, `+1y`) and columns:
- `upLast7days`, `downLast7days`
- `upLast30days`, `downLast30days`

Add to DataClient Protocol: `get_estimate_revisions(ticker, asof_date) -> EstimateRevisions | None`.
Add to `v2/data/models.py`:
```python
class EstimateRevisions(BaseModel):
    ticker: str
    asof_date: str
    period: str                    # primary period analyzed (default "0q")
    up_last_7d: int
    down_last_7d: int
    up_last_30d: int
    down_last_30d: int
    total_analysts: int | None     # if available
```

**Trigger:**
- Use `period = "0q"` (current quarter, most actionable) by default
- `net_7d = up_last_7d - down_last_7d`
- `total_7d = up_last_7d + down_last_7d`
- Fire if `total_7d >= 3` AND `abs(net_7d) >= 2`

**Severity:**
- `severity_mag = max(abs(net_7d) / 0.7, severity_floor)` (so net=5 → severity ≈ 7.1, capped by 5σ clip in scoring)
- Sign: `+1` if `net_7d > 0` else `-1`
- Symmetric — unlike insider, upward and downward estimate revisions are equally informative (Womack 1996, Stickel 1991)

Constructor:
```python
__init__(
    self,
    *,
    period: str = "0q",
    min_total_revisions: int = 3,
    net_threshold: int = 2,
    severity_scale: float = 0.7,         # net / scale → severity_z
    severity_floor: float = 2.0,
)
```

**Components:**
```python
"period": str,
"up_7d": int,
"down_7d": int,
"net_7d": int,
"up_30d": int,
"down_30d": int,
"net_30d": int,
"total_7d": int,
```

**Direction:** symmetric — net positive → bullish, net negative → bearish, exact zero with high total → neutral (rare).

**Reason example**: `"4 EPS estimates raised vs 1 cut for 0q (last 7d); net=+3"`

**Handling missing data**: yfinance can return empty / missing eps_revisions for low-coverage names. In that case return `None` (data missing, exclude from stats), NOT `triggered=False` (which would imply "ran cleanly, nothing fired").

**Relationship to `analyst_rating` and M9.d**:
- `analyst_rating` = rating *word* changes (Buy/Sell/Hold labels)
- `estimate_revision` (this) = EPS *number* forecast changes (count of analysts revising)
- M9.d (deferred) = target *price* changes (median target $ value, needs DB snapshot)

All three are independent — same analyst may do any combination (e.g., upgrade rating without changing EPS estimate, or revise EPS without changing rating).

Expected trigger rate on nasdaq100: 5-15 / day around earnings season (mid-quarter sees fewer revisions).

---

## 4. Composite scoring changes

File: `v2/scanner/scoring.py` + `v2/scanner/models.py` (`ScannerWeights`).

### 4.1 Multi-trigger corroboration reward

Current `event_score = max(|severity_z|) / 5σ × 100` ignores the number of triggers. New formula rewards corroboration:

```python
n_triggered = len(triggered)            # how many of 8 detectors fired
extra = max(0, n_triggered - 1)
corroboration_mult = 1.0 + 0.15 * min(extra, 2)   # cap at 1.30
# i.e. 1 trigger → 1.00, 2 triggers → 1.15, 3 triggers → 1.30, 4+ triggers → 1.30 (capped)
```

Cap at 2 extra (not 7 extra) prevents a ticker that triggers 5 weak signals from outranking a ticker triggering 1 strong signal.

### 4.2 Per-detector severity weight (NEW)

Add a quality-of-signal multiplier applied to each detector's raw `severity_z` BEFORE the max-takes-all operation. Lives in `ScannerWeights.detector_severity_mult`:

```python
class ScannerWeights(BaseModel):
    ...
    detector_severity_mult: dict[str, float] = Field(default_factory=lambda: {
        "earnings_surprise":       1.20,    # PEAD strongest empirical anomaly
        "insider_cluster":         1.00,    # internal asymmetry already (buy×1.3, sell×0.7)
        "volume_anomaly":          0.90,    # narrow scenario but clean when fires
        "intraday_move":           1.10,    # SPY-adjusted = cleaner real-flow signal
        "breakout_multi_horizon":  1.00,    # high (strong) + low (ambiguous) averaged
        "analyst_rating":          0.90,    # structurally lagging
        "bollinger_squeeze":       0.80,    # setup not event, neutral direction
        "estimate_revision":       1.10,    # Stickel 1991 — leads rating actions
    })
```

(Detector `.name` strings kept as their pre-rename originals to avoid DB migration — see §6.)

### 4.3 Combined event_score formula

```python
weighted_severities = [
    abs(t.severity_z) * weights.detector_severity_mult.get(t.detector, 1.0)
    for t in triggered
]
max_weighted_severity = max(weighted_severities) if weighted_severities else 0.0

event_score = clip(max_weighted_severity / 5.0, 0.0, 1.0) * 100.0 * corroboration_mult
event_score = clip(event_score, 0.0, 100.0)
```

Direction logic (`_direction_from`) also uses weighted severity sum:
```python
weighted_sum = sum(
    t.severity_z * weights.detector_severity_mult.get(t.detector, 1.0)
    for t in triggered
)
# > +1e-6 → bullish, < -1e-6 → bearish, else neutral
```

**No change to quant_score or event/quant weight split (0.6 / 0.4).**

### 4.4 Backward compat

`detector_severity_mult` has a default value, and `.get(name, 1.0)` means any unmapped detector silently gets multiplier 1.0 — no breakage when adding/removing detectors. Old `WatchlistEntry` DB rows with original severity_z values are unaffected (re-computation is not retroactive; new scoring only applies to new runs).

---

## 5. Removed: `news_sentiment_shift`

**Remove from `ALL_DETECTORS` tuple** in `v2/scanner/detectors/__init__.py`. The file `news_sentiment.py` and its tests can stay (git history is enough; deleting is optional cleanup).

**Rationale:**
1. EODHD aggregate sentiment is structurally noisy (headline-level, no source authority)
2. LLM agents at the analysis layer already do sentiment qualitatively (`src/agents/news_sentiment.py`)
3. Adding web search to those agents (separately, see §10) gives much higher-quality sentiment than any precomputed label

**Keep** `fd.get_news(...)` in `DataClient` Protocol and `CompositeClient.news_backend = eodhd`. LLM agents may still consume structured news; only the scanner-level trigger is removed.

**UI**: `_fmt_triggers` in `v2/scanner/__main__.py` — remove `"news_sentiment_shift": "NEWS"` from the `short` dict. Existing DB rows with NEWS labels stay valid (historical records).

---

## 6. Migration phases

> **Status note** (2026-05-15): the plan was re-sequenced from the original
> P0/P1/P2 grouping after a real scan showed IDAY was the dominant noise
> source on volatile market days. We shipped a narrowed "Path B" first
> (§3.4 + §3.3) plus the §4.2/§4.3 scoring changes bundled with the
> user-selectable-detector picker. The remaining phases below are the
> updated forward-looking plan.

**Phase P0** — ✅ shipped 2026-05-15 (Path B + picker):
- ✅ §3.4 intraday_move SPY-relative
- ✅ §3.3 volume_anomaly (slim)
- ✅ §4.2/4.3 per-detector severity weight + weighted event_score
- ✅ User-selectable detectors per ScannerConfig (companion feature)

**Phase P1** — partial 2026-05-15:
- ✅ §3.5 breakout_multi_horizon (replace 52w) — 0-2/day → 5-15/day expected
- ⚠️ §3.8 estimate_revision — shipped but UNREGISTERED same day after field-semantics issue (see §3.8 row above). Replaced by M9.d.

**Phase P1b** — in progress 2026-05-15:
- M9.d `target_price_change` — DB-backed analyst target_median 5-day change detector (the signal we actually intended). Requires alembic migration + snapshot writer + new detector + tests. Bootstrap: needs ≥2 daily snapshots so won't fire usefully until day 2+.

**Phase P2**:
- §3.2 insider_action (asymmetric refactor)
- §3.7 bollinger_squeeze (new) — REQUIRES first-day-entry gate (see §3.7 design note)
- §4.1 composite corroboration reward — wait until detector set stabilizes

**Phase P3** — only after agent layer ready:
- §5 remove news_sentiment_shift (currently transitionally under-weighted to 0.50)
- M9.d analyst target_median 5d change via DB snapshot

**Why P2 splits squeeze and estimate_revision**: both are new detectors with new components, can ship together in one PR. Both use existing data sources (EODHD prices for squeeze; yfinance for revisions) so no infra changes.

**Stable names backward-compat**: keep detector `.name` attributes for renamed detectors as a config option — historical `WatchlistEntry` rows reference old names. Simplest path: when renaming `insider_cluster` → `insider_action` etc., **migrate DB rows** with an alembic migration in the same PR, OR **keep old `.name`** strings and only rename the Python class/file. Recommendation: keep old `.name` strings to avoid migration complexity. Rename the class and file only.

---

## 7. CLAUDE.md compliance

All new/refactored detectors must honor the project invariants:

1. **Std floors on every z-score** — no `or 1e-6` patterns; use real floors (e.g. `max(std, 0.10 * mean)` for volume; `max(std, 0.005)` for daily returns; for bounded oscillators use bounded-distribution floors)
2. **Signals never raise** — on data issues return `EventTrigger(triggered=False, reason=...)`. Runner isolates exceptions but raises are bugs to investigate
3. **`None` vs `triggered=False`** — `None` means "exclude from stats"; `triggered=False` means "ran cleanly, nothing fired"
4. **Per-worker DataClient** — `^SPY` cache lives in `ScanContext` populated before pool start; do NOT create a module-level singleton
5. **Update `progress.md` after each milestone** via `planning-with-files` skill

Python interpreter for tests: `C:\Users\Jerry\anaconda3\python.exe`
Shell: PowerShell with `$env:PYTHONIOENCODING="utf-8"`

---

## 8. Testing requirements

**For each refactored or new detector**:

1. Base 4-pack: bullish trigger / bearish trigger / no-trigger-but-clean / no-data
2. Std floor regression test (CLAUDE.md M6.e hard rule)
3. `None` vs `triggered=False` distinction
4. Boundary tests (exact threshold value: triggers? doesn't?)

**Specific to each detector**:
- `insider_action`: separate buy-2-insiders / sell-4-insiders / single-P-trade-$300k / single-S-trade-1.5%-MC / mixed cluster (no trigger)
- `volume_anomaly`: high volume + high return (should NOT fire — IDAY's job) / high volume + flat return (SHOULD fire) / normal volume (no trigger)
- `intraday_move` SPY-relative: stock +5% on SPY +4% day → adjusted small → may not trigger / stock -3% on SPY +2% day → adjusted -5% → triggers
- `breakout_multi_horizon`: break only 63d / break 63d + 126d / break all three / break low unconfirmed (volume z=1.0, severity halved)
- `bollinger_squeeze`: bandwidth at 5th percentile → triggers / 50th → no / 5th but only 1 day → triggers (no min-duration gate)
- `estimate_revision`: net_7d=+3 total=4 → bullish trigger / net_7d=-3 → bearish / net_7d=0 high total → no trigger / yfinance returns empty → `None` (NOT triggered=False) / period="+1q" works

**Composite scoring test additions**:
- Per-detector severity multiplier: earnings_surprise z=+3 × 1.2 = 3.6 → event_score uses 3.6 not 3.0
- Bollinger squeeze (weight 0.8) z=2.0 → effective 1.6 → event_score lower than insider z=2.0 × 1.0
- Weighted direction sum: earnings_surprise +2 (×1.2=+2.4) + bollinger_squeeze 0 → bullish (sum positive)
- Unknown detector name → multiplier defaults to 1.0 (backward compat)

**Integration test** (`v2/scanner/test_runner.py`):
- Mock providers with 5 tickers + ^SPY data
- Verify SPY cache populated once, not per-ticker
- Verify all 7 detectors hit through `_scan_one_ticker`
- Verify composite corroboration mult applied correctly when 2+ detectors fire on same ticker

**Existing 63+ tests must remain green.** Tests for `news_sentiment_shift` may stay but their detector is no longer in `ALL_DETECTORS` — that's fine; tests can still exercise the class directly.

---

## 9. Files to change

| File | Change |
|---|---|
| `v2/scanner/detectors/__init__.py` | Update `ALL_DETECTORS` tuple; remove news_sentiment, rename imports |
| `v2/scanner/detectors/insider.py` | Refactor for asymmetric buy/sell |
| `v2/scanner/detectors/price_volume.py` → `volume_anomaly.py` | Rename file; slim to volume-only |
| `v2/scanner/detectors/intraday_move.py` | Add SPY-relative adjustment |
| `v2/scanner/detectors/breakout_52w.py` → `breakout_multi_horizon.py` | Rename file; multi-horizon logic |
| `v2/scanner/detectors/bollinger_squeeze.py` | NEW |
| `v2/scanner/detectors/estimate_revision.py` | NEW |
| `v2/data/protocol.py` | Add `get_estimate_revisions` method |
| `v2/data/models.py` | Add `EstimateRevisions` Pydantic model |
| `v2/data/yfinance_client.py` | Implement `get_estimate_revisions` via `Ticker.eps_revisions` |
| `v2/data/composite_client.py` | Route `get_estimate_revisions` to yfinance backend |
| `v2/scanner/scoring.py` | Multi-trigger corroboration mult + per-detector severity weight |
| `v2/scanner/models.py` | Add `spy_prices` field to `ScanContext`; add `detector_severity_mult` to `ScannerWeights` |
| `v2/scanner/runner.py` | Populate `ScanContext.spy_prices` once before pool start |
| `v2/scanner/__main__.py` | Update `_fmt_triggers` `short` dict (remove NEWS, add VOL/BREAK/SQZ) |
| `v2/data/yfinance_client.py` | Ensure `^SPY` or `SPY` works through `get_prices` (or add separate index method) |
| `v2/scanner/test_detectors.py` | New / refactored tests per §8 |
| `v2/scanner/test_runner.py` | SPY cache integration test, corroboration test |
| `task_plan.md` | Update milestone status (M9.e for this redesign batch) |
| `progress.md` | Per-phase entries as work completes |

---

## 10. Out of scope (future work, not in this redesign)

| Item | Why not now |
|---|---|
| Corporate actions (M&A / buyback / dividend changes) | 8-K parsing requires FD $200/mo or self-built NLP pipeline |
| Options unusual activity | No accessible data source under current budget |
| Sector relative strength | Finnhub `finnhubIndustry` not real GICS; sector mapping unreliable |
| Real GICS classification | Same data-source limitation |
| Short interest spike | Bi-weekly + 2-week-delayed reporting cadence; doesn't fit daily scanner |
| 10b5-1 plan flag in insider feed | Finnhub free tier doesn't expose the field; partial proxy via `transactionCode` ("P" = real signal) |
| Real-time intraday data | EODHD daily plan doesn't include intraday |
| Earnings post-drift sign attribution | Possible enhancement to `earnings_surprise`, deferred |
| VIX regime-adaptive thresholds | Free via yfinance `^VIX`, but not yet wired; ~0.5 day work, candidate for Phase P3 |

---

## 11. Sentiment moves to LLM agent layer

While not part of the scanner redesign itself, this redesign assumes sentiment analysis happens **downstream** in the agent layer. Audit checklist for `src/agents/`:

- `src/agents/news_sentiment.py` — confirm it reads news (via `tools/api.py`'s `get_company_news` or equivalent)
- Verify or add: web search tool integration. Anthropic Claude has native web search via tool-use; OpenAI supports it via function-calling
- Recommended: agents should have access to BOTH structured news (`fd.get_news(...)`) AND web search, choosing per-query
- Cost note: ~$1/scan day for 20 watchlist tickers × 5 searches × $0.01/search — negligible

This work is **separate from the scanner redesign** and can be done in parallel by a different PR. Not blocking on P0.

---

## 12. Success criteria

After P0 + P1 + P2 deployment, a daily nasdaq100 scan should show:

| Metric | Before redesign | Target after P0+P1+P2 |
|---|---|---|
| Triggered rate | 84/101 (83%) | 40-55% |
| Top-15 entries with single trigger | ~3/15 | <5/15 (more multi-trigger) |
| BREAK label in top 15 | 0/15 | 2-5/15 |
| EREV label in top 15 (earnings season) | n/a | 3-8/15 |
| EREV label in top 15 (mid-quarter) | n/a | 1-3/15 |
| ANLY \|severity_z\| max | +9 to +10 | ≤ ±4 (post-M9.c.1 already lower) |
| INSDR sell triggers w/ M-code | 0 (existing M6.b fix) | 0 |
| Composite score range top-20 | 84-91 (compressed) | 60-95 (more spread) |
| Detector with highest avg severity-weighted contribution | (any) | `earnings_surprise` (weight 1.20) when in season |

If P0 produces results outside these envelopes, that's a signal to re-tune before P1/P2.
