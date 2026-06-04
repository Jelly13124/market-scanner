import math
from v2.workflow_backtest.attribution import ab_welch, attach_forward_returns
from v2.workflow_backtest.types import Decision
from v2.data.models import Price


def _p(t, c):
    return Price(open=c, close=c, high=c, low=c, volume=100, time=t)


class _DecliningFD:
    """Fake fd whose get_prices returns a steadily declining series so the
    forward return over any window is negative."""

    def __init__(self, start=100.0, step=-1.0):
        self._start = start
        self._step = step

    def get_prices(self, ticker, start, end, **kw):
        import datetime as _dt

        d0 = _dt.date.fromisoformat(start[:10])
        d1 = _dt.date.fromisoformat(end[:10])
        bars = []
        i = 0
        d = d0
        while d <= d1:
            bars.append(_p(d.isoformat(), self._start + self._step * i))
            d += _dt.timedelta(days=1)
            i += 1
        return bars


def test_short_on_faller_yields_positive_signal_return():
    # SHORT a stock whose price falls → ret_21d < 0 but signal_ret_21d > 0.
    fd = _DecliningFD(start=100.0, step=-1.0)
    decisions = [Decision(ticker="AAA", action="short", quantity=0, confidence=70)]
    rows = attach_forward_returns(decisions, fd, scan_date="2025-01-02", windows=(21,),
                                  benchmark_prices=[])
    assert len(rows) == 1
    row = rows[0]
    assert row["side"] == -1
    assert row["ret_21d"] is not None and row["ret_21d"] < 0
    # signal return = side * ret → positive for a correct short.
    assert row["signal_ret_21d"] is not None and row["signal_ret_21d"] > 0
    assert math.isclose(row["signal_ret_21d"], -row["ret_21d"], rel_tol=0, abs_tol=1e-12)


def test_buy_signal_return_equals_raw_return():
    # BUY → side=+1 so signal_ret == ret (long takes the raw move).
    fd = _DecliningFD(start=100.0, step=+2.0)  # rising series → ret > 0
    decisions = [Decision(ticker="BBB", action="buy", quantity=0, confidence=80)]
    rows = attach_forward_returns(decisions, fd, scan_date="2025-01-02", windows=(21,),
                                  benchmark_prices=[])
    assert len(rows) == 1
    row = rows[0]
    assert row["side"] == 1
    assert row["ret_21d"] is not None and row["ret_21d"] > 0
    assert math.isclose(row["signal_ret_21d"], row["ret_21d"], rel_tol=0, abs_tol=1e-12)


def test_hold_and_sell_excluded_from_attribution():
    fd = _DecliningFD()
    decisions = [
        Decision(ticker="AAA", action="hold", quantity=0),
        Decision(ticker="BBB", action="sell", quantity=0),
        Decision(ticker="CCC", action="cover", quantity=0),
        Decision(ticker="DDD", action="buy", quantity=0),
    ]
    rows = attach_forward_returns(decisions, fd, scan_date="2025-01-02", windows=(21,),
                                  benchmark_prices=[])
    assert [r["ticker"] for r in rows] == ["DDD"]


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
