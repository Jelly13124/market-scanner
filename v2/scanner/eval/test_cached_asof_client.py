"""Tests for CachedAsOfClient — the no-lookahead replay data client.

These are the keystone correctness tests for the backtest harness. If the
client ever serves a record dated after the as-of ceiling, every backtest
verdict downstream is contaminated by lookahead bias. Each test pins one
facet of the clamp.

Offline: all fixtures are constructed model instances. No network.
"""

from __future__ import annotations

import pytest

from v2.data.models import (
    AnalystAction,
    AnalystTarget,
    CompanyFacts,
    CompanyNews,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
)
from v2.data.protocol import DataClient
from v2.scanner.eval.cached_asof_client import (
    CachedAsOfClient,
    TickerBundle,
)


def _price(time: str, close: float) -> Price:
    return Price(open=close, close=close, high=close, low=close, volume=1000, time=time)


def _metric(report_period: str) -> FinancialMetrics:
    return FinancialMetrics(ticker="X", report_period=report_period, period="quarterly")


def _earn(report_period: str, filing_date: str) -> EarningsRecord:
    return EarningsRecord(
        ticker="X",
        report_period=report_period,
        source_type="10-Q",
        filing_date=filing_date,
    )


def _insider(filing_date: str, transaction_date: str | None = None) -> InsiderTrade:
    return InsiderTrade(
        ticker="X",
        name="Jane Director",
        filing_date=filing_date,
        transaction_date=transaction_date,
    )


def _news(date: str) -> CompanyNews:
    return CompanyNews(ticker="X", title="t", source="s", date=date)


def _action(action_date: str) -> AnalystAction:
    return AnalystAction(ticker="X", action_date=action_date, firm="Goldman", action="up")


def _target(asof_date: str, mean: float) -> AnalystTarget:
    return AnalystTarget(ticker="X", asof_date=asof_date, target_mean=mean)


# ---------------------------------------------------------------------------
# 1. No lookahead on prices
# ---------------------------------------------------------------------------


def test_no_lookahead_prices():
    bundle = TickerBundle(
        ticker="X",
        prices=[
            _price("2024-01-01", 100.0),
            _price("2024-01-02", 101.0),
            _price("2024-01-03", 102.0),
        ],
    )
    client = CachedAsOfClient(bundle)
    client.set_asof("2024-01-02")

    out = client.get_prices("X", "2024-01-01", "2024-12-31")
    times = [p.time for p in out]
    assert times == ["2024-01-01", "2024-01-02"]
    # The future bar is clamped away despite end_date reaching into the future.
    assert "2024-01-03" not in times


# ---------------------------------------------------------------------------
# 2. set_asof required
# ---------------------------------------------------------------------------


def test_set_asof_required():
    bundle = TickerBundle(ticker="X", prices=[_price("2024-01-01", 100.0)])
    client = CachedAsOfClient(bundle)
    with pytest.raises(RuntimeError):
        client.get_prices("X", "2024-01-01", "2024-12-31")


# ---------------------------------------------------------------------------
# 3. 60-day fundamental availability lag
# ---------------------------------------------------------------------------


def test_fundamental_60d_lag():
    bundle = TickerBundle(ticker="X", metrics_history=[_metric("2024-03-31")])
    client = CachedAsOfClient(bundle)

    # 2024-04-15 is only ~15 days after the period end — statement not yet "known".
    client.set_asof("2024-04-15")
    assert client.get_financial_metrics("X", "2024-04-15") == []

    # 2024-06-30 is well past period_end + 60d — now visible.
    client.set_asof("2024-06-30")
    out = client.get_financial_metrics("X", "2024-06-30")
    assert len(out) == 1
    assert out[0].report_period == "2024-03-31"


# ---------------------------------------------------------------------------
# 4. Earnings history as-of + newest-first ordering
# ---------------------------------------------------------------------------


def test_earnings_history_asof_and_order():
    bundle = TickerBundle(
        ticker="X",
        earnings_history=[
            _earn("2023-12-31", "2024-01-20"),
            _earn("2024-03-31", "2024-04-20"),
        ],
    )
    client = CachedAsOfClient(bundle)

    client.set_asof("2024-02-01")
    out = client.get_earnings_history("X")
    assert [e.filing_date for e in out] == ["2024-01-20"]

    client.set_asof("2024-05-01")
    out = client.get_earnings_history("X")
    # Both visible, newest filing first.
    assert [e.filing_date for e in out] == ["2024-04-20", "2024-01-20"]


# ---------------------------------------------------------------------------
# 5. Insider window: both caller end_date and asof ceiling clamp
# ---------------------------------------------------------------------------


def test_insider_window_and_ceiling():
    bundle = TickerBundle(
        ticker="X",
        insider=[
            _insider("2024-01-10"),
            _insider("2024-02-10"),
            _insider("2024-03-10"),
        ],
    )
    client = CachedAsOfClient(bundle)

    # asof is earlier than caller end_date → asof wins (no Feb/Mar row).
    client.set_asof("2024-01-31")
    out = client.get_insider_trades("X", end_date="2024-12-31")
    assert [r.filing_date for r in out] == ["2024-01-10"]

    # caller end_date is earlier than asof → end_date wins (only Jan + Feb).
    client.set_asof("2024-12-31")
    out = client.get_insider_trades("X", end_date="2024-02-15")
    # newest-first
    assert [r.filing_date for r in out] == ["2024-02-10", "2024-01-10"]

    # start_date lower bound applies too.
    out = client.get_insider_trades("X", end_date="2024-12-31", start_date="2024-02-01")
    assert [r.filing_date for r in out] == ["2024-03-10", "2024-02-10"]


# ---------------------------------------------------------------------------
# 6. Empty bundle is safe
# ---------------------------------------------------------------------------


def test_empty_bundle_safe():
    client = CachedAsOfClient(TickerBundle(ticker="X"))
    client.set_asof("2024-06-01")

    assert client.get_prices("X", "2024-01-01", "2024-12-31") == []
    assert client.get_news("X", end_date="2024-12-31") == []
    assert client.get_insider_trades("X", end_date="2024-12-31") == []
    assert client.get_financial_metrics("X", "2024-12-31") == []
    assert client.get_earnings_history("X") == []
    assert client.get_analyst_actions("X", end_date="2024-12-31", start_date="2024-01-01") == []

    assert client.get_company_facts("X") is None
    assert client.get_earnings("X") is None
    assert client.get_analyst_targets("X") is None
    assert client.get_estimate_revisions("X") is None
    assert client.get_market_cap("X", "2024-12-31") is None
    assert client.get_earnings_calendar(start_date="2024-01-01", end_date="2024-12-31") == []
    # close() is a no-op and must not raise.
    client.close()


# ---------------------------------------------------------------------------
# 7. Protocol conformance (runtime_checkable verifies method names)
# ---------------------------------------------------------------------------


def test_runtime_checkable_conformance():
    client = CachedAsOfClient(TickerBundle(ticker="X"))
    assert isinstance(client, DataClient)


# ---------------------------------------------------------------------------
# Extra coverage: analyst targets, news, defensive bad-date handling
# ---------------------------------------------------------------------------


def test_analyst_targets_latest_at_or_before_ceiling():
    bundle = TickerBundle(
        ticker="X",
        analyst_targets=[
            _target("2024-01-15", 100.0),
            _target("2024-03-15", 120.0),
            _target("2024-06-15", 140.0),
        ],
    )
    client = CachedAsOfClient(bundle)

    client.set_asof("2024-04-01")
    t = client.get_analyst_targets("X")
    assert t is not None and t.asof_date == "2024-03-15"

    # explicit asof_date arg tightens further than the ceiling
    t = client.get_analyst_targets("X", asof_date="2024-02-01")
    assert t is not None and t.asof_date == "2024-01-15"

    # nothing on/before the ceiling → None
    client.set_asof("2024-01-01")
    assert client.get_analyst_targets("X") is None


def test_news_window_and_order():
    bundle = TickerBundle(
        ticker="X",
        news=[_news("2024-01-05"), _news("2024-02-05"), _news("2024-03-05")],
    )
    client = CachedAsOfClient(bundle)
    client.set_asof("2024-12-31")
    out = client.get_news("X", end_date="2024-02-10")
    assert [n.date for n in out] == ["2024-02-05", "2024-01-05"]


def test_bad_dates_excluded_never_raise():
    bundle = TickerBundle(
        ticker="X",
        prices=[_price("not-a-date", 1.0), _price("2024-01-02", 2.0)],
        news=[_news(None), _news("2024-01-02")],
        insider=[_insider("garbage"), _insider("2024-01-02")],
        metrics_history=[_metric("nope"), _metric("2024-01-01")],
        earnings_history=[_earn("2024-01-01", None), _earn("2024-01-01", "2024-01-02")],
    )
    client = CachedAsOfClient(bundle)
    client.set_asof("2024-06-01")

    assert [p.time for p in client.get_prices("X", "2024-01-01", "2024-12-31")] == ["2024-01-02"]
    assert [n.date for n in client.get_news("X", end_date="2024-12-31")] == ["2024-01-02"]
    assert [r.filing_date for r in client.get_insider_trades("X", end_date="2024-12-31")] == ["2024-01-02"]
    # metric "2024-01-01" + 60d < 2024-06-01 ceiling → visible; "nope" dropped.
    assert [m.report_period for m in client.get_financial_metrics("X", "2024-12-31")] == ["2024-01-01"]
    assert [e.filing_date for e in client.get_earnings_history("X")] == ["2024-01-02"]


def test_limit_caps_results():
    bundle = TickerBundle(
        ticker="X",
        earnings_history=[_earn("2024-01-01", f"2024-01-{d:02d}") for d in range(1, 13)],
    )
    client = CachedAsOfClient(bundle)
    client.set_asof("2024-12-31")
    out = client.get_earnings_history("X", limit=3)
    assert len(out) == 3
    # newest-first
    assert [e.filing_date for e in out] == ["2024-01-12", "2024-01-11", "2024-01-10"]
