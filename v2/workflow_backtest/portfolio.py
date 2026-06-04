"""Equal-weight, weekly-rebalance, fixed-hold portfolio simulator.

Walks an ordered trading-day calendar, entering the BUY decisions emitted on
each scan_date and exiting each position after a fixed number of trading days.
Positions are marked to market daily to build an equity curve, which is fed to
``PerformanceMetricsCalculator.compute_metrics`` for sharpe/sortino/drawdown.

Accounting model (no leverage, fractional shares):

  * At each trading day ``dt`` (in calendar order):
      1. EXIT any open position whose entry was ``hold_days`` trading-days ago —
         sell at ``dt`` close, deduct cost on the sell notional, return proceeds
         to cash.
      2. ENTER if ``dt`` is a scan_date with BUY decisions — split the
         CURRENTLY-AVAILABLE cash equally across the BUY tickers that have a
         price on ``dt``, buy fractional shares at ``dt`` close, deduct cost on
         the buy notional.
      3. MARK all open positions to ``dt`` close → portfolio value =
         cash + sum(shares * close).
  * Cost per leg = notional * (commission_bps + slippage_bps) / 1e4.
  * A trading day with no exits and no decisions leaves cash/positions
    unchanged (value is flat when nothing is held).
"""

from __future__ import annotations

from src.backtesting.metrics import PerformanceMetricsCalculator


def simulate(
    decisions_by_date,
    prices_by_ticker,
    *,
    trading_days,
    hold_days=21,
    starting_capital=100_000.0,
    commission_bps=5.0,
    slippage_bps=5.0,
):
    """Simulate an equal-weight weekly-rebalance fixed-hold portfolio.

    Args:
        decisions_by_date: ``{scan_date: list[Decision]}`` — BUY decisions to
            ENTER on that date (non-"buy" actions are skipped).
        prices_by_ticker: ``{ticker: {date: close}}`` — daily closes used for
            entry/exit/mark-to-market.
        trading_days: ordered ``list[str]`` — the calendar to walk; equity is
            marked once per day.
        hold_days: trading-days to hold each position before exiting.
        starting_capital: initial cash.
        commission_bps / slippage_bps: per-leg cost in basis points of notional.

    Returns:
        ``{"equity_curve": list[dict], "metrics": dict, "trades": list[dict]}``
        where each equity-curve point is ``{"Date", "Portfolio Value"}``.
    """
    cost_rate = (commission_bps + slippage_bps) / 1e4

    cash = float(starting_capital)
    # Open positions keyed by ticker: {ticker: {"shares", "entry_idx", "entry_date", "entry_price"}}
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    equity_curve: list[dict] = []

    def price_on(ticker: str, date: str):
        series = prices_by_ticker.get(ticker)
        if not series:
            return None
        return series.get(date)

    for idx, dt in enumerate(trading_days):
        # (1) EXIT positions whose hold window has elapsed (entered hold_days ago).
        for ticker in list(open_positions.keys()):
            pos = open_positions[ticker]
            if idx - pos["entry_idx"] >= hold_days:
                exit_price = price_on(ticker, dt)
                if exit_price is None:
                    # No price to exit on today — keep the position; try again later.
                    continue
                notional = pos["shares"] * exit_price
                cash += notional - notional * cost_rate
                trades.append(
                    {
                        "ticker": ticker,
                        "entry_date": pos["entry_date"],
                        "exit_date": dt,
                        "entry_price": pos["entry_price"],
                        "exit_price": exit_price,
                        "shares": pos["shares"],
                    }
                )
                del open_positions[ticker]

        # (2) ENTER new BUYs if dt is a scan_date with decisions.
        day_decisions = decisions_by_date.get(dt) or []
        buys = [d for d in day_decisions if getattr(d, "action", None) == "buy"]
        priceable = [d for d in buys if price_on(d.ticker, dt) is not None]
        if priceable:
            alloc = cash / len(priceable)
            for d in priceable:
                entry_price = price_on(d.ticker, dt)
                # Equal cash split; cost is taken out of the allocated slice so we
                # never spend more cash than available.
                shares = alloc / (entry_price * (1.0 + cost_rate))
                notional = shares * entry_price
                cash -= notional + notional * cost_rate
                if d.ticker in open_positions:
                    # Already holding (re-entry on same ticker): average in.
                    existing = open_positions[d.ticker]
                    total_shares = existing["shares"] + shares
                    existing["entry_price"] = (
                        existing["entry_price"] * existing["shares"] + entry_price * shares
                    ) / total_shares
                    existing["shares"] = total_shares
                    existing["entry_idx"] = idx
                    existing["entry_date"] = dt
                else:
                    open_positions[d.ticker] = {
                        "shares": shares,
                        "entry_idx": idx,
                        "entry_date": dt,
                        "entry_price": entry_price,
                    }

        # (3) MARK to market: portfolio value = cash + held shares * today's close.
        holdings_value = 0.0
        for ticker, pos in open_positions.items():
            mark = price_on(ticker, dt)
            if mark is None:
                # No mark today — fall back to last known entry price to stay no-NaN.
                mark = pos["entry_price"]
            holdings_value += pos["shares"] * mark
        equity_curve.append({"Date": dt, "Portfolio Value": cash + holdings_value})

    metrics = PerformanceMetricsCalculator().compute_metrics(equity_curve)

    return {"equity_curve": equity_curve, "metrics": metrics, "trades": trades}
