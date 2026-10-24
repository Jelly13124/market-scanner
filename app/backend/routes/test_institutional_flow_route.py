"""Offline tests for the institutional-flow route (fetches mocked — no network)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.backend.routes.institutional_flow as ifr


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ifr.router)
    return TestClient(app)


def test_returns_gamma_and_shortvol(monkeypatch):
    monkeypatch.setattr(
        ifr,
        "fetch_gamma_exposure",
        lambda t: {"regime": "negative", "total_gex": -3.5e9, "spot": 739.0, "walls": [{"strike": 740, "gamma_dollars": 9e8}], "gamma_flip": None},
    )
    monkeypatch.setattr(
        ifr,
        "fetch_short_volume",
        lambda t: {"short_pct": 0.34, "trend": "falling", "date": "2026-06-05"},
    )
    r = _client().get("/institutional-flow/nvda")
    assert r.status_code == 200
    j = r.json()
    assert j["ticker"] == "NVDA"  # uppercased
    assert j["gamma"]["regime"] == "negative"
    assert j["short_volume"]["short_pct"] == 0.34


def test_both_none_returns_nulls_not_500(monkeypatch):
    monkeypatch.setattr(ifr, "fetch_gamma_exposure", lambda t: None)
    monkeypatch.setattr(ifr, "fetch_short_volume", lambda t: None)
    r = _client().get("/institutional-flow/XYZ")
    assert r.status_code == 200
    assert r.json() == {"ticker": "XYZ", "gamma": None, "short_volume": None}


def test_fetch_exception_is_swallowed(monkeypatch):
    def boom(t):
        raise RuntimeError("net down")

    monkeypatch.setattr(ifr, "fetch_gamma_exposure", boom)
    monkeypatch.setattr(ifr, "fetch_short_volume", boom)
    r = _client().get("/institutional-flow/AAA")
    assert r.status_code == 200
    j = r.json()
    assert j["gamma"] is None and j["short_volume"] is None
