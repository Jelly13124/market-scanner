"""Route tests for ``GET /watchlists/{id}/quotes``.

Uses the ``full_client`` + ``two_users`` fixtures (tests/auth/conftest.py).
``fetch_live_quotes`` is patched at the route module boundary to a canned
row, so no network access. Covers: happy path, cross-user 404, and 401.
"""

from __future__ import annotations

from tests.auth.conftest import auth_header


_CANNED = {
    "ticker": "NVDA",
    "price": 123.45,
    "prev_close": 120.0,
    "change_pct": 2.875,
    "volume": 1_000_000,
    "day_open": 121.0,
    "day_high": 125.0,
    "day_low": 119.5,
    "error": None,
}


def test_route_returns_quotes(full_client, two_users, monkeypatch):
    a, _ = two_users
    # Patch at the route module boundary (where the name is imported).
    monkeypatch.setattr(
        "app.backend.routes.watchlists.fetch_live_quotes",
        lambda tickers, **kwargs: [dict(_CANNED)],
    )
    wid = full_client.post("/watchlists", json={"name": "Live"}, headers=auth_header(a)).json()["id"]
    full_client.post(f"/watchlists/{wid}/tickers", json={"ticker": "NVDA"}, headers=auth_header(a))

    r = full_client.get(f"/watchlists/{wid}/quotes", headers=auth_header(a))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "NVDA"
    assert body[0]["price"] == 123.45
    assert body[0]["change_pct"] == 2.875
    assert body[0]["error"] is None


def test_route_cross_user_404(full_client, two_users, monkeypatch):
    a, b = two_users
    monkeypatch.setattr(
        "app.backend.routes.watchlists.fetch_live_quotes",
        lambda tickers, **kwargs: [dict(_CANNED)],
    )
    wid = full_client.post("/watchlists", json={"name": "A's"}, headers=auth_header(a)).json()["id"]
    # B cannot read A's watchlist quotes.
    assert full_client.get(f"/watchlists/{wid}/quotes", headers=auth_header(b)).status_code == 404


def test_route_requires_auth(full_client, two_users, monkeypatch):
    a, _ = two_users
    monkeypatch.setattr(
        "app.backend.routes.watchlists.fetch_live_quotes",
        lambda tickers, **kwargs: [dict(_CANNED)],
    )
    wid = full_client.post("/watchlists", json={"name": "A's"}, headers=auth_header(a)).json()["id"]
    assert full_client.get(f"/watchlists/{wid}/quotes").status_code == 401


def test_quote_route_uses_only_acting_users_finnhub_key(full_client, two_users, monkeypatch):
    from unittest.mock import Mock
    a, b = two_users
    ha, hb = auth_header(a), auth_header(b)
    for headers, key in [(ha, 'test-finnhub-a'), (hb, 'test-finnhub-b')]:
        response = full_client.post('/api-keys/', json={'provider': 'FINNHUB_API_KEY', 'key_value': key}, headers=headers)
        assert response.status_code in (200, 201), response.text
    fetch = Mock(return_value=[dict(_CANNED)])
    monkeypatch.setattr('app.backend.routes.watchlists.fetch_live_quotes', fetch)
    wid = full_client.post('/watchlists', json={'name': 'Own quotes'}, headers=ha).json()['id']
    assert full_client.get(f'/watchlists/{wid}/quotes', headers=ha).status_code == 200
    assert fetch.call_args.kwargs['finnhub_api_key'] == 'test-finnhub-a'
