import math
from v2.workflow_backtest.attribution import ab_welch

def test_ab_welch_positive_when_a_beats_b():
    r = ab_welch([0.05, 0.04, 0.06], [0.0, -0.01, 0.01])
    assert r["n_a"] == 3 and r["n_b"] == 3
    assert math.isclose(r["diff"], 0.05 - 0.0, rel_tol=0, abs_tol=1e-9) or r["diff"] > 0.04
    assert r["t"] is not None and r["t"] > 0

def test_ab_welch_equal_lists_zero_t():
    r = ab_welch([0.01, 0.02, 0.03], [0.01, 0.02, 0.03])
    assert abs(r["diff"]) < 1e-12
    assert abs(r["t"]) < 1e-9

def test_ab_welch_insufficient_samples():
    r = ab_welch([0.01], [0.02, 0.03])
    assert r["t"] is None
    assert r["n_a"] == 1 and r["n_b"] == 2

def test_ab_welch_drops_none():
    r = ab_welch([0.05, None, 0.06], [0.0, 0.01, None])
    assert r["n_a"] == 2 and r["n_b"] == 2
