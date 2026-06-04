from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.workflow_backtest.asof_dispatcher import AsOfDispatcher


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
