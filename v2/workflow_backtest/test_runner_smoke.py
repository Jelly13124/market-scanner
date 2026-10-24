import os
from v2.workflow_backtest.run_workflow_backtest import run_workflow_backtest
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.data.models import Price

def _p(t, c): return Price(open=c, close=c, high=c, low=c, volume=100, time=t)

class _Entry:
    def __init__(self, ticker): self.ticker = ticker; self.rank = 1
    composite_score = 80.0; direction = "bullish"; event_severity = 1.0; triggers = []

def _fake_run_scan(*, tickers, end_date, top_n, provider_factory=None, **kw):
    return [_Entry(t) for t in tickers[:top_n]]

def _stub_hedge_fund(**kw):
    return {"decisions": {t: {"action": "buy", "quantity": 1, "confidence": 75} for t in kw["tickers"]},
            "analyst_signals": {}}

class _FakeFD:
    def __init__(self, prices): self._prices = prices
    def get_prices(self, ticker, start, end, **kw):
        return self._prices.get(ticker, [])

def test_smoke_offline(tmp_path):
    universe = ["AAA", "BBB", "CCC", "DDD"]
    dates = ["2025-03-03", "2025-03-10"]
    cal = ["2025-03-03", "2025-03-10", "2025-04-10"]
    px = {t: [_p("2025-03-03", 100), _p("2025-03-10", 105), _p("2025-04-10", 110)] for t in universe}
    px["SPY"] = [_p("2025-03-03", 400), _p("2025-03-10", 402), _p("2025-04-10", 404)]
    bundles = {t: TickerBundle(ticker=t, prices=px[t]) for t in universe}
    schedule = [{"scan_date": d, "regime_name": "win_2025", "regime_label": "CHOPPY", "is_post_cutoff": True} for d in dates]
    fd = _FakeFD(px)
    summary = run_workflow_backtest(
        universe_tickers=universe, schedule=schedule, model_name="deepseek-v4-pro",
        model_provider="DeepSeek", top_n=2, seed=42, hold_days=21, out_dir=str(tmp_path),
        provider_factory=lambda: _FakeFD(px), fd=fd, bundles=bundles,
        run_scan_fn=_fake_run_scan, run_hedge_fund_fn=_stub_hedge_fund,
    )
    assert summary["n_dates"] == 2
    # both arms ran each date
    for d in dates:
        assert set(summary["arms_ran"][d]) >= {"scanner", "random"}
    assert os.path.exists(summary["report_path"])
    assert os.path.exists(summary["decisions_csv"])
    txt = open(summary["report_path"], encoding="utf-8").read()
    assert "A/B" in txt
