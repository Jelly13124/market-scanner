# Self-Evolve Factor-Value Cache (Part B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional factor-value cache so a self-evolve backtest stops recomputing immutable factor values every iteration (~17 min/iter → seconds), with no-lookahead preserved by construction.

**Architecture:** A plain dict cache, created once in `evolve()` and threaded `evolve → backtest → generate_holdings → compute_factors`. `compute_factors` wraps its `_compute_one(bundle, asof, config)` call: key `(ticker, asof_iso, lookback_tuple)`; on hit return the stored factor dict (or `None`), on miss compute then store. `_compute_one`'s math is untouched. Every seam param defaults to `cache=None`, so all existing callers/tests are unaffected; `evolve` only binds a cache when no `backtest_fn` is injected (so injected test stubs never see a `cache` kwarg).

**Tech Stack:** Python (anaconda interpreter), pytest, the existing `v2/self_evolve/` package.

**Global constraints (every task):**
- Python: `C:\Users\Jerry\anaconda3\python.exe` (Poetry not on PATH).
- Tests: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest <path> -q` — OFFLINE only (synthetic `SimpleNamespace` bundles; no network/LLM).
- Commit per task; conventional message; **NO Co-Authored-By**; never `--no-verify`; explicit `git add <paths>` (never `-A`); never stage `.claude/settings.local.json`.
- `black` on touched `.py` before commit. Branch `main`.

**Anchored current signatures / call sites (verified — do not re-derive):**
- `factors.py:144` `def _compute_one(bundle, asof: str, config) -> dict[str, float] | None`
- `factors.py:239` `def compute_factors(bundles, asof: str, config) -> dict[str, dict[str, float]]`; loop at `265-268` calls `_compute_one(bundle, asof_iso, config)`; `asof_iso = _parse_iso(asof)` at `261`.
- `strategy_gen.py:306` `factor_rows = compute_factors(sub_bundles, asof_iso, config)`
- `backtest.py:128` `def backtest(bundles, config, sample: str) -> dict`; `195` `weights = generate_holdings(bundles, entry, config) or {}`
- `loop.py:180` `def evolve(bundles, base_config, *, iterations, base_dir, skill_md="", propose_fn=None, backtest_fn=None)`; `225` `backtest_fn = backtest_fn or _backtest_mod.backtest`; calls at `232/233/301` (+ the val call right after `301`).

**Correctness invariant (load-bearing):** the lookback tuple in the cache key MUST include every lookback `_compute_one` reads — for Part B that is `momentum_days, vol_days, reversal_days` (value/quality use the fixed 60-day lag, no window). If a lookback `_compute_one` uses is omitted from the key, a cached value goes stale when that lookback changes. (Part C extends both `_compute_one` and this tuple together.)

---

## Task 1: cache in `compute_factors`

**Files:**
- Modify: `v2/self_evolve/factors.py` (add `_lookback_cache_key` + `cache=None` to `compute_factors`)
- Test: `v2/self_evolve/test_factors_cache.py` (create)

- [ ] **Step 1: Write the failing tests** — create `v2/self_evolve/test_factors_cache.py`:

```python
"""Factor-value cache: correctness, hits, and lookback-keyed invalidation."""
from types import SimpleNamespace

import v2.self_evolve.factors as fmod
from v2.self_evolve.config import load_config, apply_delta
from v2.self_evolve.factors import compute_factors


def _price(d, c, v=1_000_000):
    return SimpleNamespace(time=d, close=float(c), volume=float(v))


def _bundle(prices, metrics=None):
    return SimpleNamespace(prices=prices, metrics_history=metrics or [])


def _bundles():
    # ~320 daily bars so momentum(252)/vol(63)/reversal(21) all compute.
    days = [f"2021-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 28)]
    base = days[:300]
    a = _bundle([_price(d, 100 + i * 0.5) for i, d in enumerate(base)])
    b = _bundle([_price(d, 200 - i * 0.3) for i, d in enumerate(base)])
    return {"AAA": a, "BBB": b}


def _cfg():
    # Uses the repo baseline config (momentum_days/vol_days/reversal_days present).
    import os

    return load_config(os.path.join("strategy_skill", "skill_config.yaml"))


def test_cached_equals_fresh():
    bundles, cfg = _bundles(), _cfg()
    asof = "2021-09-15"
    fresh = compute_factors(bundles, asof, cfg)
    cache = {}
    cached = compute_factors(bundles, asof, cfg, cache=cache)
    assert cached == fresh
    assert len(cache) >= 1  # something was stored


def test_second_call_is_a_pure_hit(monkeypatch):
    bundles, cfg = _bundles(), _cfg()
    asof = "2021-09-15"
    cache = {}
    compute_factors(bundles, asof, cfg, cache=cache)

    calls = []
    orig = fmod._compute_one
    monkeypatch.setattr(fmod, "_compute_one", lambda b, a, c: calls.append(1) or orig(b, a, c))
    again = compute_factors(bundles, asof, cfg, cache=cache)
    assert calls == []  # zero recomputes on the second call with the same cache
    assert again == compute_factors(bundles, asof, cfg)  # still correct


def test_lookback_change_invalidates_and_matches_fresh():
    bundles, cfg = _bundles(), _cfg()
    asof = "2021-09-15"
    cache = {}
    compute_factors(bundles, asof, cfg, cache=cache)
    n_after_first = len(cache)

    # Change EACH lookback _compute_one reads -> a different key -> recompute that matches fresh.
    for path, val in [
        ("lookback.momentum_days", 200),
        ("lookback.vol_days", 40),
        ("lookback.reversal_days", 10),
    ]:
        cfg2 = apply_delta(cfg, {path: val})
        fresh2 = compute_factors(bundles, asof, cfg2)
        cached2 = compute_factors(bundles, asof, cfg2, cache=cache)
        assert cached2 == fresh2
    assert len(cache) > n_after_first  # new lookbacks added entries, didn't overwrite
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py -q`
Expected: FAIL — `compute_factors() got an unexpected keyword argument 'cache'`.

- [ ] **Step 3: Implement** — in `v2/self_evolve/factors.py`, add this helper just above `compute_factors` (line ~239):

```python
def _lookback_cache_key(config) -> tuple:
    """The lookbacks _compute_one consumes, in a fixed order — the cache key's
    lookback component. MUST list every window _compute_one reads (Part B:
    momentum/vol/reversal); extend in lockstep when _compute_one gains factors."""
    lb = getattr(config, "lookback", {}) or {}
    return (
        int(lb.get("momentum_days", 0)),
        int(lb.get("vol_days", 0)),
        int(lb.get("reversal_days", 0)),
    )
```

Then change `compute_factors` to accept `cache` and wrap the `_compute_one` call (lines 239 + 265-268):

```python
def compute_factors(bundles, asof: str, config, *, cache=None) -> dict[str, dict[str, float]]:
```
(keep the existing docstring; append a line: `If ``cache`` (a dict) is given, per-(ticker, asof, lookback) factor dicts are memoized — bundles are immutable across a run, so this skips recompute. No-lookahead is preserved because ``asof`` is in the key.`)

Replace the loop body (was lines 265-268):
```python
    lookback_key = _lookback_cache_key(config)
    for ticker, bundle in bundles.items():
        if cache is None:
            factors = _compute_one(bundle, asof_iso, config)
        else:
            key = (ticker, asof_iso, lookback_key)
            if key in cache:
                factors = cache[key]
            else:
                factors = _compute_one(bundle, asof_iso, config)
                cache[key] = factors
        if factors is not None:
            out[ticker] = factors
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: black + commit**

```bash
C:\Users\Jerry\anaconda3\python.exe -m black v2/self_evolve/factors.py v2/self_evolve/test_factors_cache.py
git add v2/self_evolve/factors.py v2/self_evolve/test_factors_cache.py
git commit -m "feat(self-evolve): factor-value cache in compute_factors (lookback-keyed, no-lookahead)"
```

---

## Task 2: thread cache through `generate_holdings`

**Files:**
- Modify: `v2/self_evolve/strategy_gen.py` (line 306 call + signature)
- Test: `v2/self_evolve/test_factors_cache.py` (append)

- [ ] **Step 1: Write the failing test** — append:

```python
def test_generate_holdings_cache_passthrough():
    from v2.self_evolve.strategy_gen import generate_holdings

    bundles, cfg = _bundles(), _cfg()
    asof = "2021-09-15"
    no_cache = generate_holdings(bundles, asof, cfg)
    cache = {}
    with_cache = generate_holdings(bundles, asof, cfg, cache=cache)
    assert with_cache == no_cache          # identical holdings
    assert len(cache) >= 1                  # cache was populated via compute_factors
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py::test_generate_holdings_cache_passthrough -q`
Expected: FAIL — `generate_holdings() got an unexpected keyword argument 'cache'`.

- [ ] **Step 3: Implement** — in `v2/self_evolve/strategy_gen.py`, add `cache=None` to the signature of `generate_holdings` (find `def generate_holdings(bundles, asof`...`, config)` and add `, *, cache=None` before the `)`), and forward it at line 306:

```python
    factor_rows = compute_factors(sub_bundles, asof_iso, config, cache=cache)
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: black + commit**

```bash
C:\Users\Jerry\anaconda3\python.exe -m black v2/self_evolve/strategy_gen.py v2/self_evolve/test_factors_cache.py
git add v2/self_evolve/strategy_gen.py v2/self_evolve/test_factors_cache.py
git commit -m "feat(self-evolve): thread factor cache through generate_holdings"
```

---

## Task 3: thread cache through `backtest`

**Files:**
- Modify: `v2/self_evolve/backtest.py` (line 128 signature + 195 call)
- Test: `v2/self_evolve/test_factors_cache.py` (append)

- [ ] **Step 1: Write the failing test** — append (a SHARED cache across two backtests computes each (ticker, asof, lookback) once):

```python
def _sample_bundles():
    # Daily bars across the whole 'test' sample window so backtest has >=2 rebalances.
    days = [f"{y}-{m:02d}-{d:02d}" for y in (2024, 2025) for m in range(1, 13) for d in (1, 15)]
    a = _bundle([_price(d, 100 + i) for i, d in enumerate(days)])
    b = _bundle([_price(d, 300 - i) for i, d in enumerate(days)])
    return {"AAA": a, "BBB": b}


def test_backtest_cache_same_metrics_and_no_recompute(monkeypatch):
    from v2.self_evolve.backtest import backtest

    bundles, cfg = _sample_bundles(), _cfg()
    plain = backtest(bundles, cfg, "test")
    cache = {}
    cached = backtest(bundles, cfg, "test", cache=cache)
    assert cached == plain                  # identical metrics

    calls = []
    orig = fmod._compute_one
    monkeypatch.setattr(fmod, "_compute_one", lambda b, a, c: calls.append(1) or orig(b, a, c))
    again = backtest(bundles, cfg, "test", cache=cache)  # same cache, same lookbacks
    assert calls == []                       # ZERO recomputes the second time
    assert again == plain
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py::test_backtest_cache_same_metrics_and_no_recompute -q`
Expected: FAIL — `backtest() got an unexpected keyword argument 'cache'`.

- [ ] **Step 3: Implement** — in `v2/self_evolve/backtest.py`:

Signature (line 128):
```python
def backtest(bundles, config, sample: str, *, cache=None) -> dict:
```
Forward at the rebalance call (line 195):
```python
        weights = generate_holdings(bundles, entry, config, cache=cache) or {}
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: black + commit**

```bash
C:\Users\Jerry\anaconda3\python.exe -m black v2/self_evolve/backtest.py v2/self_evolve/test_factors_cache.py
git add v2/self_evolve/backtest.py v2/self_evolve/test_factors_cache.py
git commit -m "feat(self-evolve): thread factor cache through backtest"
```

---

## Task 4: `evolve` binds one shared cache (only when backtest_fn is default)

**Files:**
- Modify: `v2/self_evolve/loop.py` (line 225)
- Test: `v2/self_evolve/test_factors_cache.py` (append)

- [ ] **Step 1: Write the failing test** — append. Drives the REAL default backtest across multiple iterations with a stub proposer and asserts `_compute_one` runs once per (ticker, asof) — NOT once per iteration:

```python
def test_evolve_shares_one_cache_across_iterations(monkeypatch, tmp_path):
    import os, shutil
    from v2.self_evolve.loop import evolve

    bundles, cfg = _sample_bundles(), _cfg()
    base_dir = str(tmp_path)
    shutil.copy(os.path.join("strategy_skill", "skill_config.yaml"), os.path.join(base_dir, "skill_config.yaml"))

    # Stub proposer: weight-only deltas (lookbacks unchanged) so every iteration
    # should be a pure cache hit after the baseline computes the panel once.
    deltas = iter([
        {"path": "factor_weights.momentum", "value": 0.4, "hypothesis": "w"},
        {"path": "factor_weights.reversal", "value": 0.25, "hypothesis": "w"},
    ])
    def propose_fn(skill_md, config, val_history, *, llm_fn=None):
        return next(deltas, None)

    calls = []
    orig = fmod._compute_one
    monkeypatch.setattr(fmod, "_compute_one", lambda b, a, c: calls.append((id(b), a)) or orig(b, a, c))

    evolve(bundles, cfg, iterations=2, base_dir=base_dir, propose_fn=propose_fn)

    # Baseline + 2 weight-only rounds = 3 train+val passes, but lookbacks never
    # change -> each (bundle, asof) computed ONCE, not 3x. So total computes ==
    # the number of DISTINCT (bundle, asof) pairs.
    assert len(calls) == len(set(calls)), f"expected no recomputes, got {len(calls)} for {len(set(calls))} distinct"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py::test_evolve_shares_one_cache_across_iterations -q`
Expected: FAIL — without the shared cache, `_compute_one` runs every iteration, so `len(calls) > len(set(calls))` (the assertion fails).

- [ ] **Step 3: Implement** — in `v2/self_evolve/loop.py`, replace line 225:

```python
    backtest_fn = backtest_fn or _backtest_mod.backtest
```
with:
```python
    # One shared factor cache for the whole run: bundles are immutable across all
    # iterations, so a weight-only delta is a pure hit. Only bound when the DEFAULT
    # backtest is used — an injected backtest_fn keeps its (bundles, config, sample)
    # contract untouched (it never receives a cache kwarg).
    if backtest_fn is None:
        _factor_cache: dict = {}
        backtest_fn = lambda b, c, s: _backtest_mod.backtest(b, c, s, cache=_factor_cache)
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_factors_cache.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: black + commit**

```bash
C:\Users\Jerry\anaconda3\python.exe -m black v2/self_evolve/loop.py v2/self_evolve/test_factors_cache.py
git add v2/self_evolve/loop.py v2/self_evolve/test_factors_cache.py
git commit -m "feat(self-evolve): evolve binds one shared factor cache across iterations"
```

---

## Task 5: full regression + no-lookahead re-assert

**Files:** none (verification only)

- [ ] **Step 1: Full self-evolve suite green**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/ -q`
Expected: PASS (the prior 99 + the 6 new = 105). In particular the existing loop tests (which inject a stub `backtest_fn`) MUST still pass — they never hit the cache closure (it is only bound when `backtest_fn is None`).

- [ ] **Step 2: Confirm the no-lookahead + test-never-read invariant tests are unchanged and green**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest v2/self_evolve/test_loop.py v2/self_evolve/test_factors.py -q`
Expected: PASS. The cache cannot introduce lookahead (asof is in the key); the loop still backtests train+val only.

No commit (verification task).

---

## Self-Review (against the spec, Part B section)

- **Spec coverage:** "factor-value cache, key (ticker, asof, factor, lookback), threaded evolve→backtest→generate_holdings→compute_factors, default None, load-bearing cached==fresh test, call-count proof, no-lookahead preserved" → Tasks 1–4 + the three test families (cached==fresh T1, pure-hit T1/T3, lookback-invalidation T1, call-count across iterations T4). Regression → Task 5.
- **Deliberate simplification (noted):** the spec sketched a *per-factor* key; this plan keys the whole `_compute_one` result by `(ticker, asof, lookback_tuple)` because `_compute_one` is monolithic and all-or-nothing (`None` on short history). This achieves the spec's goal — 100% hit on weight-only deltas (the common case) + correct recompute on any lookback change — with no restructuring of the factor math. A lookback delta recomputes all factors for affected names (acceptable; still vastly cheaper than no cache). Per-factor granularity can be a later refinement if profiling shows lookback-delta cost matters.
- **Placeholder scan:** none — every step has concrete code/commands.
- **Type/name consistency:** `cache` kwarg is keyword-only (`*, cache=None`) and named identically in `compute_factors`, `generate_holdings`, `backtest`; `_lookback_cache_key` defined in Task 1 and used only there; the evolve closure keeps the `(b, c, s)` arity that `backtest_fn` callers at loop.py:232/233/301 already use.

## Execution Handoff

Small, sequential, single-package change. Recommended: **Inline Execution** (executing-plans) — 4 tiny TDD tasks + a verify; subagent overhead isn't worth it. After Part B is green + the speedup confirmed, write Part C's plan (line-items enrich + the 11 factors).
