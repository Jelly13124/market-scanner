"""Phase 6C: verdict rules from IS vs OOS metrics."""

from __future__ import annotations

from src.lab.engine.metrics import Metrics
from src.lab.engine.verdict import make_verdict, Verdict


def _m(cagr=0.15, n_trades=20, **kw):
    base = dict(total_return=cagr, cagr=cagr, sharpe=1.0, sortino=1.2,
                 max_drawdown=-0.15, calmar=cagr/0.15,
                 win_rate=0.55, profit_factor=1.6,
                 avg_holding_days=15, n_trades=n_trades, exposure_pct=0.5)
    base.update(kw)
    return Metrics(**base)


def test_insufficient_trades_in_either_period():
    v = make_verdict(_m(n_trades=2), _m(n_trades=20), benchmark_cagr=0.10)
    assert v.label == "insufficient"
    v2 = make_verdict(_m(n_trades=20), _m(n_trades=2), benchmark_cagr=0.10)
    assert v2.label == "insufficient"


def test_oos_loses_money_rejects():
    v = make_verdict(_m(cagr=0.20), _m(cagr=-0.05), benchmark_cagr=0.10)
    assert v.label == "reject"
    assert "out-of-sample" in v.text.lower() or "oos" in v.text.lower()


def test_heavy_degradation_overfit():
    # IS +20% CAGR, OOS +5% → ratio 0.25 < 0.4
    v = make_verdict(_m(cagr=0.20), _m(cagr=0.05), benchmark_cagr=0.10)
    assert v.label == "overfit"


def test_weak_degradation():
    # IS +20%, OOS +10% → ratio 0.5 < 0.6
    v = make_verdict(_m(cagr=0.20), _m(cagr=0.10), benchmark_cagr=0.05)
    assert v.label == "weak"


def test_underperforms_benchmark():
    # IS +12%, OOS +8% → ratio 0.67 OK, but SPY +15%
    v = make_verdict(_m(cagr=0.12), _m(cagr=0.08), benchmark_cagr=0.15)
    assert v.label == "underperform_bench"


def test_positive_edge():
    # IS +20%, OOS +18% → ratio 0.9 ok, OOS beats SPY 0.10
    v = make_verdict(_m(cagr=0.20), _m(cagr=0.18), benchmark_cagr=0.10)
    assert v.label == "positive_edge"
