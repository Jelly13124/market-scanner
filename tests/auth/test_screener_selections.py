from datetime import date

import pytest

from app.backend.repositories.screener_repository import ScreenerRepository, SnapshotRow
from tests.auth.conftest import auth_header


@pytest.fixture
def selection(full_client):
    with full_client.session_local() as db:
        ScreenerRepository(db).bulk_upsert([
            SnapshotRow(ticker=ticker, market=market, sector=sector, snapshot_date=date(2026, 5, day))
            for ticker, market, sector, day in [
                ("AMD", "US", "Technology", 26),
                ("AMD", "US", "Energy", 27),
                ("AAPL", "US", "Technology", 26),
                ("MSFT", "US", "Technology", 26),
                ("XOM", "US", "Energy", 26),
                ("600519.SH", "CN", "Technology", 26),
                ("LATER", "US", "Technology", 27),
            ]
        ])
    return {
        "market": "US", "filters": {"sector_in": ["Technology"]},
        "snapshot_date": "2026-05-26", "tickers": ["AMD", "AAPL"],
    }


def test_saves_exact_filtered_selection_and_keeps_it_after_edits(full_client, two_users, selection):
    a, b = (auth_header(token) for token in two_users)
    wid = full_client.post("/watchlists", json={"name": "Research"}, headers=a).json()["id"]
    watchlist = f"/watchlists/{wid}"
    full_client.patch(watchlist, json={"tickers": ["SPY", "AAPL"]}, headers=a).raise_for_status()

    result = full_client.post("/screener/selections", json={**selection, "watchlist_id": wid}, headers=a)
    assert result.status_code == 201, result.text
    frozen = result.json()
    assert frozen["tickers"] == ["AMD", "AAPL"]
    assert frozen["origin"] == "screener"
    assert frozen["market"] == "US"
    assert frozen["filters"] == {"sector_in": ["Technology"]}
    assert frozen["filter_version"] == "screener.v1"
    assert frozen["screener_snapshot_date"] == "2026-05-26"
    assert frozen["source_watchlist_id"] == wid
    assert frozen["selected_at"]
    current = full_client.get(watchlist, headers=a).json()
    assert current["tickers"] == ["SPY", "AAPL", "AMD"]
    assert current["latest_selection_id"] == frozen["id"]
    history = f"/screener/universe-snapshots/{frozen['id']}"
    assert full_client.get(history, headers=b).status_code == 404
    assert full_client.post("/screener/selections", json={**selection, "watchlist_id": wid}, headers=b).status_code == 404

    second = full_client.post("/screener/selections", json={**selection, "watchlist_id": wid, "tickers": ["MSFT"]}, headers=a)
    assert second.status_code == 201
    assert full_client.get(watchlist, headers=a).json()["latest_selection_id"] == second.json()["id"]
    full_client.patch(watchlist, json={"tickers": ["SPY"]}, headers=a).raise_for_status()
    full_client.delete(watchlist, headers=a).raise_for_status()
    after_delete = full_client.get(history, headers=a)
    assert after_delete.status_code == 200
    assert after_delete.json()["tickers"] == ["AMD", "AAPL"]
    assert after_delete.json()["filters"] == {"sector_in": ["Technology"]}


@pytest.mark.parametrize("overrides", [
    {"tickers": ["AMD", "XOM"]}, {"tickers": ["600519.SH"]}, {"tickers": ["LATER"]},
    {"filters": {"unknown_rule": 1}}, {"filters": {"price_min": "NaN"}},
    {"filters": {"sector_in": [{"token": "unrelated"}]}},
    {"filters": {"recent_earnings_before": "none"}}, {"tickers": []},
])
def test_invalid_selection_never_creates_its_watchlist(full_client, two_users, selection, overrides):
    headers = auth_header(two_users[0])
    result = full_client.post("/screener/selections", json={
        **selection, "new_watchlist_name": "Rejected", **overrides,
    }, headers=headers)
    assert result.status_code == 422, result.text
    assert full_client.get("/watchlists", headers=headers).json() == []


def test_create_watchlist_and_save_selection(full_client, two_users, selection):
    headers = auth_header(two_users[0])
    payload = {**selection, "new_watchlist_name": "Technology"}
    response = full_client.post("/screener/selections", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    wid = response.json()["source_watchlist_id"]
    created = full_client.get(f"/watchlists/{wid}", headers=headers).json()
    assert created["tickers"] == ["AMD", "AAPL"]
    assert created["latest_selection_id"] == response.json()["id"]
    assert full_client.post("/screener/selections", json=payload, headers=headers).status_code == 409
    assert full_client.get(f"/watchlists/{wid}", headers=headers).json() == created


def test_selection_uses_same_csv_multiselect_as_snapshot_query(full_client, two_users, selection):
    # An existing saved preset may supply the list chip as a comma-separated string.
    headers = auth_header(two_users[0])
    filters = {"sector_in": "Technology, Energy"}
    viewed = full_client.get("/screener/snapshot/latest", params={"market": "US", **filters})
    assert viewed.status_code == 200
    response = full_client.post("/screener/selections", headers=headers, json={
        **selection, "filters": filters, "snapshot_date": viewed.json()["snapshot_date"],
        "tickers": ["AMD"], "new_watchlist_name": "Imported preset",
    })
    assert response.status_code == 201, response.text
    assert response.json()["filters"] == {"sector_in": ["Technology", "Energy"]}
