"""Offline tests for the ownership data fetch (yfinance, best-effort).

No network: yfinance is replaced with a fake module via ``sys.modules`` so
``fetch_ownership`` reads our synthetic ``.info`` / ``.major_holders`` /
``.institutional_holders`` instead of hitting the wire. A yfinance exception
must degrade to an all-``None`` dict, never raise.
"""

from __future__ import annotations

import sys
import types

import pandas as pd

from src.research.ownership_fetch import fetch_ownership


# --------------------------------------------------------------------------- #
# Fake yfinance plumbing
# --------------------------------------------------------------------------- #


class _FakeTicker:
    """Mimics the slice of yfinance.Ticker that fetch_ownership touches."""

    def __init__(self, ticker):
        self.ticker = ticker
        self.info = {
            "heldPercentInsiders": 0.0007,
            "heldPercentInstitutions": 0.62,
            "sharesOutstanding": 15_000_000_000,
        }
        # .major_holders: yfinance returns a DataFrame; institutionsCount lives
        # in the "Value" column keyed by "institutionsCount" in recent versions.
        self.major_holders = pd.DataFrame({"Value": {"institutionsCount": 4321}})
        # .institutional_holders: a DataFrame with Holder + pctHeld columns.
        self.institutional_holders = pd.DataFrame(
            {
                "Holder": ["Vanguard Group Inc", "Blackrock Inc.", "State Street Corp"],
                "pctHeld": [0.0834, 0.0651, 0.0398],
            }
        )


def _install_fake_yf(monkeypatch, ticker_factory):
    fake = types.ModuleType("yfinance")
    fake.Ticker = ticker_factory
    monkeypatch.setitem(sys.modules, "yfinance", fake)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_fetch_ownership_returns_full_dict(monkeypatch):
    _install_fake_yf(monkeypatch, _FakeTicker)

    out = fetch_ownership("AAPL")

    assert out["insider_pct"] == 0.0007
    assert out["institution_pct"] == 0.62
    assert out["shares_outstanding"] == 15_000_000_000
    assert out["institution_count"] == 4321

    holders = out["top_holders"]
    assert isinstance(holders, list)
    assert len(holders) == 3
    assert holders[0] == {"name": "Vanguard Group Inc", "pct": 0.0834}
    assert holders[1]["name"] == "Blackrock Inc."
    assert holders[2]["pct"] == 0.0398


def test_fetch_ownership_has_all_expected_keys(monkeypatch):
    _install_fake_yf(monkeypatch, _FakeTicker)
    out = fetch_ownership("AAPL")
    for key in (
        "insider_pct",
        "institution_pct",
        "institution_count",
        "top_holders",
        "shares_outstanding",
    ):
        assert key in out


# --------------------------------------------------------------------------- #
# Best-effort degradation — never raises
# --------------------------------------------------------------------------- #


def test_fetch_ownership_swallows_yfinance_exception(monkeypatch):
    def _boom(ticker):
        raise RuntimeError("network down")

    _install_fake_yf(monkeypatch, _boom)

    out = fetch_ownership("AAPL")  # must NOT raise
    assert out == {
        "insider_pct": None,
        "institution_pct": None,
        "institution_count": None,
        "top_holders": None,
        "shares_outstanding": None,
    }


def test_fetch_ownership_handles_missing_fields(monkeypatch):
    class _SparseTicker:
        def __init__(self, ticker):
            self.info = {}  # no held* / sharesOutstanding keys
            self.major_holders = None
            self.institutional_holders = None

    _install_fake_yf(monkeypatch, _SparseTicker)

    out = fetch_ownership("AAPL")  # must NOT raise on the sparse shapes
    assert out["insider_pct"] is None
    assert out["institution_pct"] is None
    assert out["shares_outstanding"] is None
    assert out["institution_count"] is None
    # top_holders degrades to None (no DataFrame) or an empty list — either is
    # an acceptable "no data" signal the section guards on.
    assert out["top_holders"] in (None, [])


def test_fetch_ownership_handles_empty_institutional_holders(monkeypatch):
    class _EmptyHoldersTicker:
        def __init__(self, ticker):
            self.info = {"heldPercentInstitutions": 0.5}
            self.major_holders = None
            self.institutional_holders = pd.DataFrame({"Holder": [], "pctHeld": []})

    _install_fake_yf(monkeypatch, _EmptyHoldersTicker)

    out = fetch_ownership("AAPL")
    assert out["institution_pct"] == 0.5
    assert out["top_holders"] in (None, [])
