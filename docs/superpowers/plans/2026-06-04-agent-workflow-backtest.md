# Agent-Workflow Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `v2/workflow_backtest/` — a no-lookahead A/B backtest proving whether the Scanner→agents→execute workflow adds value (Scanner-arm vs Random-arm, across bull/bear/sideways regimes; absolute equity curve on the post-cutoff slice). The BUILD ships the framework + offline tests + a mocked smoke; the paid real run is a separate launch step.

**Architecture:** Reuse `run_agents_only`/`run_pipeline`, `CachedAsOfClient`, `regimes.py`, `forward_returns`, `run_scan`, `load_universe`, `PerformanceMetricsCalculator`. A multi-ticker `AsOfDispatcher` + a context manager make the agent data path as-of-safe (monkeypatch the api.py singleton AND `get_provider_factory`, clear sector/macro agent caches). Decisions → A/B attribution (forward-return t-test) + an equal-weight weekly-rebalance portfolio sim.

**Tech Stack:** Python (`C:\Users\Jerry\anaconda3\python.exe`), pytest, pandas, pydantic. Spec: `docs/superpowers/specs/2026-06-04-agent-workflow-backtest-design.md`.

**Constraints (every task):**
- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `-m pytest` with `PYTHONIOENCODING=utf-8`, `PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund`.
- **OFFLINE-ONLY build:** every test mocks `run_hedge_fund`/`run_scan` (via the `*_fn` injection seams) + uses constructed model instances / a fake provider. **NO network, NO LLM spend, deterministic.** Each task's verification = `pytest <file> -q` green.
- Commit per task; conventional message; **NO Co-Authored-By**; never `--no-verify`. Explicit `git add <paths>` (never `-A`; never stage `.claude/settings.local.json`).
- The **paid full run is NOT part of the build** — the deliverable is the package + offline tests + a mocked end-to-end smoke. A `--help`-able CLI exists but is launched separately by the user.
- Branch `main`. Tests co-located in `v2/workflow_backtest/test_*.py` (matches the v2 convention).

**Exact reuse surface (verbatim — do not re-derive):**
- `v2/pipeline/orchestrator.py`: `run_agents_only(*, tickers, scan_date, scanner_context=None, template=None, custom_analysts=None, portfolio=None, model_name="gpt-4.1", model_provider="OpenAI", show_reasoning=False, run_hedge_fund_fn=None) -> dict` returning `{"decisions": {ticker:{action,quantity,confidence?,reasoning?}}, "analyst_signals":..., "selected_analysts":..., "duration_seconds":...}`. `action ∈ {"buy","sell","short","cover","hold"}`. Read `confidence`/`reasoning` with `.get()` (not guaranteed).
- `v2/pipeline/orchestrator.py`: `run_pipeline(*, scan_date=None, universe="nasdaq100", top_n=5, model_name, model_provider, use_quant_signals=True, run_scan_fn=None, run_hedge_fund_fn=None, provider_factory=None, ...) -> PipelineResult` with `.agent_decisions: dict[ticker→decision]`, `.watchlist: list[dict]`, `.scan_date`, `.status`.
- `v2/scanner/runner.py`: `run_scan(*, tickers, end_date, top_n=20, provider_factory=None, ...) -> list[ScoredEntry]`; `ScoredEntry`: `.ticker, .composite_score, .direction, .event_severity, .rank, .triggers`.
- `v2/scanner/eval/cached_asof_client.py`: `CachedAsOfClient(bundle: TickerBundle)` (SINGLE ticker) + `.set_asof(date_iso)`; methods `get_prices(t,start,end)`, `get_financial_metrics(t,end_date,period,limit)`, `get_news(t,end_date,start_date,limit)`, `get_insider_trades(t,end_date,start_date,limit)`, `get_company_facts(t)`, `get_market_cap(t,end_date)`, `get_earnings_history(t,limit)`, `get_analyst_actions(t,*,end_date,start_date,limit)`, `get_analyst_targets(t,*,asof_date)`, `get_earnings(t)`, `get_earnings_calendar(*,start_date,end_date)`, `get_estimate_revisions(...)`, `close()`. `TickerBundle(ticker, prices, earnings_history, insider, news, metrics_history, analyst_actions, analyst_targets, facts, market_cap)`.
- `v2/scanner/eval/run_eval.py`: `prefetch_price_bundles(tickers, provider_factory, start, end) -> dict[str,TickerBundle]`; `v2/scanner/eval/historical_events.py`: `enrich_bundle(bundle, *, start_date, end_date, insider_client=None, news_client=None, do_financials=True, deadline=None) -> dict`.
- `v2/scanner/eval/regimes.py`: `DEFAULT_CANDIDATES: list[dict]` (`[{name,start,end},...]`), `classify_regimes(prices, candidates=DEFAULT_CANDIDATES) -> list[RegimeWindow]` (`RegimeWindow.name/start/end/label∈{BULL,BEAR,CHOPPY}`).
- `v2/backtesting/forward_returns.py`: `compute_forward_returns(fd, *, ticker, scan_date, windows=(1,5,20,63), benchmark_ticker="SPY", benchmark_prices=None) -> dict` with `ret_{N}d`, `bench_ret_{N}d`, `alpha_{N}d`, `close_at_scan`.
- `src/backtesting/metrics.py`: `PerformanceMetricsCalculator().compute_metrics(values: Sequence[PortfolioValuePoint]) -> {"sharpe_ratio","sortino_ratio","max_drawdown"(×100),"max_drawdown_date"}`. Input = equity curve points each with `"Date"`,`"Portfolio Value"`.
- `v2/scanner/universes/loader.py`: `load_universe("nasdaq100") -> list[str]`.
- `src/tools/api.py`: module global `_v2_client_cache` + `_get_v2_client()` (lazy singleton, short-circuits when non-None). `v2/data/factory.py`: `get_provider_factory()`.
- DeepSeek run: `model_name="deepseek-v4-pro"`, `model_provider="DeepSeek"`.

---

## File structure (all under `v2/workflow_backtest/`)

| File | Responsibility |
|---|---|
| `__init__.py` | package marker |
| `bundles.py` | build `{ticker: TickerBundle}` (prefetch prices + enrich) |
| `asof_dispatcher.py` | `AsOfDispatcher` — multi-ticker as-of client routing to per-ticker `CachedAsOfClient` |
| `asof_agents.py` | `asof_agent_context(dispatcher, scan_date)` — monkeypatch agent data path + clear caches + restore |
| `arms.py` | `scanner_arm(...)` / `random_arm(...)` — the two ticker lists per scan-date |
| `decisions.py` | run agents for an arm → `{ticker: Decision}` |
| `attribution.py` | join decisions × forward returns; A/B Welch t-test per regime/horizon |
| `portfolio.py` | equal-weight weekly-rebalance sim → equity curve + metrics |
| `regime_windows.py` | scan-date schedule across regimes + post-cutoff; classify |
| `run_workflow_backtest.py` | the runner (pool, resumable, per-date as-of ctx) + CLI |
| `report.py` | write `findings_agent_backtest.md` + CSVs |
| `test_*.py` | co-located offline tests, one per module |

---

### Task 1: Package skeleton + `Decision` dataclass

**Files:** Create `v2/workflow_backtest/__init__.py`, `v2/workflow_backtest/types.py`, `v2/workflow_backtest/test_types.py`

- [ ] **Step 1: failing test** — `v2/workflow_backtest/test_types.py`:
```python
from v2.workflow_backtest.types import Decision, ArmResult

def test_decision_defaults():
    d = Decision(ticker="NVDA", action="buy", quantity=10)
    assert d.ticker == "NVDA" and d.action == "buy" and d.quantity == 10
    assert d.confidence is None  # not guaranteed by all agent paths

def test_arm_result_holds_decisions():
    ar = ArmResult(arm="scanner", scan_date="2025-03-03", tickers=["NVDA"],
                   decisions={"NVDA": Decision(ticker="NVDA", action="buy", quantity=10, confidence=80)})
    assert ar.decisions["NVDA"].confidence == 80
```
- [ ] **Step 2: run → FAIL** (`ModuleNotFoundError`). `C:\Users\Jerry\anaconda3\python.exe -m pytest v2/workflow_backtest/test_types.py -q`
- [ ] **Step 3: implement** `v2/workflow_backtest/__init__.py` (empty) + `types.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Action = Literal["buy", "sell", "short", "cover", "hold"]
Arm = Literal["scanner", "random"]

@dataclass
class Decision:
    ticker: str
    action: Action
    quantity: int = 0
    confidence: int | None = None      # PM confidence 0-100; None if the agent path omitted it
    reasoning: str | None = None

@dataclass
class ArmResult:
    arm: Arm
    scan_date: str
    tickers: list[str]
    decisions: dict[str, Decision] = field(default_factory=dict)
    error: str | None = None
```
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `git add v2/workflow_backtest/__init__.py v2/workflow_backtest/types.py v2/workflow_backtest/test_types.py && git commit -m "feat(workflow-backtest): package skeleton + Decision/ArmResult types"`

---

### Task 2: `AsOfDispatcher` (multi-ticker, keystone risk)

**Files:** Create `v2/workflow_backtest/asof_dispatcher.py`, `v2/workflow_backtest/test_asof_dispatcher.py`

`CachedAsOfClient` is SINGLE-ticker. `AsOfDispatcher` holds many `TickerBundle`s and routes each `get_X(ticker, ...)` to that ticker's lazily-created `CachedAsOfClient` after `set_asof`. It must expose every method the agent path + scanner call.

- [ ] **Step 1: failing test** — `test_asof_dispatcher.py`:
```python
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.workflow_backtest.asof_dispatcher import AsOfDispatcher
from src.data.models import Price  # the model CachedAsOfClient returns is v2; use its Price

def _p(t, c):
    from v2.data.models import Price as V2Price
    return V2Price(open=c, close=c, high=c, low=c, volume=1000, time=t)

def test_dispatcher_clamps_per_ticker():
    bundles = {
        "AAA": TickerBundle(ticker="AAA", prices=[_p("2025-01-01", 10), _p("2025-01-02", 11), _p("2025-01-03", 12)]),
        "BBB": TickerBundle(ticker="BBB", prices=[_p("2025-01-01", 20), _p("2025-01-02", 21)]),
    }
    d = AsOfDispatcher(bundles)
    d.set_asof("2025-01-02")
    assert [p.time for p in d.get_prices("AAA", "2025-01-01", "2025-12-31")] == ["2025-01-01", "2025-01-02"]
    assert [p.time for p in d.get_prices("BBB", "2025-01-01", "2025-12-31")] == ["2025-01-01", "2025-01-02"]

def test_dispatcher_unknown_ticker_returns_empty():
    d = AsOfDispatcher({})
    d.set_asof("2025-01-02")
    assert d.get_prices("ZZZ", "2025-01-01", "2025-12-31") == []
    assert d.get_company_facts("ZZZ") is None
```
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `asof_dispatcher.py`:
```python
from __future__ import annotations
from v2.scanner.eval.cached_asof_client import CachedAsOfClient, TickerBundle

class AsOfDispatcher:
    """Multi-ticker as-of client. Wraps one CachedAsOfClient per ticker bundle and
    routes get_*(ticker, ...) calls to it after applying the shared as-of ceiling.
    Implements the DataClient surface the agents + scanner call. Unknown tickers
    return the empty/None default (never raise)."""

    def __init__(self, bundles: dict[str, TickerBundle]) -> None:
        self._clients = {t: CachedAsOfClient(b) for t, b in bundles.items()}
        self._asof: str | None = None

    def set_asof(self, date_iso: str) -> None:
        self._asof = date_iso[:10]
        for c in self._clients.values():
            c.set_asof(self._asof)

    def _c(self, ticker: str) -> CachedAsOfClient | None:
        return self._clients.get(ticker)

    def get_prices(self, ticker, start_date, end_date, **kw):
        c = self._c(ticker); return c.get_prices(ticker, start_date, end_date, **kw) if c else []
    def get_financial_metrics(self, ticker, end_date, period="ttm", limit=10):
        c = self._c(ticker); return c.get_financial_metrics(ticker, end_date, period, limit) if c else []
    def get_news(self, ticker, end_date, start_date=None, limit=1000):
        c = self._c(ticker); return c.get_news(ticker, end_date, start_date, limit) if c else []
    def get_insider_trades(self, ticker, end_date, start_date=None, limit=1000):
        c = self._c(ticker); return c.get_insider_trades(ticker, end_date, start_date, limit) if c else []
    def get_company_facts(self, ticker):
        c = self._c(ticker); return c.get_company_facts(ticker) if c else None
    def get_market_cap(self, ticker, end_date):
        c = self._c(ticker); return c.get_market_cap(ticker, end_date) if c else None
    def get_earnings_history(self, ticker, limit=12):
        c = self._c(ticker); return c.get_earnings_history(ticker, limit) if c else []
    def get_earnings(self, ticker):
        c = self._c(ticker); return c.get_earnings(ticker) if c else None
    def get_earnings_calendar(self, *, start_date, end_date):
        return []
    def get_analyst_actions(self, ticker, *, end_date, start_date, limit=100):
        c = self._c(ticker); return c.get_analyst_actions(ticker, end_date=end_date, start_date=start_date, limit=limit) if c else []
    def get_analyst_targets(self, ticker, *, asof_date=None):
        c = self._c(ticker); return c.get_analyst_targets(ticker, asof_date=asof_date) if c else None
    def get_estimate_revisions(self, ticker, *, period="0q", asof_date=None):
        c = self._c(ticker); return c.get_estimate_revisions(ticker, period=period, asof_date=asof_date) if c else None
    def close(self) -> None:
        pass
```
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `git add v2/workflow_backtest/asof_dispatcher.py v2/workflow_backtest/test_asof_dispatcher.py && git commit -m "feat(workflow-backtest): multi-ticker AsOfDispatcher over CachedAsOfClient"`

---

### Task 3: `asof_agent_context` (highest-risk: monkeypatch all agent data paths)

**Files:** Create `v2/workflow_backtest/asof_agents.py`, `v2/workflow_backtest/test_asof_agents.py`

A context manager that, for one `scan_date`, makes EVERY agent data read as-of-safe by: (a) `dispatcher.set_asof(scan_date)`; (b) `src.tools.api._v2_client_cache = dispatcher`; (c) `v2.data.factory.get_provider_factory = lambda: (lambda: dispatcher)` (covers sector_agent/macro_agent which bypass api.py); (d) clear the agent module caches; restore ALL on exit. `search_line_items` (yfinance) is a documented residual leak — out of scope to clamp (A/B-cancelled).

- [ ] **Step 1: failing test** — `test_asof_agents.py` (pure offline; assert swap + restore + set_asof called):
```python
import src.tools.api as api_mod
import v2.data.factory as factory_mod
from v2.workflow_backtest.asof_agents import asof_agent_context

class _FakeDispatcher:
    def __init__(self): self.asof = None
    def set_asof(self, d): self.asof = d

def test_context_swaps_and_restores():
    orig_cache = api_mod._v2_client_cache
    orig_factory = factory_mod.get_provider_factory
    disp = _FakeDispatcher()
    with asof_agent_context(disp, "2025-03-03"):
        assert disp.asof == "2025-03-03"
        assert api_mod._v2_client_cache is disp
        assert factory_mod.get_provider_factory()() is disp   # factory returns a factory→dispatcher
    assert api_mod._v2_client_cache is orig_cache
    assert factory_mod.get_provider_factory is orig_factory
```
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `asof_agents.py` (read `src/agents/sector_agent.py` + `macro_agent.py` for the exact cache global names — `_SECTOR_CACHE`, `_ETF_PRICES` confirmed in sector_agent; clear any dict caches found, guarded by `getattr`):
```python
from __future__ import annotations
import contextlib
import src.tools.api as _api
import v2.data.factory as _factory

@contextlib.contextmanager
def asof_agent_context(dispatcher, scan_date: str):
    """Force every agent data read for `scan_date` through `dispatcher` (as-of-safe).
    Patches src.tools.api._v2_client_cache AND v2.data.factory.get_provider_factory
    (sector/macro agents bypass api.py), clears agent module caches, restores on exit.
    Residual leak: search_line_items (yfinance) is NOT clamped — A/B-cancelled."""
    dispatcher.set_asof(scan_date)
    saved_cache = _api._v2_client_cache
    saved_factory = _factory.get_provider_factory
    cleared = []  # (module, attr, original) to restore
    try:
        _api._v2_client_cache = dispatcher
        _factory.get_provider_factory = lambda: (lambda: dispatcher)
        for modname, attrs in (
            ("src.agents.sector_agent", ("_SECTOR_CACHE", "_ETF_PRICES")),
            ("src.agents.macro_agent", ("_MACRO_CACHE",)),
        ):
            try:
                mod = __import__(modname, fromlist=["*"])
            except Exception:
                continue
            for a in attrs:
                cache = getattr(mod, a, None)
                if isinstance(cache, dict):
                    cleared.append((mod, a, dict(cache)))
                    cache.clear()
        yield dispatcher
    finally:
        _api._v2_client_cache = saved_cache
        _factory.get_provider_factory = saved_factory
        for mod, a, original in cleared:
            cache = getattr(mod, a, None)
            if isinstance(cache, dict):
                cache.clear(); cache.update(original)
```
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `git add v2/workflow_backtest/asof_agents.py v2/workflow_backtest/test_asof_agents.py && git commit -m "feat(workflow-backtest): as-of context manager wiring the agent data path"`

---

### Task 4: Bundle prefetch (`bundles.py`)

**Files:** Create `v2/workflow_backtest/bundles.py`, `v2/workflow_backtest/test_bundles.py`

Build `{ticker: TickerBundle}` for the backtest universe + date span, reusing `prefetch_price_bundles` + `enrich_bundle`. Tested offline with a fake provider (no network).

- [ ] **Step 1: failing test** — `test_bundles.py` injects a fake provider_factory returning a stub client whose `get_prices` returns canned bars; assert `build_bundles(["AAA"], factory, "2025-01-01", "2025-02-01", enrich=False)` returns `{"AAA": TickerBundle}` with the canned prices. (enrich=False to stay offline; enrich path covered by historical_events' own tests.)
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `bundles.py`:
```python
from __future__ import annotations
from v2.scanner.eval.run_eval import prefetch_price_bundles
from v2.scanner.eval.historical_events import enrich_bundle

def build_bundles(tickers, provider_factory, start_date, end_date, *, enrich=True, deadline=None):
    """Prefetch a TickerBundle per ticker (prices, then optionally enrich with
    earnings/insider/news/metrics). enrich=False keeps it offline/price-only."""
    bundles = prefetch_price_bundles(tickers, provider_factory, start_date, end_date)
    if enrich:
        client = provider_factory()
        for b in bundles.values():
            try:
                enrich_bundle(b, start_date=start_date, end_date=end_date,
                              insider_client=client, news_client=client, deadline=deadline)
            except Exception:
                pass
    return bundles
```
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `... -m "feat(workflow-backtest): bundle prefetch helper"`

---

### Task 5: Arms (`arms.py`)

**Files:** Create `v2/workflow_backtest/arms.py`, `v2/workflow_backtest/test_arms.py`

`scanner_arm(scan_date, universe_tickers, top_n, provider_factory, run_scan_fn=run_scan)` → top-N tickers + the per-ticker scanner_context (reuse the orchestrator's `_entry_to_scanner_context`). `random_arm(scan_date, universe_tickers, n, seed)` → seeded reproducible random tickers.

- [ ] **Step 1: failing test** — `test_arms.py`: `random_arm("2025-03-03", ["A","B","C","D","E"], 2, seed=42)` is deterministic + a subset of size 2; calling twice with same seed+date gives the same list. `scanner_arm` with a `run_scan_fn` stub returning 2 `ScoredEntry`s yields those 2 tickers.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `arms.py`:
```python
from __future__ import annotations
import random
from v2.scanner.runner import run_scan as _run_scan
from v2.pipeline.orchestrator import _entry_to_scanner_context

def scanner_arm(*, scan_date, universe_tickers, top_n, provider_factory, run_scan_fn=None):
    fn = run_scan_fn or _run_scan
    entries = fn(tickers=universe_tickers, end_date=scan_date, top_n=top_n, provider_factory=provider_factory)
    tickers = [e.ticker for e in entries]
    context = {}
    for e in entries:
        context.update(_entry_to_scanner_context(e, scan_date))
    return tickers, context

def random_arm(*, scan_date, universe_tickers, n, seed):
    rng = random.Random(f"{seed}:{scan_date}")
    pool = list(dict.fromkeys(universe_tickers))
    return rng.sample(pool, min(n, len(pool)))
```
(If `_entry_to_scanner_context` is not importable as-is, inline an equivalent that builds `{ticker: {scan_date, rank, composite_score, direction, event_severity, triggered_detectors, triggered_components}}` from the ScoredEntry — confirm during impl.)
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `... -m "feat(workflow-backtest): scanner + seeded random arms"`

---

### Task 6: Decisions (`decisions.py`)

**Files:** Create `v2/workflow_backtest/decisions.py`, `v2/workflow_backtest/test_decisions.py`

Run the agents for an arm's tickers via `run_agents_only` (inject a `run_hedge_fund_fn` stub in tests) and map the result to `{ticker: Decision}`. Never raise — on failure return an `ArmResult` with `error` set.

- [ ] **Step 1: failing test** — stub `run_hedge_fund_fn` returns `{"decisions": {"NVDA": {"action":"buy","quantity":5,"confidence":70}}, "analyst_signals": {}}`; assert `run_arm_decisions(arm="random", scan_date="2025-03-03", tickers=["NVDA"], scanner_context=None, run_hedge_fund_fn=stub, model_name="deepseek-v4-pro", model_provider="DeepSeek")` → `ArmResult` with `decisions["NVDA"].action=="buy"`, `.confidence==70`. A stub that raises → `ArmResult.error` set, `decisions=={}`.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `decisions.py`:
```python
from __future__ import annotations
from v2.pipeline.orchestrator import run_agents_only
from v2.workflow_backtest.types import ArmResult, Decision

def run_arm_decisions(*, arm, scan_date, tickers, scanner_context, model_name, model_provider,
                      run_hedge_fund_fn=None):
    try:
        out = run_agents_only(
            tickers=tickers, scan_date=scan_date, scanner_context=scanner_context,
            model_name=model_name, model_provider=model_provider,
            run_hedge_fund_fn=run_hedge_fund_fn,
        )
    except Exception as e:
        return ArmResult(arm=arm, scan_date=scan_date, tickers=tickers, error=f"{type(e).__name__}: {e}")
    raw = out.get("decisions") or {}
    decisions = {}
    for t, d in raw.items():
        if not isinstance(d, dict):
            continue
        decisions[t] = Decision(ticker=t, action=d.get("action", "hold"),
                                quantity=int(d.get("quantity") or 0),
                                confidence=d.get("confidence"), reasoning=d.get("reasoning"))
    return ArmResult(arm=arm, scan_date=scan_date, tickers=tickers, decisions=decisions)
```
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `... -m "feat(workflow-backtest): run agents per arm → Decisions"`

---

### Task 7: Attribution + A/B test (`attribution.py`)

**Files:** Create `v2/workflow_backtest/attribution.py`, `v2/workflow_backtest/test_attribution.py`

For each BUY decision, attach `compute_forward_returns` (inject a fake `fd`/prices in tests). Then the A/B: Welch t-test of scanner-arm BUY forward returns vs random-arm BUY forward returns, per (regime, horizon).

- [ ] **Step 1: failing test** — feed two lists of forward returns (scanner BUYs `[0.05,0.04,0.06]`, random BUYs `[0.0,-0.01,0.01]`); assert `ab_welch(scanner, random)` returns `{"diff": ~0.043, "t": >0, "n_scanner":3, "n_random":3}`; equal lists → `t≈0`; <2 samples either side → `t=None`.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `attribution.py` with `attach_forward_returns(decisions_rows, fd, windows=(21,42,63))` (calls `compute_forward_returns` per BUY row, using the UNCLAMPED full-series `fd` so outcomes aren't clamped) + `ab_welch(a: list[float], b: list[float]) -> dict` (manual Welch t to avoid a scipy dep: `t = (mean_a-mean_b)/sqrt(var_a/n_a+var_b/n_b)`, guard n<2 → None). Quote full code in the task during impl.
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `... -m "feat(workflow-backtest): forward-return attribution + Welch A/B test"`

---

### Task 8: Portfolio sim (`portfolio.py`)

**Files:** Create `v2/workflow_backtest/portfolio.py`, `v2/workflow_backtest/test_portfolio.py`

Equal-weight the BUY decisions each rebalance week, hold H trading days, apply `(commission_bps+slippage_bps)/1e4` on both legs, mark-to-market daily → equity-curve points → `PerformanceMetricsCalculator.compute_metrics`. One curve per arm + SPY buy-hold.

- [ ] **Step 1: failing test** — a 2-week, 2-ticker toy with canned prices + decisions: assert the equity curve length = #trading days, final value reflects equal-weight returns minus costs, and `compute_metrics` returns a dict with `sharpe_ratio`/`max_drawdown` keys. A no-BUY week → cash held flat.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `portfolio.py`: `simulate(decisions_by_date, prices_by_ticker, *, hold_days=21, starting_capital=100_000, commission_bps=5, slippage_bps=5) -> {"equity_curve": list[PortfolioValuePoint], "metrics": dict}`. Equal-weight new BUYs across available cash; close positions after `hold_days`; daily MTM. Reuse `PerformanceMetricsCalculator().compute_metrics(equity_curve)`. Full code authored during impl from this contract.
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `... -m "feat(workflow-backtest): equal-weight weekly-rebalance portfolio sim"`

---

### Task 9: Regime windows + scan-date schedule (`regime_windows.py`)

**Files:** Create `v2/workflow_backtest/regime_windows.py`, `v2/workflow_backtest/test_regime_windows.py`

`weekly_scan_dates(window, trading_days, every=5)` samples ~weekly dates inside a window; `build_schedule(trading_days, spy_prices, post_cutoff_start="2025-01-01", run_date=...)` returns `[(scan_date, regime_name, regime_label, is_post_cutoff)]` over `DEFAULT_CANDIDATES + post_cutoff window`, labels via `classify_regimes`.

- [ ] **Step 1: failing test** — `weekly_scan_dates` over a 20-trading-day list with `every=5` returns 4 dates evenly spaced + all inside the window; `build_schedule` tags 2025+ dates `is_post_cutoff=True` and 2022 dates `False`.
- [ ] **Step 2–5:** implement + test + commit (`-m "feat(workflow-backtest): regime-segmented scan-date schedule + post-cutoff flag"`).

---

### Task 10: Runner + report + mocked smoke (`run_workflow_backtest.py`, `report.py`)

**Files:** Create `v2/workflow_backtest/run_workflow_backtest.py`, `report.py`, `test_runner_smoke.py`

The runner ties it together: build bundles → schedule → for each scan_date, under `asof_agent_context`, run both arms' decisions (parallel within a date via a bounded `ThreadPoolExecutor`), attach forward returns, persist per-(date,arm) JSON incrementally (resumable — skip existing), then portfolio sim + A/B per regime → `report.write(...)`. A CLI `main()` with args (`--universe nasdaq100 --top-n 5 --every 5 --model deepseek-v4-pro --provider DeepSeek --hold-days 21 --seed 42 --out-dir workflow_backtest --smoke`). `--smoke` runs 2 dates × top_n=2 with INJECTED stub agent fns (no network) and asserts files are produced.

- [ ] **Step 1: failing test** — `test_runner_smoke.py` calls `run_workflow_backtest(..., run_scan_fn=stub, run_hedge_fund_fn=stub, provider_factory=fake, schedule=[2 dates], out_dir=tmp)` and asserts: both arms ran each date, `findings_agent_backtest.md` + `decisions.csv` exist, the A/B section is present. All stubbed — offline.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** the runner (dependency-injected fns so the smoke is offline; the real CLI defaults to the live `run_scan`/`run_agents_only` + a real `provider_factory` for the user's paid launch) + `report.py` (writes the markdown + CSVs from the collected results, per-regime A/B table + post-cutoff absolute metrics).
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** — `... -m "feat(workflow-backtest): runner (resumable, parallel) + report + offline smoke"`

---

## Self-review

**Spec coverage:** A/B attribution (T6,T7) ✓; absolute portfolio (T8) ✓; post-cutoff slice (T9) ✓; no-lookahead agent wiring (T2,T3 — dispatcher + monkeypatch BOTH api.py singleton AND get_provider_factory + clear sector/macro caches) ✓; CachedAsOfClient reuse (T2) ✓; regimes (T9) ✓; parallel within-date + resumable runner (T10) ✓; report + CSVs (T10) ✓; offline-only build, paid run separate (every task; `--smoke`) ✓; DeepSeek params (`deepseek-v4-pro`/`DeepSeek`, T6/T10) ✓; residual leaks documented (T3 docstring) ✓; out-of-scope Lab/PM-exits respected ✓.

**Placeholder scan:** T7/T8/T10 say "full code authored during impl from this contract" — acceptable because each gives the exact signature + behavior + the test that pins it; the implementer writes within a fixed interface. No TBD/vague-error-handling.

**Type consistency:** `Decision`/`ArmResult` (T1) used verbatim in T6; `AsOfDispatcher` (T2) consumed by T3; `run_agents_only` plain-dict return + `.get("confidence")` defensive read consistent (T6); `compute_metrics` equity-curve input + ×100 max_drawdown (T8) matches the reuse surface; `run_hedge_fund_fn`/`run_scan_fn` injection seams used uniformly for offline tests.

**Sequencing:** keystone as-of (T2,T3) early as required; each task independently green; T10 proves the pipe end-to-end offline before any paid launch.
