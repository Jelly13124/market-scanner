"""Tests for Phase-2 best-effort historical event/fundamental sourcing.

Every fetcher in ``historical_events`` is best-effort: it returns ``[]`` / a
counts dict on ANY failure and NEVER raises. These tests are fully offline —
``YFinanceClient`` is monkeypatched with a fake, insider/news clients are plain
fakes, and the lazy ``yfinance`` import inside ``fetch_financials_history`` is
patched to a tiny in-memory module. The contract under test is the error
isolation + pass-through wiring, not real Yahoo data.
"""

from __future__ import annotations

import sys
import time
import types

import pytest

from v2.data.models import AnalystAction, CompanyNews, EarningsRecord, InsiderTrade
from v2.scanner.eval import historical_events as he
from v2.scanner.eval.cached_asof_client import TickerBundle


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeYF:
    """Stand-in for ``YFinanceClient`` — records calls, returns fixed lists."""

    earnings_ret: list = []
    actions_ret: list = []
    earnings_raises = False
    actions_raises = False
    calls: list = []

    def __init__(self, *a, **k) -> None:
        pass

    def get_earnings_history(self, ticker, limit=12):
        _FakeYF.calls.append(("earnings", ticker, limit))
        if _FakeYF.earnings_raises:
            raise RuntimeError("boom earnings")
        return list(_FakeYF.earnings_ret)

    def get_analyst_actions(self, ticker, *, end_date, start_date, limit=100):
        _FakeYF.calls.append(("actions", ticker, start_date, end_date, limit))
        if _FakeYF.actions_raises:
            raise RuntimeError("boom actions")
        return list(_FakeYF.actions_ret)


class _FakeInsiderClient:
    def __init__(self, ret=None, raises=False) -> None:
        self.ret = ret or []
        self.raises = raises
        self.calls: list = []

    def get_insider_trades(self, ticker, *, end_date, start_date, limit=1000):
        self.calls.append((ticker, start_date, end_date, limit))
        if self.raises:
            raise RuntimeError("boom insider")
        return list(self.ret)


class _FakeNewsClient:
    def __init__(self, ret=None, raises=False) -> None:
        self.ret = ret or []
        self.raises = raises
        self.calls: list = []

    def get_news(self, ticker, *, end_date, start_date, limit=1000):
        self.calls.append((ticker, start_date, end_date, limit))
        if self.raises:
            raise RuntimeError("boom news")
        return list(self.ret)


def _earnings_record() -> EarningsRecord:
    return EarningsRecord(
        ticker="AAPL", report_period="2024-01-31",
        source_type="yfinance", filing_date="2024-01-31",
    )


def _analyst_action() -> AnalystAction:
    return AnalystAction(
        ticker="AAPL", action_date="2024-02-01", firm="MS", action="up",
    )


def _insider_trade() -> InsiderTrade:
    return InsiderTrade(ticker="AAPL", name="CEO", filing_date="2024-01-15")


def _news() -> CompanyNews:
    return CompanyNews(ticker="AAPL", title="t", source="s", date="2024-01-10")


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeYF.earnings_ret = []
    _FakeYF.actions_ret = []
    _FakeYF.earnings_raises = False
    _FakeYF.actions_raises = False
    _FakeYF.calls = []
    yield


# ---------------------------------------------------------------------------
# fetch_earnings_history / fetch_analyst_actions — pass-through
# ---------------------------------------------------------------------------


def test_fetch_earnings_history_passes_through(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.earnings_ret = [_earnings_record(), _earnings_record()]
    out = he.fetch_earnings_history("AAPL", limit=40)
    assert out == _FakeYF.earnings_ret
    assert _FakeYF.calls[0] == ("earnings", "AAPL", 40)


def test_fetch_earnings_history_swallows_exception(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.earnings_raises = True
    assert he.fetch_earnings_history("AAPL") == []


def test_fetch_analyst_actions_passes_through(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.actions_ret = [_analyst_action()]
    out = he.fetch_analyst_actions(
        "AAPL", start_date="2024-01-01", end_date="2024-03-01", limit=200,
    )
    assert out == _FakeYF.actions_ret
    assert _FakeYF.calls[0] == ("actions", "AAPL", "2024-01-01", "2024-03-01", 200)


def test_fetch_analyst_actions_swallows_exception(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.actions_raises = True
    assert he.fetch_analyst_actions(
        "AAPL", start_date="2024-01-01", end_date="2024-03-01",
    ) == []


# ---------------------------------------------------------------------------
# fetch_insider_window / fetch_news_history — pass-through + None client
# ---------------------------------------------------------------------------


def test_fetch_insider_window_passes_through():
    client = _FakeInsiderClient(ret=[_insider_trade()])
    out = he.fetch_insider_window(
        "AAPL", start_date="2024-01-01", end_date="2024-02-01", insider_client=client,
    )
    assert out == client.ret
    assert client.calls[0] == ("AAPL", "2024-01-01", "2024-02-01", 1000)


def test_fetch_insider_window_none_client_returns_empty():
    assert he.fetch_insider_window(
        "AAPL", start_date="2024-01-01", end_date="2024-02-01", insider_client=None,
    ) == []


def test_fetch_insider_window_swallows_exception():
    client = _FakeInsiderClient(raises=True)
    assert he.fetch_insider_window(
        "AAPL", start_date="2024-01-01", end_date="2024-02-01", insider_client=client,
    ) == []


def test_fetch_news_history_passes_through():
    client = _FakeNewsClient(ret=[_news()])
    out = he.fetch_news_history(
        "AAPL", start_date="2024-01-01", end_date="2024-02-01", news_client=client,
    )
    assert out == client.ret
    assert client.calls[0] == ("AAPL", "2024-01-01", "2024-02-01", 1000)


def test_fetch_news_history_none_client_returns_empty():
    assert he.fetch_news_history(
        "AAPL", start_date="2024-01-01", end_date="2024-02-01", news_client=None,
    ) == []


def test_fetch_news_history_swallows_exception():
    client = _FakeNewsClient(raises=True)
    assert he.fetch_news_history(
        "AAPL", start_date="2024-01-01", end_date="2024-02-01", news_client=client,
    ) == []


# ---------------------------------------------------------------------------
# fetch_financials_history — best-effort; returns a list, never raises
# ---------------------------------------------------------------------------


class _FakeSeries:
    """Minimal pandas-Series-like: .get(key) lookup over a dict."""

    def __init__(self, d):
        self._d = d

    def get(self, key, default=None):
        return self._d.get(key, default)


class _FakeFrame:
    """Minimal pandas-DataFrame-like for quarterly statements.

    Columns are period-end timestamps; rows are line-item labels. ``[col]``
    returns a Series-like keyed by label. ``.empty`` and ``.columns`` mirror
    the pandas attributes the implementation may read.
    """

    def __init__(self, columns, data):
        # data: {label: {col: value}}
        self.columns = list(columns)
        self._data = data

    @property
    def empty(self):
        return len(self.columns) == 0

    def __getitem__(self, col):
        return _FakeSeries({label: vals.get(col) for label, vals in self._data.items()})


class _FakeTs:
    """Timestamp-like with .date() and isoformat-able str."""

    def __init__(self, iso):
        self._iso = iso

    def date(self):
        import datetime as _dt
        return _dt.date.fromisoformat(self._iso)

    def __str__(self):
        return self._iso


class _FakeTicker:
    def __init__(self, fin, bs):
        self.quarterly_financials = fin
        self.quarterly_balance_sheet = bs


def _install_fake_yfinance(monkeypatch, ticker_obj=None, raises=False):
    """Install a fake ``yfinance`` module into ``sys.modules`` so the lazy
    ``import yfinance`` inside fetch_financials_history resolves to it."""
    mod = types.ModuleType("yfinance")

    def _Ticker(sym):
        if raises:
            raise RuntimeError("boom yfinance")
        return ticker_obj

    mod.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return mod


def test_fetch_financials_history_returns_list_with_fake_frame(monkeypatch):
    # Two quarters, same fiscal quarter a year apart so YoY growth is derivable.
    cols = [_FakeTs("2024-03-31"), _FakeTs("2023-03-31")]
    fin = _FakeFrame(
        columns=cols,
        data={
            "Total Revenue": {cols[0]: 120.0, cols[1]: 100.0},
            "Gross Profit": {cols[0]: 60.0, cols[1]: 48.0},
            "Operating Income": {cols[0]: 30.0, cols[1]: 24.0},
            "Net Income": {cols[0]: 24.0, cols[1]: 20.0},
        },
    )
    bs = _FakeFrame(columns=cols, data={})
    _install_fake_yfinance(monkeypatch, _FakeTicker(fin, bs))

    out = he.fetch_financials_history("AAPL")
    assert isinstance(out, list)
    # All returned items are FinancialMetrics with the required keys set.
    for m in out:
        assert m.ticker == "AAPL"
        assert m.report_period
        assert m.period
    # Margins should be derivable for the most recent quarter.
    if out:
        by_period = {m.report_period: m for m in out}
        latest = by_period.get("2024-03-31")
        assert latest is not None
        assert latest.gross_margin == pytest.approx(0.5)
        assert latest.operating_margin == pytest.approx(0.25)
        assert latest.net_margin == pytest.approx(0.2)
        # YoY revenue growth 100 -> 120 = +0.20
        assert latest.revenue_growth == pytest.approx(0.2)


def test_fetch_financials_history_raising_yfinance_returns_empty(monkeypatch):
    _install_fake_yfinance(monkeypatch, raises=True)
    assert he.fetch_financials_history("AAPL") == []


def test_fetch_financials_history_empty_frame_returns_list(monkeypatch):
    empty = _FakeFrame(columns=[], data={})
    _install_fake_yfinance(monkeypatch, _FakeTicker(empty, empty))
    out = he.fetch_financials_history("AAPL")
    assert out == []


def test_fetch_financials_history_no_yfinance_module(monkeypatch):
    # Simulate yfinance not installed → ImportError inside the function → [].
    monkeypatch.setitem(sys.modules, "yfinance", None)
    assert he.fetch_financials_history("AAPL") == []


# ---------------------------------------------------------------------------
# enrich_bundle
# ---------------------------------------------------------------------------


def test_enrich_bundle_fills_lists_and_returns_counts(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.earnings_ret = [_earnings_record(), _earnings_record()]
    _FakeYF.actions_ret = [_analyst_action()]
    insider = _FakeInsiderClient(ret=[_insider_trade()])
    news = _FakeNewsClient(ret=[_news(), _news(), _news()])
    bundle = TickerBundle(ticker="AAPL")

    counts = he.enrich_bundle(
        bundle,
        start_date="2023-01-01",
        end_date="2024-03-01",
        insider_client=insider,
        news_client=news,
        do_financials=False,
    )

    assert bundle.earnings_history == _FakeYF.earnings_ret
    assert bundle.analyst_actions == _FakeYF.actions_ret
    assert bundle.insider == insider.ret
    assert bundle.news == news.ret
    assert counts["earnings"] == 2
    assert counts["analyst"] == 1
    assert counts["insider"] == 1
    assert counts["news"] == 3
    assert counts["financials"] == 0  # do_financials=False


def test_enrich_bundle_runs_financials_when_enabled(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    cols = [_FakeTs("2024-03-31"), _FakeTs("2023-03-31")]
    fin = _FakeFrame(
        columns=cols,
        data={
            "Total Revenue": {cols[0]: 120.0, cols[1]: 100.0},
            "Gross Profit": {cols[0]: 60.0, cols[1]: 48.0},
        },
    )
    bs = _FakeFrame(columns=cols, data={})
    _install_fake_yfinance(monkeypatch, _FakeTicker(fin, bs))
    bundle = TickerBundle(ticker="AAPL")

    counts = he.enrich_bundle(
        bundle, start_date="2023-01-01", end_date="2024-03-01", do_financials=True,
    )
    assert counts["financials"] == len(bundle.metrics_history)
    assert counts["financials"] >= 1


def test_enrich_bundle_past_deadline_stops_early(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.earnings_ret = [_earnings_record()]
    _FakeYF.actions_ret = [_analyst_action()]
    insider = _FakeInsiderClient(ret=[_insider_trade()])
    news = _FakeNewsClient(ret=[_news()])
    bundle = TickerBundle(ticker="AAPL")

    past = time.monotonic() - 1.0
    counts = he.enrich_bundle(
        bundle,
        start_date="2023-01-01",
        end_date="2024-03-01",
        insider_client=insider,
        news_client=news,
        deadline=past,
    )
    # Returns a dict and did little/no work — nothing fetched.
    assert isinstance(counts, dict)
    assert counts["earnings"] == 0
    assert counts["analyst"] == 0
    assert counts["insider"] == 0
    assert counts["news"] == 0
    assert bundle.earnings_history == []
    # No yfinance/insider/news calls happened.
    assert _FakeYF.calls == []
    assert insider.calls == []
    assert news.calls == []


# ---------------------------------------------------------------------------
# probe_availability
# ---------------------------------------------------------------------------


def test_probe_availability_all_true(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.earnings_ret = [_earnings_record()]
    _FakeYF.actions_ret = [_analyst_action()]
    cols = [_FakeTs("2024-03-31"), _FakeTs("2023-03-31")]
    fin = _FakeFrame(
        columns=cols,
        data={
            "Total Revenue": {cols[0]: 120.0, cols[1]: 100.0},
            "Gross Profit": {cols[0]: 60.0, cols[1]: 48.0},
        },
    )
    bs = _FakeFrame(columns=cols, data={})
    _install_fake_yfinance(monkeypatch, _FakeTicker(fin, bs))
    insider = _FakeInsiderClient(ret=[_insider_trade()])
    news = _FakeNewsClient(ret=[_news()])

    out = he.probe_availability(
        "AAPL", insider_client=insider, news_client=news,
    )
    assert out["earnings"] is True
    assert out["analyst"] is True
    assert out["insider"] is True
    assert out["news"] is True
    assert out["financials"] is True


def test_probe_availability_handles_raising_sources(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.earnings_raises = True
    _FakeYF.actions_raises = True
    _install_fake_yfinance(monkeypatch, raises=True)
    insider = _FakeInsiderClient(raises=True)
    news = _FakeNewsClient(raises=True)

    out = he.probe_availability(
        "AAPL", insider_client=insider, news_client=news,
    )
    assert out["earnings"] is False
    assert out["analyst"] is False
    assert out["insider"] is False
    assert out["news"] is False
    assert out["financials"] is False


def test_probe_availability_none_clients_are_false(monkeypatch):
    monkeypatch.setattr(he, "YFinanceClient", _FakeYF)
    _FakeYF.earnings_ret = [_earnings_record()]
    _FakeYF.actions_ret = [_analyst_action()]
    # No financials frame installed and no insider/news clients.
    _install_fake_yfinance(monkeypatch, raises=True)
    out = he.probe_availability("AAPL", insider_client=None, news_client=None)
    assert out["earnings"] is True
    assert out["analyst"] is True
    assert out["insider"] is False
    assert out["news"] is False
    assert out["financials"] is False
