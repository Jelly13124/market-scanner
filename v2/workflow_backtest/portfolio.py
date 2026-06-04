"""Equal-weight, weekly-rebalance, fixed-hold portfolio simulator (long+short).

Walks an ordered trading-day calendar, entering the directional decisions
(buy → long, short → short) emitted on each scan_date and exiting each position
after a fixed number of trading days. Positions are marked to market daily to
build an equity curve, which is fed to
``PerformanceMetricsCalculator.compute_metrics`` for sharpe/sortino/drawdown.

Accounting model — P&L-based so long and short are handled uniformly:

    equity(t) = starting_capital + realized_pnl
                + sum(side * shares * (price_t - entry_price) for open positions)

  * At each trading day ``dt`` (in calendar order):
      1. EXIT any open position whose entry was ``hold_days`` trading-days ago —
         realize ``side * shares * (exit_price - entry_price)`` into realized_pnl
         and charge the exit-leg cost on the exit notional.
      2. ENTER if ``dt`` is a scan_date with directional decisions — split an
         equal CASH NOTIONAL across the buy/short tickers that have a price on
         ``dt`` (notional = starting_capital / n_bets), buy/short fractional
         shares at ``dt`` close, charge the entry-leg cost on the notional.
      3. MARK all open positions to ``dt`` close → equity per the formula above.
  * Cost per leg = notional * (commission_bps + slippage_bps) / 1e4, charged to
    realized_pnl at BOTH entry and exit.
  * A short's unrealized/realized P&L uses ``side = -1`` so a price DROP is a
    gain; a long uses ``side = +1``. Notional is freed (position closed) at exit.
  * A trading day with no exits and no decisions leaves equity unchanged.
"""

from __future__ import annotations

import datetime as _dt

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
    """Simulate an equal-weight weekly-rebalance fixed-hold portfolio (long+short).

    Args:
        decisions_by_date: ``{scan_date: list[Decision]}`` — directional
            decisions to ENTER on that date. ``buy`` opens a long (side=+1),
            ``short`` opens a short (side=-1); ``hold``/``sell``/``cover`` are
            skipped (not opening bets).
        prices_by_ticker: ``{ticker: {date: close}}`` — daily closes used for
            entry/exit/mark-to-market.
        trading_days: ordered ``list[str]`` — the calendar to walk; equity is
            marked once per day.
        hold_days: trading-days to hold each position before exiting.
        starting_capital: initial capital (P&L baseline).
        commission_bps / slippage_bps: per-leg cost in basis points of notional.

    Returns:
        ``{"equity_curve": list[dict], "metrics": dict, "trades": list[dict]}``
        where each equity-curve point is ``{"Date", "Portfolio Value"}`` and
        each trade row includes a ``"side"`` (+1 long / -1 short).
    """
    cost_rate = (commission_bps + slippage_bps) / 1e4
    side_by_action = {"buy": 1, "short": -1}

    realized_pnl = 0.0
    # Open positions keyed by ticker:
    #   {ticker: {"side", "shares", "entry_idx", "entry_date", "entry_price"}}
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
                side = pos["side"]
                # Realize the directional P&L; charge exit-leg cost on the notional.
                realized_pnl += side * pos["shares"] * (exit_price - pos["entry_price"])
                exit_notional = pos["shares"] * exit_price
                realized_pnl -= exit_notional * cost_rate
                trades.append(
                    {
                        "ticker": ticker,
                        "side": side,
                        "entry_date": pos["entry_date"],
                        "exit_date": dt,
                        "entry_price": pos["entry_price"],
                        "exit_price": exit_price,
                        "shares": pos["shares"],
                    }
                )
                del open_positions[ticker]

        # (2) ENTER new directional bets if dt is a scan_date with decisions.
        day_decisions = decisions_by_date.get(dt) or []
        bets = [d for d in day_decisions if side_by_action.get(getattr(d, "action", None)) is not None]
        priceable = [d for d in bets if price_on(d.ticker, dt) is not None]
        if priceable:
            # Equal CASH NOTIONAL per bet, sized off starting capital so long and
            # short legs get the same gross exposure regardless of prior P&L.
            notional = float(starting_capital) / len(priceable)
            for d in priceable:
                side = side_by_action[d.action]
                entry_price = price_on(d.ticker, dt)
                shares = notional / entry_price
                # Entry-leg cost hits realized P&L now; the notional is "deployed"
                # and freed at exit (no separate cash ledger — equity is P&L-based).
                realized_pnl -= notional * cost_rate
                if d.ticker in open_positions and open_positions[d.ticker]["side"] == side:
                    # Already holding same-side (re-entry on same ticker): average in.
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
                        "side": side,
                        "shares": shares,
                        "entry_idx": idx,
                        "entry_date": dt,
                        "entry_price": entry_price,
                    }

        # (3) MARK to market: equity = start + realized + sum(unrealized P&L).
        unrealized = 0.0
        for ticker, pos in open_positions.items():
            mark = price_on(ticker, dt)
            if mark is None:
                # No mark today — fall back to entry price (zero unrealized) to stay no-NaN.
                mark = pos["entry_price"]
            unrealized += pos["side"] * pos["shares"] * (mark - pos["entry_price"])
        equity_curve.append({"Date": dt, "Portfolio Value": float(starting_capital) + realized_pnl + unrealized})

    # compute_metrics expects datetime "Date" (PortfolioValuePoint contract) so
    # its max_drawdown_date .strftime works; the public curve keeps ISO strings.
    def _to_dt(d):
        return _dt.datetime.fromisoformat(d[:10]) if isinstance(d, str) else d

    metrics_curve = [{"Date": _to_dt(p["Date"]), "Portfolio Value": p["Portfolio Value"]} for p in equity_curve]
    metrics = PerformanceMetricsCalculator().compute_metrics(metrics_curve)

    return {"equity_curve": equity_curve, "metrics": metrics, "trades": trades}
