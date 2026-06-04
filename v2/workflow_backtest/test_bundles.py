from v2.workflow_backtest.bundles import build_bundles
from v2.data.models import Price


class _FakeClient:
    def get_prices(self, ticker, start, end, **kw):
        return [Price(open=10, close=10, high=10, low=10, volume=100, time="2025-01-02"),
                Price(open=11, close=11, high=11, low=11, volume=100, time="2025-01-03")]


def _factory():
    return _FakeClient()


def test_build_bundles_price_only():
    bundles = build_bundles(["AAA"], _factory, "2025-01-01", "2025-02-01", enrich=False)
    assert set(bundles) == {"AAA"}
    assert [p.time for p in bundles["AAA"].prices] == ["2025-01-02", "2025-01-03"]
