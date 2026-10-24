from v2.workflow_backtest.portfolio import simulate
from v2.workflow_backtest.types import Decision

def test_single_buy_held_then_marked():
    # Buy AAA on day0 at 100, hold 2 trading days, price rises to 110.
    trading_days = ["2025-01-02", "2025-01-03", "2025-01-04"]
    prices = {"AAA": {"2025-01-02": 100.0, "2025-01-03": 105.0, "2025-01-04": 110.0}}
    decisions = {"2025-01-02": [Decision(ticker="AAA", action="buy", quantity=0)]}
    res = simulate(decisions, prices, trading_days=trading_days, hold_days=2,
                   starting_capital=100_000.0, commission_bps=5.0, slippage_bps=5.0)
    ec = res["equity_curve"]
    assert [p["Date"] for p in ec] == trading_days
    # all-in on AAA at 100 (minus ~10bps buy cost), marked at 110 on the last day.
    # gross ~ +10%; final value should be > starting (costs are ~0.1% per leg).
    assert ec[-1]["Portfolio Value"] > 105_000  # well above costs, below perfect 110k
    assert ec[-1]["Portfolio Value"] < 110_000
    assert "sharpe_ratio" in res["metrics"] and "max_drawdown" in res["metrics"]

def test_no_decisions_holds_cash_flat():
    trading_days = ["2025-01-02", "2025-01-03"]
    res = simulate({}, {}, trading_days=trading_days, hold_days=21, starting_capital=50_000.0)
    ec = res["equity_curve"]
    assert all(abs(p["Portfolio Value"] - 50_000.0) < 1e-6 for p in ec)

def test_single_short_on_faller_nets_gain():
    # SHORT AAA on day0 at 100, hold 2 trading days, price FALLS to 90.
    # A correct short should END ABOVE starting capital (gross +10% short P&L,
    # minus ~0.1%/leg costs).
    trading_days = ["2025-01-02", "2025-01-03", "2025-01-04"]
    prices = {"AAA": {"2025-01-02": 100.0, "2025-01-03": 95.0, "2025-01-04": 90.0}}
    decisions = {"2025-01-02": [Decision(ticker="AAA", action="short", quantity=0)]}
    res = simulate(decisions, prices, trading_days=trading_days, hold_days=2,
                   starting_capital=100_000.0, commission_bps=5.0, slippage_bps=5.0)
    ec = res["equity_curve"]
    assert [p["Date"] for p in ec] == trading_days
    # +10% gross short P&L, net of costs → above starting but below perfect 110k.
    assert ec[-1]["Portfolio Value"] > 105_000
    assert ec[-1]["Portfolio Value"] < 110_000
    # the trade row records the short side.
    assert res["trades"] and res["trades"][0]["side"] == -1

def test_short_on_riser_loses():
    # SHORT a stock that RISES 100→110 should END BELOW starting capital.
    trading_days = ["2025-01-02", "2025-01-03", "2025-01-04"]
    prices = {"AAA": {"2025-01-02": 100.0, "2025-01-03": 105.0, "2025-01-04": 110.0}}
    decisions = {"2025-01-02": [Decision(ticker="AAA", action="short", quantity=0)]}
    res = simulate(decisions, prices, trading_days=trading_days, hold_days=2,
                   starting_capital=100_000.0, commission_bps=5.0, slippage_bps=5.0)
    ec = res["equity_curve"]
    assert ec[-1]["Portfolio Value"] < 100_000

def test_hold_and_sell_not_entered():
    # Only buy/short open positions; hold/sell/cover are ignored → flat cash.
    trading_days = ["2025-01-02", "2025-01-03"]
    prices = {"AAA": {"2025-01-02": 100.0, "2025-01-03": 110.0}}
    decisions = {"2025-01-02": [
        Decision(ticker="AAA", action="hold", quantity=0),
        Decision(ticker="AAA", action="sell", quantity=0),
        Decision(ticker="AAA", action="cover", quantity=0),
    ]}
    res = simulate(decisions, prices, trading_days=trading_days, hold_days=21,
                   starting_capital=100_000.0)
    ec = res["equity_curve"]
    assert all(abs(p["Portfolio Value"] - 100_000.0) < 1e-6 for p in ec)
    assert res["trades"] == []
