"""Trading-day enumeration via a benchmark ETF's price bars.

For backtest replay we need to know which calendar days the market was
open between ``start`` and ``end``. Reimplementing US market holiday
logic is fiddle (early closes, weather closures, plus regulatory holidays
that shift between years). Instead we lean on the fact that we already
fetch price data through the same DataClient — query SPY (or the
configured benchmark) for the window and treat every bar's date as a
trading day. This is also how ``v2.event_study.engine`` aligns dates.
"""

from __future__ import annotations

from v2.data.protocol import DataClient


def trading_days_between(
    fd: DataClient,
    *,
    start_date: str,
    end_date: str,
    calendar_ticker: str = "SPY",
) -> list[str]:
    """Return ISO YYYY-MM-DD strings of trading days in [start, end] inclusive.

    Uses ``calendar_ticker``'s actual price bars as the source of truth so
    weekend / holiday / weather-closure exclusions are handled implicitly.
    Empty list when the provider returns no bars (network failure, ticker
    unknown).
    """
    bars = fd.get_prices(calendar_ticker, start_date, end_date)
    if not bars:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for p in sorted(bars, key=lambda b: b.time[:10]):
        d = p.time[:10]
        if d in seen:
            continue
        if start_date <= d <= end_date:
            out.append(d)
            seen.add(d)
    return out
