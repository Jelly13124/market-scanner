"""Factor-value cache (Part B): correctness, hits, lookback-keyed invalidation.

Offline + deterministic — synthetic ``SimpleNamespace`` bundles, no network/LLM.
The synthetic price history spans well over ``momentum_days`` so ``_compute_one``
returns REAL factor values (not ``None``), making the cache assertions meaningful.
"""

import os
from datetime import date, timedelta
from types import SimpleNamespace

import v2.self_evolve.factors as fmod
from v2.self_evolve.config import apply_delta, load_config
from v2.self_evolve.factors import compute_factors

_SKILL_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "strategy_skill", "skill_config.yaml")
ASOF = "2021-06-01"


def _price(d, c, v=1_000_000):
    return SimpleNamespace(time=d, close=float(c), volume=float(v))


def _bundle(prices, metrics=None):
    return SimpleNamespace(prices=prices, metrics_history=metrics or [])


def _days(start: str, n: int) -> list[str]:
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _bundles():
    # ~1000 consecutive daily bars from 2019 -> comfortably > momentum_days(252)
    # of history before ASOF (2021-06-01), so all price factors compute.
    days = _days("2019-01-01", 1000)
    a = _bundle([_price(d, 100 + i * 0.1) for i, d in enumerate(days)])
    b = _bundle([_price(d, 300 - i * 0.05) for i, d in enumerate(days)])
    return {"AAA": a, "BBB": b}


def _cfg():
    return load_config(_SKILL_CONFIG)


def test_cached_equals_fresh():
    bundles, cfg = _bundles(), _cfg()
    fresh = compute_factors(bundles, ASOF, cfg)
    assert fresh, "synthetic bundles should yield real (non-empty) factor rows"
    cache = {}
    cached = compute_factors(bundles, ASOF, cfg, cache=cache)
    assert cached == fresh
    assert len(cache) >= 1  # something was stored


def test_second_call_is_a_pure_hit(monkeypatch):
    bundles, cfg = _bundles(), _cfg()
    cache = {}
    compute_factors(bundles, ASOF, cfg, cache=cache)

    calls = []
    orig = fmod._compute_one
    monkeypatch.setattr(fmod, "_compute_one", lambda b, a, c: calls.append(1) or orig(b, a, c))
    again = compute_factors(bundles, ASOF, cfg, cache=cache)
    assert calls == []  # zero recomputes on the second call with the same cache
    assert again == compute_factors(bundles, ASOF, cfg)  # still correct


def test_lookback_change_invalidates_and_matches_fresh():
    bundles, cfg = _bundles(), _cfg()
    cache = {}
    compute_factors(bundles, ASOF, cfg, cache=cache)
    n_after_first = len(cache)

    # Change EACH lookback _compute_one reads -> a different key -> recompute that matches fresh.
    for path, val in [
        ("lookback.momentum_days", 200),
        ("lookback.vol_days", 40),
        ("lookback.reversal_days", 10),
    ]:
        cfg2 = apply_delta(cfg, {path: val})
        fresh2 = compute_factors(bundles, ASOF, cfg2)
        cached2 = compute_factors(bundles, ASOF, cfg2, cache=cache)
        assert cached2 == fresh2
    assert len(cache) > n_after_first  # new lookbacks added entries, didn't overwrite


def test_generate_holdings_cache_passthrough():
    from v2.self_evolve.strategy_gen import generate_holdings

    bundles, cfg = _bundles(), _cfg()
    no_cache = generate_holdings(bundles, ASOF, cfg)
    cache = {}
    with_cache = generate_holdings(bundles, ASOF, cfg, cache=cache)
    assert with_cache == no_cache  # identical holdings
    assert len(cache) >= 1  # cache was populated via compute_factors


def _sample_bundles():
    # Daily bars 2022..2025 so each monthly rebalance in the 'test' sample (2024+)
    # has >252 days of prior history -> real factor values at every rebalance.
    days = _days("2022-01-01", 1260)
    a = _bundle([_price(d, 100 + i * 0.05) for i, d in enumerate(days)])
    b = _bundle([_price(d, 300 - i * 0.03) for i, d in enumerate(days)])
    return {"AAA": a, "BBB": b}


def test_backtest_cache_same_metrics_and_no_recompute(monkeypatch):
    from v2.self_evolve.backtest import backtest

    bundles, cfg = _sample_bundles(), _cfg()
    plain = backtest(bundles, cfg, "test")
    cache = {}
    cached = backtest(bundles, cfg, "test", cache=cache)
    assert cached == plain  # identical metrics
    assert len(cache) >= 1  # factors were memoized across the run's rebalances

    calls = []
    orig = fmod._compute_one
    monkeypatch.setattr(fmod, "_compute_one", lambda b, a, c: calls.append(1) or orig(b, a, c))
    again = backtest(bundles, cfg, "test", cache=cache)  # same cache, same lookbacks
    assert calls == []  # ZERO recomputes the second time
    assert again == plain


def test_evolve_shares_one_cache_across_iterations(monkeypatch, tmp_path):
    import shutil

    from v2.self_evolve.loop import evolve

    bundles, cfg = _sample_bundles(), _cfg()
    base_dir = str(tmp_path)
    shutil.copy(_SKILL_CONFIG, os.path.join(base_dir, "skill_config.yaml"))

    # Stub proposer: weight-only deltas (lookbacks unchanged) -> every iteration
    # is a pure cache hit after the baseline computes the panel once.
    deltas = iter(
        [
            {"path": "factor_weights.momentum", "value": 0.4, "hypothesis": "w"},
            {"path": "factor_weights.reversal", "value": 0.25, "hypothesis": "w"},
        ]
    )

    def propose_fn(skill_md, config, val_history, *, llm_fn=None):
        return next(deltas, None)

    calls = []
    orig = fmod._compute_one
    monkeypatch.setattr(fmod, "_compute_one", lambda b, a, c: calls.append((id(b), a)) or orig(b, a, c))

    evolve(bundles, cfg, iterations=2, base_dir=base_dir, propose_fn=propose_fn)

    # Baseline + 2 weight-only rounds = 3 train+val passes, but lookbacks never
    # change -> each (bundle, asof) computed ONCE, not 3x.
    assert len(calls) == len(set(calls)), f"expected no recomputes: {len(calls)} calls, {len(set(calls))} distinct"
