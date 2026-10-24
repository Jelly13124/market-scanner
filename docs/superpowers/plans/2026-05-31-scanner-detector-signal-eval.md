# Scanner detector/signal usefulness evaluation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Steps use `- [ ]` checkboxes. Fresh implementer subagent per task; two-stage
> review (spec-compliance then code-quality); for any detector/signal-touching
> task also run the scanner-invariant-reviewer.

**Goal:** Build an offline-tested evaluation system that scores each of the 13
detectors + 5 signals as USEFUL/USELESS/DATA-LIMITED across bull/bear/choppy
regimes, then run it overnight to produce `findings_scanner_eval.md`.

**Architecture:** New package code under `v2/scanner/eval/`. A `CachedAsOfClient`
(fetch-once, serve `≤asof` slices, hard no-lookahead) makes a full live sweep
CPU-bound. Three fail-soft phases: price scorecard (guaranteed) → event/
fundamental fill-in (best-effort, time-boxed) → full-replay confirmation
(bounded). Incremental report writing.

**Tech stack:** Python 3.13 (anaconda), numpy, pandas, yfinance, existing
`v2/data` clients + `v2/scanner` detectors/signals + `v2/backtesting`.

**Spec:** `docs/superpowers/specs/2026-05-31-scanner-detector-signal-eval-design.md`

---

## Constraints (paste into every implementer prompt)

- Python: `C:\Users\Jerry\anaconda3\python.exe`; tests via `-m pytest`; set
  `$env:PYTHONPATH="C:\Users\Jerry\Desktop\ai-hedge-fund"` and
  `$env:PYTHONIOENCODING="utf-8"`.
- Branch `feature/scanner-eval`. Commit per task, conventional message, **NO
  Co-Authored-By trailer; never --no-verify**. Explicit `git add <paths>` — never
  `git add -A`, never stage `.claude/settings.local.json`.
- **All subagents run on Opus 4.8** (`model: opus`). Per CLAUDE.md.
- Tests are **offline** — mock clients / synthetic series, no network. The only
  network use is the real overnight run (Wave E).
- Detector/signal invariants (CLAUDE.md): every z-score has a real std floor;
  signals never raise; `None` vs `EventTrigger(triggered=False)` distinct;
  per-worker DataClient. The eval must not violate these in any new detector
  interaction.
- After each task: append one line to `progress.md`.

---

## Wave A — Foundations (pure logic, offline)

### Task A1: Extend `evaluate_detector` with interestingness metrics

**Files:**
- Modify: `v2/scanner/eval/detector_ab.py`
- Test: `v2/scanner/test_eval_ab.py` (extend)

- [ ] **Step 1 — failing test.** Add to `TestEvaluateDetector`:
```python
def test_interestingness_metrics_present():
    out = evaluate_detector(
        fire_returns=[0.10, -0.08, 0.06],      # big moves, mixed sign
        baseline_returns=[0.01, -0.01, 0.00, 0.02],  # quiet
        horizon=5,
    )
    # existing signed keys still present
    assert "mean_fwd_return" in out and "t_stat" in out
    # new interestingness keys: |moves| of fired vs baseline
    assert out["abs_mean_fired"] == pytest.approx((0.10+0.08+0.06)/3)
    assert out["abs_mean_baseline"] == pytest.approx((0.01+0.01+0.00+0.02)/4)
    assert out["interestingness_diff"] == pytest.approx(
        out["abs_mean_fired"] - out["abs_mean_baseline"])
    # Welch t on the abs arrays; fired clearly > baseline → t>0
    assert out["interestingness_t"] > 0
```
- [ ] **Step 2** — run, expect FAIL (KeyError).
- [ ] **Step 3 — implement.** In `evaluate_detector`, after computing the signed
  block, add (reuse the existing Welch helper pattern):
```python
abs_fired = [abs(x) for x in fire_returns]
abs_base = [abs(x) for x in baseline_returns]
abs_mean_fired = float(np.mean(abs_fired)) if abs_fired else 0.0
abs_mean_baseline = float(np.mean(abs_base)) if abs_base else 0.0
interestingness_diff = abs_mean_fired - abs_mean_baseline
interestingness_t = 0.0
if len(abs_fired) >= 2 and len(abs_base) >= 2:
    vA = float(np.var(abs_fired, ddof=1)); vB = float(np.var(abs_base, ddof=1))
    denom = vA/len(abs_fired) + vB/len(abs_base)
    if denom > 0.0:
        interestingness_t = interestingness_diff / math.sqrt(denom)
```
  Add the 4 keys to the returned dict. Keep all existing keys/values unchanged.
- [ ] **Step 4** — run `v2/scanner/test_eval_ab.py` → PASS (old + new).
- [ ] **Step 5 — commit.** `feat(scanner-eval): add interestingness (abs-move vs random) metrics to evaluate_detector`

---

### Task A2: `CachedAsOfClient` + `TickerBundle` (keystone)

**Files:**
- Create: `v2/scanner/eval/cached_asof_client.py`
- Test: `v2/scanner/eval/test_cached_asof_client.py`

Background: detectors call `fd.get_prices(ticker, start, end)`, plus event
methods (`get_insider_trades`, `get_earnings`, `get_news`, `get_metrics`,
`get_company_facts` — confirm exact names from `v2/data/protocol.py`). The
client must satisfy that Protocol but serve only pre-fetched, `≤asof` data.

- [ ] **Step 1 — failing tests.** Key cases:
```python
def test_no_lookahead_prices():
    bundle = TickerBundle(ticker="X", prices=[_p("2024-01-01",10),_p("2024-01-02",11),_p("2024-01-03",12)])
    c = CachedAsOfClient(bundle); c.set_asof("2024-01-02")
    out = c.get_prices("X","2024-01-01","2024-12-31")  # caller asks far future
    assert [p.time for p in out] == ["2024-01-01","2024-01-02"]   # clamped to ≤asof

def test_fundamental_60d_lag():
    # a statement for period 2024-03-31 must NOT be visible at asof 2024-04-15
    bundle = TickerBundle(ticker="X", prices=[...], metrics_history=[_m(period="2024-03-31", roe=0.2)])
    c = CachedAsOfClient(bundle); c.set_asof("2024-04-15")
    assert c.get_metrics("X") is None or _no_2024Q1(c.get_metrics("X"))
    c.set_asof("2024-06-30")   # > 2024-03-31 + 60d
    assert _has_2024Q1(c.get_metrics("X"))

def test_empty_bundle_no_crash():
    c = CachedAsOfClient(TickerBundle(ticker="X", prices=[]))
    c.set_asof("2024-01-02")
    assert c.get_prices("X","2024-01-01","2024-01-02") == []
    assert c.get_earnings("X") in (None, [])
```
- [ ] **Step 2** — run, expect FAIL (module missing).
- [ ] **Step 3 — implement.**
```python
FUNDAMENTAL_AVAILABILITY_LAG_DAYS = 60

@dataclass
class TickerBundle:
    ticker: str
    prices: list                      # v2.data Price objects, time-ascending
    insider: list = field(default_factory=list)
    earnings: list = field(default_factory=list)
    news: list = field(default_factory=list)
    metrics_history: list = field(default_factory=list)   # period-stamped
    facts_history: list = field(default_factory=list)

class CachedAsOfClient:
    """DataClient-compatible, serves only pre-fetched data ≤ asof.
    set_asof() is a HARD ceiling; every accessor clamps regardless of args."""
    def __init__(self, bundle: TickerBundle):
        self._b = bundle
        self._asof: str | None = None
    def set_asof(self, date: str) -> None: self._asof = date
    def _ceil(self) -> str:
        if self._asof is None: raise RuntimeError("set_asof() before use")
        return self._asof
    def get_prices(self, ticker, start_date, end_date):
        hi = min(end_date, self._ceil())
        return [p for p in self._b.prices if start_date <= p.time <= hi]
    # event accessors: filter to record_date ≤ asof; for metrics/facts apply lag.
    def get_metrics(self, ticker, *a, **k):
        cutoff = _minus_days(self._ceil(), FUNDAMENTAL_AVAILABILITY_LAG_DAYS)
        avail = [m for m in self._b.metrics_history if _period_of(m) <= cutoff]
        return avail[-1] if avail else None
    # ... get_earnings/get_news/get_insider_trades/get_company_facts analogously,
    #     earnings & news & insider use ≤ asof (no lag); facts use the 60d lag.
    def close(self): pass
```
  Match the exact Protocol method names/signatures from `v2/data/protocol.py`.
  Use a tiny `_minus_days(iso, n)` and `_period_of(m)` helper.
- [ ] **Step 4** — run tests → PASS. Add a conformance check that
  `isinstance(client, DataClient)` if the Protocol is `@runtime_checkable`.
- [ ] **Step 5 — commit.** `feat(scanner-eval): CachedAsOfClient with hard no-lookahead + 60d fundamental lag`

---

### Task A3: `regimes.py` — classify bull/bear/choppy

**Files:**
- Create: `v2/scanner/eval/regimes.py`
- Test: `v2/scanner/eval/test_regimes.py`

- [ ] **Step 1 — failing test.** Synthetic SPY close lists:
```python
def test_monotonic_up_is_bull():
    prices = _mk([100*1.001**i for i in range(250)], start="2023-01-02")
    w = classify_window(prices, name="x", start="2023-01-02", end="2023-12-29")
    assert w.label == "BULL" and w.spy_return > 0.2

def test_drawdown_is_bear():
    prices = _mk([100*0.999**i for i in range(250)], ...)
    assert classify_window(...).label == "BEAR"

def test_flat_is_choppy():
    prices = _mk([100 + (i%5 - 2) for i in range(250)], ...)  # sideways
    assert classify_window(...).label == "CHOPPY"
```
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `RegimeWindow` dataclass (name,start,end,spy_return,
  max_drawdown,trend_r2,label). `classify_window(prices, *, name, start, end)`:
  slice prices to window, compute total return, max drawdown (running-peak),
  trend R² (OLS of log-close vs index). Label: `BEAR` if return ≤ −0.10 or
  drawdown ≤ −0.15 with negative slope; `BULL` if return ≥ +0.12 and R² high
  with positive slope; else `CHOPPY`. `DEFAULT_CANDIDATES` list with the 3
  windows from the spec. `classify_regimes(prices, candidates=DEFAULT_CANDIDATES)`
  maps each → RegimeWindow, logs the stats.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): SPY-based bull/bear/choppy regime classifier`

---

## Wave B — Evaluators (offline tests)

### Task B1: `detector_scorecard.py`

**Files:**
- Create: `v2/scanner/eval/detector_scorecard.py`
- Test: `v2/scanner/eval/test_detector_scorecard.py`

- [ ] **Step 1 — failing test.** A fake detector firing on a known day with a
  known forward move; synthetic prices; assert the produced row has the right
  `n_fired`, `interestingness_diff` sign, and `coverage`.
```python
class _FakeDet:
    name = "fake"
    def detect(self, ticker, end_date, fd):
        bars = fd.get_prices(ticker, "1900-01-01", end_date)
        # fire on one specific asof
        return EventTrigger(triggered=(end_date=="2024-02-01"), detector="fake",
                            direction="bull", severity_z=3.0, components={})
def test_scorecard_row_for_fired_detector(...):
    rows = score_detector(_FakeDet(), regime, bundles_by_ticker, spy_prices,
                          horizons=(5,20), rng_seed=0)
    r = rows[("fake","5d")]
    assert r["n_fired"] >= 1 and r["coverage"] > 0
```
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `score_detector(detector, regime, bundles, spy_prices,
  *, horizons, rng_seed)`:
  - For each ticker bundle: build `CachedAsOfClient`; for each `asof` in the
    regime's trading days: `set_asof(asof)`, `detect`, and if fired, for each
    horizon compute `signed/abs/dir/alpha/dir_alpha` forward returns (alpha vs
    SPY same window); collect.
  - Build seeded random baseline per ticker (sample valid asof indices), same
    metrics.
  - Per horizon call extended `evaluate_detector`; assemble a row dict with
    `detector, regime, horizon, n_fired, coverage, interestingness_diff,
    interestingness_t, dir_alpha_mean, dir_alpha_t`.
  - `score_all_detectors(detectors, regimes, bundles, spy) -> list[row]` and
    `write_detectors_csv(rows, path)`.
  - **Invariant:** never raise on a single detector/ticker — wrap, log, count
    (mirror runner failure isolation).
- [ ] **Step 4** — PASS. Also run `pytest tests/test_detector_invariants.py` to
  confirm no regression.
- [ ] **Step 5 — commit.** `feat(scanner-eval): per-detector x regime scorecard driver`

---

### Task B2: `signal_ic.py`

**Files:**
- Create: `v2/scanner/eval/signal_ic.py`
- Test: `v2/scanner/eval/test_signal_ic.py`

- [ ] **Step 1 — failing test.**
```python
def test_perfect_factor_ic_near_plus_one():
    # factor value == realized forward return → rank-IC ≈ 1
    ...
    assert ic_row["mean_ic_5d"] > 0.9
def test_negated_factor_ic_near_minus_one(): ...
def test_shuffled_factor_ic_near_zero(): ...
```
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `score_signal(signal, regime, bundles, *, horizons,
  rebalance="W")`:
  - At each weekly rebalance asof: for each ticker compute `signal.compute(
    ticker, asof, fd)` value (fd=CachedAsOfClient, set_asof) and forward Nd
    return; gather the cross-section.
  - Spearman rank-IC per date (guard n<5 → skip date); aggregate `mean_ic`,
    `ic_t = mean/std*sqrt(n_dates)`, `n_dates`, `coverage`.
  - `score_all_signals(...)`, `write_signals_csv(...)`.
  - Signals never raise (guaranteed by BaseSignal contract); still wrap.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): per-signal x regime rank-IC study`

---

### Task B3: `report.py` — `findings_scanner_eval.md` renderer + verdicts

**Files:**
- Create: `v2/scanner/eval/report.py`
- Test: `v2/scanner/eval/test_report.py`

- [ ] **Step 1 — failing test.** Feed a fixed list of detector rows + signal rows
  (some clearly KEEP, some CUT, some DATA-LIMITED) → assert the rendered markdown
  contains the right verdict chips and headline lists.
```python
def test_verdict_keep_and_cut():
    md = render_report(detector_rows=ROWS, signal_rows=SROWS, regimes=REG,
                       phase3=None)
    assert "## Useful" in md and "earnings_event" in _useful_section(md)
    assert classify_detector_verdict(rows_for("price_volume_anomaly")) == "CUT"
```
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `classify_detector_verdict(rows)` and
  `classify_signal_verdict(rows)` per the spec thresholds (KEEP/WATCH/CUT/
  DATA-LIMITED/INVERTED). `render_report(*, detector_rows, signal_rows, regimes,
  phase3)` → markdown: headline USEFUL/USELESS/DATA-LIMITED lists, detector table
  (rows×regimes), signal table, Phase-3 confirmation block (or "pending"),
  regime-definition table, methodology + caveats. `write_report(path, ...)`.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): findings report renderer + verdict logic`

---

## Wave C — Historical data sourcing (Phase 2)

### Task C1: `historical_events.py`

**Files:**
- Create: `v2/scanner/eval/historical_events.py`
- Test: `v2/scanner/eval/test_historical_events.py`

- [ ] **Step 1 — failing tests** (all mocked, no network): patch `yfinance.Ticker`
  to return a fixed earnings-dates DataFrame → assert `fetch_earnings_history`
  parses `(announce_date, eps_actual, eps_estimate, surprise_pct)`; patch the
  financials frames → assert `fetch_financials_history` builds period-stamped
  metrics; each fetcher returns `[]` when the source raises.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** Functions: `probe_availability(sample_ticker)`,
  `fetch_earnings_history`, `fetch_financials_history`, `fetch_sentiment_history`
  (EODHD `/sentiments`), `fetch_recommendation_history` (Finnhub rec-trend),
  `fetch_insider_window` (Finnhub insider, date range). Each best-effort,
  try/except → `[]`/`None`, logged. `enrich_bundle(bundle, *, sources, budget)`
  fills the bundle's event/fundamental lists from the fetchers. yfinance import
  lazy (inside the function) so the module imports without it.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): best-effort historical event/fundamental sourcing (yfinance/EODHD/Finnhub)`

---

## Wave D — Orchestrator + Phase 3

### Task D1: `phase3_backtest.py` — bounded full-replay confirmation

**Files:**
- Create: `v2/scanner/eval/phase3_backtest.py`
- Test: `v2/scanner/eval/test_phase3_backtest.py`

- [ ] **Step 1 — failing test.** Monkeypatch `v2.backtesting.engine.run_backtest`
  to write a tiny CSV → assert `run_phase3(regimes, ...)` invokes it per regime
  with quant on AND off, and `summarize_phase3(csv_paths)` returns mean alpha_5d
  per regime + the quant-on-minus-off delta.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `run_phase3(regimes, *, universe, top_n, max_days,
  out_dir, provider_factory)`: for each regime × `use_quant_signals in (True,
  False)` call `run_backtest(...)` with `max_days=max_days`. `summarize_phase3`
  reads the CSVs → dict for the report. Wrap each call; a failure → that cell
  "n/a", never aborts.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): bounded Phase-3 full-replay confirmation + summary`

---

### Task D2: `run_eval.py` — orchestrator CLI

**Files:**
- Create: `v2/scanner/eval/run_eval.py`
- Test: `v2/scanner/eval/test_run_eval.py`

- [ ] **Step 1 — failing test.** Monkeypatch each phase; assert: (a) Phase-1 report
  written before Phase-2 runs; (b) Phase-2 raising still leaves the Phase-1
  report on disk (fail-soft); (c) Phase-3 disabled by `--no-phase3`.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `main(argv)` with argparse (`--universe`,
  `--max-tickers`, `--phase2-budget-min`, `--phase3-max-days`, `--no-phase3`,
  `--out-dir`). Flow: load universe → provider_factory → fetch SPY →
  `classify_regimes` → **prefetch price bundles once/ticker** → Phase 1
  (score_all_detectors + score_all_signals on price data → write CSVs + report)
  → Phase 2 (probe + `enrich_bundle` within budget → re-score event/fundamental
  components → rewrite report) → Phase 3 (`run_phase3` unless `--no-phase3` →
  rewrite report) → append `progress.md`. Each phase `try/except` with a clear
  log; report is rewritten after each so partial completion still yields output.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(scanner-eval): run_eval orchestrator (3 fail-soft phases, incremental report)`

---

## Wave E — Execute the overnight run (compute, not code)

### Task E1: Real run

- [ ] Ensure `.env` keys present (EODHD/FINNHUB). On `feature/scanner-eval`.
- [ ] Run (background, long):
```
$env:PYTHONPATH="C:\Users\Jerry\Desktop\ai-hedge-fund"; $env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -m v2.scanner.eval.run_eval `
   --universe nasdaq100_sp500 --phase2-budget-min 90 --phase3-max-days 8
```
- [ ] Monitor; if a phase errors, the prior report still exists — capture the log.
- [ ] Verify `findings_scanner_eval.md` + `scanner_eval/*.csv` produced.
- [ ] Commit artifacts: `chore(scanner-eval): overnight run artifacts (report + CSVs)`
  (add `findings_scanner_eval.md` + `scanner_eval/` explicitly).

### Task E2: Wrap-up

- [ ] Append an overnight wrap-up to `progress.md` (what ran, what was
  DATA-LIMITED, headline verdicts). Commit.
- [ ] Prepare the morning report message: per-detector + per-signal verdicts,
  regime notes, data-coverage caveats, and the recommended cuts to consider.

---

## Self-review (done)

- **Spec coverage:** CachedAsOfClient (A2), regimes (A3), detector eval (B1),
  signal IC (B2), report+verdicts (B3), historical sourcing (C1), Phase-3 (D1),
  orchestrator (D2), real run (E) — every spec component has a task. ✓
- **Placeholders:** none — each task has concrete tests + signatures. The bodies
  marked "…/analogously" are mechanical mirrors of shown code, acceptable for
  opus implementers with the shown pattern. ✓
- **Type consistency:** `TickerBundle`, `CachedAsOfClient.set_asof`,
  `evaluate_detector` keys, row-dict columns, and `render_report` signature are
  used consistently across A1→B→D. ✓
- **Invariant safety:** B1/B2 run the detector-invariant test; no new detector is
  added (we only *evaluate* existing ones). ✓
