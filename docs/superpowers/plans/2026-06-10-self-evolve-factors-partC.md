# Self-Evolve 11-Factor Library (Part C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the self-evolve factor library from an effective 3 to 11 academically-backed, point-in-time-backtestable factors (fixing the two silently-inert fundamental factors and adding a real line-items data path).

**Architecture:** Add a `line_items_history` enrich to the bundle (yfinance annual via `search_line_items`, 60-day as-of lag). Add 4 price/volume factors (MAX, 52-week-high, turnover, residual-momentum) and rebuild 4 fundamental factors (value E/P, gross-profitability, asset-growth, ROE) on real data. All flow through the generic `FACTOR_KEYS` plumbing; the Part-B cache covers them once their lookbacks are added to `_lookback_cache_key`.

**Tech Stack:** Python (anaconda interpreter), pytest, the existing `v2/self_evolve/` package + `src.tools.line_items` + `v2/scanner/eval/historical_events`.

**Global constraints (every task):**
- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest <path> -q`; OFFLINE only (synthetic `SimpleNamespace` bundles; mock `search_line_items`).
- Commit per task; conventional message; **NO Co-Authored-By**; never `--no-verify`; explicit `git add <paths>` (never `-A`); never stage `.claude/settings.local.json`.
- `black` on touched `.py`. Branch `main`.

**Cross-cutting invariants (apply in EVERY factor task):**
1. **No-lookahead:** prices use bars dated ≤ asof; fundamentals use the latest line-items record with `report_period ≤ asof − 60d` (`FUNDAMENTAL_AVAILABILITY_LAG_DAYS`). A bar/record dated after the ceiling can never change a value (assert it in each factor's test).
2. **Two FACTOR_KEYS in sync:** `v2/self_evolve/config.py:80` AND `v2/self_evolve/factors.py:48` both define `FACTOR_KEYS`. Every key added must go in BOTH.
3. **Cache-key completeness (load-bearing):** every windowed factor's lookback MUST be added to `factors._lookback_cache_key` (else the Part-B cache returns stale values when that window changes). Fundamental factors have no window (fixed 60d lag) → no cache-key change.
4. **`validate()` (config.py:195) requires `factor_weights` keys == `FACTOR_KEYS` exactly + sum to 1.0** — so adding a key to `FACTOR_KEYS` REQUIRES adding it to `strategy_skill/skill_config.yaml` `factor_weights` (the `__post_init__` re-normalizes the sum).
5. **Never raises:** a missing line-item field / short history → that factor is `None` → neutral 0 in the z-score (ticker kept). Mirrors today's `value`/`quality`.

**Factor formulas (as-of D), direction sign baked so "higher z = better":**
| key | formula | source |
|---|---|---|
| `max_lottery` | `−max(daily return over last max_days≈21 as-of bars)` | Bali-Cakici-Whitelaw 2011 |
| `high_52w` | `close[D] / max(close over last hi_days≈252 as-of bars)` | George-Hwang 2004 |
| `turnover` | `−mean(volume over last to_days≈21 as-of bars) / latest book "shares" proxy` → use `−mean(volume)/mean(volume over a long baseline)` (a relative turnover; no shares needed) | Datar-Naik-Radcliffe 1998 |
| `resid_mom` | momentum of the stock's returns residualized vs the universe-mean return over the formation window (computed in `compute_factors`, which has all bundles) | Blitz-Huij-Martens 2011 |
| `value` | `EPS_lagged / close[D]` (earnings yield); `None` if EPS≤0 or missing | Fama-French HML |
| `gross_prof` | `gross_profit_lagged / total_assets_lagged`; fallback `gross_margin` from `metrics_history` | Novy-Marx 2013 |
| `asset_growth` | `−(total_assets[t] / total_assets[t−1] − 1)` | Cooper-Gulen-Schill 2008 |
| `quality` (real ROE) | `EPS_lagged / book_value_per_share_lagged` (= NI/equity); replaces the inert ROE | — |

---

## Phase 1 — line-items data path

### Task 1: fetch + attach `line_items_history`

**Files:**
- Modify: `v2/scanner/eval/historical_events.py` (add `fetch_line_items_history` + attach in the enrich body next to `metrics_history`)
- Test: `v2/scanner/eval/test_line_items_enrich.py` (create)

- [ ] **Step 1: failing test** (mock `search_line_items`; assert the bundle gets a `line_items_history` of records carrying `report_period` + the requested fields):

```python
from types import SimpleNamespace
import v2.scanner.eval.historical_events as he


def test_fetch_line_items_history_maps_fields(monkeypatch):
    fake = [
        SimpleNamespace(ticker="X", report_period="2022-12-31", period="annual",
                        total_assets=1000.0, earnings_per_share=5.0,
                        book_value_per_share=25.0, revenue=800.0,
                        cost_of_revenue=500.0, net_income=120.0),
    ]
    monkeypatch.setattr(he, "search_line_items", lambda *a, **k: fake)
    out = he.fetch_line_items_history("X")
    assert out and out[0].report_period == "2022-12-31"
    assert out[0].total_assets == 1000.0 and out[0].earnings_per_share == 5.0


def test_fetch_line_items_history_never_raises(monkeypatch):
    monkeypatch.setattr(he, "search_line_items", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert he.fetch_line_items_history("X") == []
```

- [ ] **Step 2: run → fail** (`fetch_line_items_history` undefined).

- [ ] **Step 3: implement** — in `historical_events.py`, import `search_line_items` (`from src.tools.line_items import search_line_items`) and add:

```python
_LINE_ITEM_FIELDS = [
    "total_assets", "earnings_per_share", "book_value_per_share",
    "revenue", "cost_of_revenue", "gross_profit", "net_income",
]


def fetch_line_items_history(ticker: str, *, end_date: str | None = None, limit: int = 10) -> list:
    """Best-effort annual line-items series (yfinance) for fundamental factors.

    Returns ``LineItem`` records (each with ``report_period`` + the requested
    fields as dynamic attrs). Never raises — any failure yields ``[]`` so the
    fundamental factors degrade to ``None`` (neutral), not a crash."""
    from datetime import date

    try:
        end = end_date or date.today().isoformat()
        recs = search_line_items(ticker, list(_LINE_ITEM_FIELDS), end, period="annual", limit=limit)
        return list(recs or [])
    except Exception as e:  # noqa: BLE001 — best-effort enrich
        logger.debug("fetch_line_items_history(%s) failed: %s", ticker, e)
        return []
```

Then attach it in the enrich body (next to the `do_financials` block that sets `bundle.metrics_history`):

```python
    if do_financials and not _expired(deadline):
        bundle.line_items_history = fetch_line_items_history(bundle.ticker, end_date=end_date)
        counts["line_items"] = len(bundle.line_items_history)
```
(add `"line_items": 0` to the `counts` dict initialiser.)

- [ ] **Step 4: run → pass.**

- [ ] **Step 5: commit**
```bash
git add v2/scanner/eval/historical_events.py v2/scanner/eval/test_line_items_enrich.py
git commit -m "feat(self-evolve): line-items history enrich for fundamental factors (yfinance, best-effort)"
```

### Task 2: as-of line-item lookups in factors.py

**Files:**
- Modify: `v2/self_evolve/factors.py` (add `_latest_lagged_line_item` + `_prior_year_line_item`)
- Test: `v2/self_evolve/test_factors_line_items.py` (create)

- [ ] **Step 1: failing test** — the lag excludes a too-recent record; `_prior_year_line_item` returns the one before the latest-knowable:

```python
from types import SimpleNamespace
from v2.self_evolve.factors import _latest_lagged_line_item, _prior_year_line_item


def _li(rp, **kw):
    return SimpleNamespace(report_period=rp, **kw)


def test_latest_lagged_excludes_too_recent():
    items = [_li("2021-12-31", total_assets=100.0), _li("2022-12-31", total_assets=200.0)]
    # asof 2023-01-15: 2022-12-31 is < 60d before -> not knowable -> 2021 wins.
    got = _latest_lagged_line_item(items, "2023-01-15")
    assert got.total_assets == 100.0


def test_prior_year_line_item():
    items = [_li("2020-12-31", total_assets=80.0), _li("2021-12-31", total_assets=100.0), _li("2022-12-31", total_assets=200.0)]
    latest, prior = _latest_lagged_line_item(items, "2023-06-01"), None
    prior = _prior_year_line_item(items, "2023-06-01")
    assert latest.total_assets == 200.0 and prior.total_assets == 100.0
```

- [ ] **Step 2: run → fail.**

- [ ] **Step 3: implement** — mirror `_latest_lagged_metric` (already in factors.py): `_latest_lagged_line_item(items, asof)` returns the newest record with `report_period ≤ asof − 60d`; `_prior_year_line_item(items, asof)` returns the newest record strictly older than that latest one (for asset growth). Both defensive (`_parse_iso`; skip unparseable; `None` on empty). Reuse `_parse_iso` + `_minus_days` + `FUNDAMENTAL_AVAILABILITY_LAG_DAYS`.

- [ ] **Step 4: run → pass. Step 5: commit**
```bash
git add v2/self_evolve/factors.py v2/self_evolve/test_factors_line_items.py
git commit -m "feat(self-evolve): as-of line-item lookups (60d lag + prior-year) for fundamental factors"
```

---

## Phase 2 — make the config 11-factor-ready (factors still neutral)

### Task 3: extend FACTOR_KEYS / ADJUSTABLE / skill_config.yaml / cache key

**Files:** Modify `v2/self_evolve/config.py`, `v2/self_evolve/factors.py` (local FACTOR_KEYS + `_lookback_cache_key`), `strategy_skill/skill_config.yaml`. Test: `v2/self_evolve/test_config.py` (append).

- [ ] **Step 1: failing test** — assert the 11 keys exist + are adjustable + the new lookbacks are keyed:

```python
def test_eleven_factor_keys_and_adjustable():
    from v2.self_evolve.config import FACTOR_KEYS, ADJUSTABLE, load_config, validate
    import os
    expected = {"momentum","low_vol","reversal","value","quality",
                "max_lottery","high_52w","turnover","resid_mom","gross_prof","asset_growth"}
    assert set(FACTOR_KEYS) == expected
    for k in expected:
        assert f"factor_weights.{k}" in ADJUSTABLE
    for lb in ("max_days","hi_days","to_days","resid_days"):
        assert f"lookback.{lb}" in ADJUSTABLE
    cfg = load_config(os.path.join("strategy_skill","skill_config.yaml"))
    validate(cfg)  # 11 weights present + normalized
```

> Note: that is 11 keys — the table lists `quality` (rebuilt ROE) + 10 others; `value` is rebuilt too. Final set = the 5 originals (value/quality rebuilt) + max_lottery, high_52w, turnover, resid_mom, gross_prof, asset_growth = **11**.

- [ ] **Step 2: run → fail.**

- [ ] **Step 3: implement** —
  - `config.py:80` `FACTOR_KEYS` and `factors.py:48` `FACTOR_KEYS`: add the 6 new keys (`max_lottery, high_52w, turnover, resid_mom, gross_prof, asset_growth`).
  - `config.py` `ADJUSTABLE`: add `factor_weights.<each new key>: (0.0, 1.0)` and `lookback.max_days: (10, 42)`, `lookback.hi_days: (120, 300)`, `lookback.to_days: (10, 63)`, `lookback.resid_days: (120, 300)`.
  - `factors._lookback_cache_key`: extend the returned tuple to also include `int(lb.get("max_days",0)), int(lb.get("hi_days",0)), int(lb.get("to_days",0)), int(lb.get("resid_days",0))`.
  - `strategy_skill/skill_config.yaml`: add the 6 new `factor_weights` (small defaults, e.g. each 0.05, leaving the 5 originals dominant — `__post_init__` re-normalizes) and the 4 new `lookback` entries (`max_days: 21, hi_days: 252, to_days: 21, resid_days: 252`).

- [ ] **Step 4: run → pass** (`test_config.py` + full `v2/self_evolve/` suite stays green — the 6 new factors are not yet computed, so they are neutral 0 everywhere; existing behavior unchanged except a benign re-normalization of the original weights).

- [ ] **Step 5: commit**
```bash
git add v2/self_evolve/config.py v2/self_evolve/factors.py strategy_skill/skill_config.yaml v2/self_evolve/test_config.py
git commit -m "feat(self-evolve): register 11 FACTOR_KEYS + new lookbacks + cache-key (factors neutral until computed)"
```

---

## Phase 3 — implement the factors (one task each; key+weight already exist → just compute + test)

For each: add the computation to `_compute_one` (per-ticker factors) and to its returned dict; add the factor's test to `v2/self_evolve/test_factors_partc.py`; the test asserts (a) a known value on a synthetic bundle, (b) no-lookahead (a bar/record after asof does not change it), (c) `None`/neutral on missing data. Commit per factor.

- [ ] **Task 4 — `max_lottery`:** `−max(daily return over last max_days as-of bars)`. Reuse the as-of return window pattern from `low_vol`. Test: a bundle with one big up-day in the window → low (negative) factor; a big up-day AFTER asof → unchanged. Commit `feat(self-evolve): MAX lottery factor`.

- [ ] **Task 5 — `high_52w`:** `close[asof] / max(close over last hi_days as-of bars)`. Test: at the high → ~1.0; below → <1.0; a higher close AFTER asof → unchanged. Commit `feat(self-evolve): 52-week-high proximity factor`.

- [ ] **Task 6 — `turnover`:** `−mean(volume over last to_days as-of bars) / mean(volume over the full as-of series)` (relative recent turnover; sign negative = high turnover penalised). Guard divide-by-zero with the std-floor pattern. Test: rising recent volume → more negative; no volume → `None`. Commit `feat(self-evolve): turnover (relative recent volume) factor`.

- [ ] **Task 7 — `value` (rebuilt E/P):** `EPS_lagged / close[asof]` where `EPS_lagged = getattr(_latest_lagged_line_item(bundle.line_items_history, asof), "earnings_per_share", None)`; `None` if EPS is `None`/≤0 or close≤0. Test: known EPS+close → E/P; a line-item dated < 60d before asof excluded; missing → `None`. Commit `feat(self-evolve): real value (E/P) factor from line items`.

- [ ] **Task 8 — `gross_prof`:** `gross_profit_lagged / total_assets_lagged`; if `gross_profit` is missing, derive `revenue − cost_of_revenue`; if still missing, fall back to `gross_margin` from `_latest_lagged_metric(bundle.metrics_history, asof)`. `None` if no source. Test: line-items path; metrics fallback path; missing → `None`. Commit `feat(self-evolve): gross-profitability factor (line items, gross_margin fallback)`.

- [ ] **Task 9 — `asset_growth`:** `−(ta_t / ta_prev − 1)` with `ta_t = total_assets` of `_latest_lagged_line_item`, `ta_prev = total_assets` of `_prior_year_line_item`; `None` if either missing or `ta_prev ≤ 0`. Test: two years of assets → correct sign (growth → negative factor); one year only → `None`. Commit `feat(self-evolve): asset-growth (investment/CMA) factor`.

- [ ] **Task 10 — `quality` (rebuilt ROE):** `EPS_lagged / BVPS_lagged` (`book_value_per_share`); `None` if BVPS `None`/≤0. This REPLACES the old inert `price_to_earnings_ratio`/`return_on_equity` reads in `_quality_from_metric`/`_value_from_metric` — delete those two helpers and their calls (they always returned `None`; removing them is cleaning up orphaned-by-this-change code). Test: known EPS+BVPS → ROE; lag respected; missing → `None`. Commit `feat(self-evolve): real ROE quality factor from line items; drop inert PE/ROE reads`.

- [ ] **Task 11 — `resid_mom` (cross-sectional; computed in `compute_factors`, NOT `_compute_one`):**
  - In `compute_factors`, after the per-ticker loop, compute the universe-mean daily return series over the trailing `resid_days` as-of bars (mean across all tickers per day), then for each ticker regress its as-of daily returns on that market series (a 1-factor OLS slope+intercept), take the residuals, and set `resid_mom = mean(residual returns)` (the residual-momentum signal). Store it into each ticker's factor dict (the cache stores the whole dict, keyed including `resid_days` via the extended `_lookback_cache_key`).
  - Test: a stock that moves exactly with the market → residual ≈ 0; a stock with idiosyncratic drift on top of the market → positive `resid_mom`; no-lookahead (post-asof bars excluded); <2 overlapping returns → `None`. Commit `feat(self-evolve): residual-momentum factor (market-residualized, cross-sectional)`.

---

## Phase 4 — integration

### Task 12: weights, kernel doc, smoke, regression

**Files:** Modify `strategy_skill/skill_config.yaml` (final weight balance) + `strategy_skill/SKILL.md` (list the 11 factors + papers). Test: `v2/self_evolve/test_factors_partc.py` (smoke).

- [ ] **Step 1: smoke test** — on a synthetic multi-ticker bundle with line items, `compute_factors` returns all 11 keys for a healthy ticker; `generate_holdings` with a config that up-weights a NEW factor (e.g. `factor_weights.value`) yields DIFFERENT holdings than baseline (proves the factor participates, not neutral). Assert the Part-B cache still gives identical values cached vs fresh for the new factors (extends `test_factors_cache.py` intent).

- [ ] **Step 2:** implement the final `skill_config.yaml` weights (a sensible balanced 11-way default; the loop tunes from here) + update `SKILL.md`.

- [ ] **Step 3: full regression**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/ -q`
Expected: PASS (all prior + the new Part-C tests). Confirm `test_loop.py` (test-never-read) + `test_factors_cache.py` (no-lookahead cache) unchanged & green.

- [ ] **Step 4: commit**
```bash
git add strategy_skill/skill_config.yaml strategy_skill/SKILL.md v2/self_evolve/test_factors_partc.py
git commit -m "feat(self-evolve): balance 11-factor weights + document the factor kernel; Part C complete"
```

---

## Self-Review (against the spec, Part C)

- **Spec coverage:** line-items enrich → Task 1–2; the 11 factors → Tasks 3–11 (4 price/volume + 4 fundamental + the 3 existing carried, value/quality rebuilt); generic `FACTOR_KEYS` plumbing + cache-key extension → Task 3; the inert-factor fix → Task 10; no-lookahead + never-raise re-asserted per factor; weights/doc/smoke → Task 12.
- **Placeholder scan:** formulas are concrete; tests specify the asserted behaviour. The one soft spot — exact yfinance line-item field NAMES (`gross_profit` vs `cost_of_revenue`) — is handled by the derive+fallback chain in Task 8 and the `None`→neutral discipline, so a missing field degrades gracefully (the executor should print one real `search_line_items("AAPL", _LINE_ITEM_FIELDS, today)` while implementing Task 1 to confirm the populated names, and adjust `_LINE_ITEM_FIELDS` if yfinance uses different labels).
- **Type consistency:** the 6 new keys are identical across `config.FACTOR_KEYS`, `factors.FACTOR_KEYS`, `ADJUSTABLE`, `skill_config.yaml`, and `_lookback_cache_key`; `resid_mom` is the only factor computed outside `_compute_one` (documented in Task 11).
- **Cache correctness:** Task 3 extends `_lookback_cache_key` with all 4 new windows in the SAME task that registers them — no window can change without invalidating the cache.

## Execution Handoff

Larger than Part B (12 tasks, multi-file). Recommended: **Subagent-Driven** (fresh opus subagent per task + two-stage review) given the factor-math density and the no-lookahead invariant per factor — though Inline is fine if you prefer to watch each factor land. Phase 1–2 should land before Phase 3 (the factors depend on the data path + the registered keys). `resid_mom` (Task 11) is the riskiest; it may be deferred to a follow-up without blocking the other 10 if its cross-sectional cost or design needs more thought.
