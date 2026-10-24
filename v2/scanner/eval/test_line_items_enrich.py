"""Tests for the best-effort line-items history sourcing in ``historical_events``.

``fetch_line_items_history`` is best-effort like every other fetcher in the
module: it returns ``[]`` on ANY failure and NEVER raises. These tests are fully
offline — the ``search_line_items`` symbol the module imported is monkeypatched
with a fake on the ``historical_events`` module, so no network is touched. The
contract under test is the field-list wiring + error isolation, not real data.
"""

from __future__ import annotations

from types import SimpleNamespace

from v2.scanner.eval import historical_events as he
from v2.scanner.eval.cached_asof_client import TickerBundle


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _line_item(report_period: str, **fields) -> SimpleNamespace:
    """A LineItem-like record: report_period + arbitrary dynamic fields."""
    return SimpleNamespace(
        ticker="AAPL",
        report_period=report_period,
        period="annual",
        currency="USD",
        **fields,
    )


# ---------------------------------------------------------------------------
# fetch_line_items_history — pass-through + never-raises
# ---------------------------------------------------------------------------


def test_fetch_line_items_history_passes_through(monkeypatch):
    captured = {}

    def _fake_search(ticker, line_items, end_date, period="annual", limit=10, api_key=None):
        captured["ticker"] = ticker
        captured["line_items"] = list(line_items)
        captured["end_date"] = end_date
        captured["period"] = period
        captured["limit"] = limit
        return [
            _line_item("2023-12-31", total_assets=1000.0, earnings_per_share=5.0),
            _line_item("2022-12-31", total_assets=900.0, earnings_per_share=4.0),
        ]

    monkeypatch.setattr(he, "search_line_items", _fake_search)

    out = he.fetch_line_items_history("AAPL", end_date="2024-03-01", limit=10)

    assert isinstance(out, list)
    assert len(out) == 2
    # Records carry report_period + the requested dynamic fields.
    assert out[0].report_period == "2023-12-31"
    assert out[0].total_assets == 1000.0
    assert out[0].earnings_per_share == 5.0
    # Requested the full canonical field list, annual period.
    assert captured["line_items"] == list(he._LINE_ITEM_FIELDS)
    assert captured["period"] == "annual"
    assert captured["end_date"] == "2024-03-01"
    assert captured["limit"] == 10


def test_fetch_line_items_history_swallows_exception(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("boom line items")

    monkeypatch.setattr(he, "search_line_items", _boom)
    # Never raises → returns [].
    assert he.fetch_line_items_history("AAPL", end_date="2024-03-01") == []


def test_fetch_line_items_history_none_result_returns_empty_list(monkeypatch):
    monkeypatch.setattr(he, "search_line_items", lambda *a, **k: None)
    assert he.fetch_line_items_history("AAPL", end_date="2024-03-01") == []


# ---------------------------------------------------------------------------
# enrich_bundle wires line_items_history + counts
# ---------------------------------------------------------------------------


def test_enrich_bundle_attaches_line_items_history(monkeypatch):
    # Line items ride the fundamentals (``do_financials``) leg. Keep the other
    # (yfinance-backed) steps inert by stubbing them to empty.
    monkeypatch.setattr(he, "fetch_earnings_history", lambda *a, **k: [])
    monkeypatch.setattr(he, "fetch_analyst_actions", lambda *a, **k: [])
    monkeypatch.setattr(he, "fetch_financials_history", lambda *a, **k: [])

    items = [
        _line_item("2023-12-31", total_assets=1000.0),
        _line_item("2022-12-31", total_assets=900.0),
    ]
    monkeypatch.setattr(he, "search_line_items", lambda *a, **k: items)

    bundle = TickerBundle(ticker="AAPL")
    counts = he.enrich_bundle(
        bundle,
        start_date="2023-01-01",
        end_date="2024-03-01",
        do_financials=True,
    )

    assert bundle.line_items_history == items
    assert counts["line_items"] == 2


def test_enrich_bundle_counts_has_line_items_key_when_empty(monkeypatch):
    monkeypatch.setattr(he, "fetch_earnings_history", lambda *a, **k: [])
    monkeypatch.setattr(he, "fetch_analyst_actions", lambda *a, **k: [])
    monkeypatch.setattr(he, "fetch_financials_history", lambda *a, **k: [])
    monkeypatch.setattr(he, "search_line_items", lambda *a, **k: [])

    bundle = TickerBundle(ticker="AAPL")
    counts = he.enrich_bundle(
        bundle,
        start_date="2023-01-01",
        end_date="2024-03-01",
        do_financials=True,
    )
    assert counts["line_items"] == 0
    assert bundle.line_items_history == []


def test_enrich_bundle_skips_line_items_when_do_financials_false(monkeypatch):
    # do_financials=False suppresses BOTH the metrics and the line-items leg.
    monkeypatch.setattr(he, "fetch_earnings_history", lambda *a, **k: [])
    monkeypatch.setattr(he, "fetch_analyst_actions", lambda *a, **k: [])

    def _should_not_run(*a, **k):  # pragma: no cover - asserts it's never called
        raise AssertionError("search_line_items called despite do_financials=False")

    monkeypatch.setattr(he, "search_line_items", _should_not_run)

    bundle = TickerBundle(ticker="AAPL")
    counts = he.enrich_bundle(
        bundle,
        start_date="2023-01-01",
        end_date="2024-03-01",
        do_financials=False,
    )
    assert counts["line_items"] == 0
    assert bundle.line_items_history == []
