"""Service tests for ``fetch_live_quotes`` (live watchlist quotes).

yfinance.download is monkeypatched to a small fake frame; never hits the
network. The HTTP route tests (which need the auth fixtures) live in
``tests/auth/test_watchlist_quotes_route.py``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backend.services.live_quotes import fetch_live_quotes


# ---------------------------------------------------------------------------
# Fake-frame builders (mirror yfinance.download output shapes)
# ---------------------------------------------------------------------------


def _multi_frame(data: dict[str, list[list[float]]]) -> pd.DataFrame:
    """Build a group_by='ticker' MultiIndex frame.

    ``data`` maps ticker -> list of [Open, High, Low, Close, Volume] rows.
    """
    idx = None
    cols: dict[tuple[str, str], list[float]] = {}
    fields = ["Open", "High", "Low", "Close", "Volume"]
    for ticker, rows in data.items():
        n = len(rows)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        for j, field in enumerate(fields):
            cols[(ticker, field)] = [r[j] for r in rows]
    df = pd.DataFrame(cols, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def _single_frame(rows: list[list[float]]) -> pd.DataFrame:
    """Build a non-grouped single-ticker frame (flat columns)."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {
            "Open": [r[0] for r in rows],
            "High": [r[1] for r in rows],
            "Low": [r[2] for r in rows],
            "Close": [r[3] for r in rows],
            "Volume": [r[4] for r in rows],
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# Service: fetch_live_quotes
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty():
    assert fetch_live_quotes([]) == []
    assert fetch_live_quotes(None) == []  # type: ignore[arg-type]


def test_multi_ticker_values_and_order(monkeypatch):
    # AAPL: prev close 100, last close 110 → +10%. MSFT: prev 200, last 190 → -5%.
    frame = _multi_frame(
        {
            "AAPL": [[99, 101, 98, 100, 1000], [108, 112, 107, 110, 2000]],
            "MSFT": [[201, 205, 199, 200, 3000], [191, 196, 188, 190, 4000]],
        }
    )
    monkeypatch.setattr("yfinance.download", lambda *a, **k: frame)

    rows = fetch_live_quotes(["AAPL", "MSFT"])
    assert [r["ticker"] for r in rows] == ["AAPL", "MSFT"]  # input order preserved

    aapl, msft = rows
    assert aapl["price"] == 110.0
    assert aapl["prev_close"] == 100.0
    assert aapl["change_pct"] == pytest.approx(10.0)
    assert aapl["volume"] == 2000
    assert aapl["day_open"] == 108.0
    assert aapl["day_high"] == 112.0
    assert aapl["day_low"] == 107.0
    assert aapl["error"] is None

    assert msft["price"] == 190.0
    assert msft["prev_close"] == 200.0
    assert msft["change_pct"] == pytest.approx(-5.0)
    assert msft["volume"] == 4000


def test_single_ticker_non_grouped_frame(monkeypatch):
    frame = _single_frame([[10, 11, 9, 10, 500], [12, 13, 11, 12, 600]])
    monkeypatch.setattr("yfinance.download", lambda *a, **k: frame)

    rows = fetch_live_quotes(["TSLA"])
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "TSLA"
    assert r["price"] == 12.0
    assert r["prev_close"] == 10.0
    assert r["change_pct"] == pytest.approx(20.0)
    assert r["volume"] == 600
    assert r["error"] is None


def test_ticker_absent_from_frame_gets_error_row(monkeypatch):
    # Frame only has AAPL; GOOG requested but missing.
    frame = _multi_frame(
        {"AAPL": [[99, 101, 98, 100, 1000], [108, 112, 107, 110, 2000]]}
    )
    monkeypatch.setattr("yfinance.download", lambda *a, **k: frame)

    rows = fetch_live_quotes(["AAPL", "GOOG"])
    assert [r["ticker"] for r in rows] == ["AAPL", "GOOG"]
    goog = rows[1]
    assert goog["error"] == "no data"
    assert goog["price"] is None
    assert goog["prev_close"] is None
    assert goog["change_pct"] is None
    assert goog["volume"] is None
    assert goog["day_open"] is None


def test_download_raises_is_best_effort(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("yfinance.download", _boom)
    rows = fetch_live_quotes(["AAPL", "MSFT"])
    # Best-effort: returns a row per ticker, all error rows, order preserved.
    assert [r["ticker"] for r in rows] == ["AAPL", "MSFT"]
    assert all(r["error"] == "no data" for r in rows)
    assert all(r["price"] is None for r in rows)


def test_empty_frame_is_best_effort(monkeypatch):
    monkeypatch.setattr("yfinance.download", lambda *a, **k: pd.DataFrame())
    rows = fetch_live_quotes(["AAPL"])
    assert len(rows) == 1
    assert rows[0]["error"] == "no data"


def test_missing_prev_close_change_pct_none(monkeypatch):
    # Only one close available → no prev_close → change_pct None.
    frame = _single_frame([[10, 11, 9, 10, 500]])
    monkeypatch.setattr("yfinance.download", lambda *a, **k: frame)
    r = fetch_live_quotes(["AAPL"])[0]
    assert r["price"] == 10.0
    assert r["prev_close"] is None
    assert r["change_pct"] is None
    assert r["error"] is None
