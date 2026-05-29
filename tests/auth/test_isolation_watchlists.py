from tests.auth.conftest import auth_header


def test_watchlist_isolation(full_client, two_users):
    a, b = two_users
    created = full_client.post("/watchlists", json={"name": "A list"}, headers=auth_header(a))
    assert created.status_code == 201
    wid = created.json()["id"]
    # B's list does not contain A's row
    b_list = full_client.get("/watchlists", headers=auth_header(b)).json()
    assert all(w["id"] != wid for w in b_list)
    # B cannot read / update / delete A's row → 404
    assert full_client.get(f"/watchlists/{wid}", headers=auth_header(b)).status_code == 404
    assert full_client.patch(f"/watchlists/{wid}", json={"name": "hijack"}, headers=auth_header(b)).status_code == 404
    assert full_client.delete(f"/watchlists/{wid}", headers=auth_header(b)).status_code == 404
    # A still can
    assert full_client.get(f"/watchlists/{wid}", headers=auth_header(a)).status_code == 200


def test_requires_auth(full_client):
    assert full_client.get("/watchlists").status_code == 401


def test_same_name_allowed_across_users(full_client, two_users):
    a, b = two_users
    assert full_client.post("/watchlists", json={"name": "Tech"}, headers=auth_header(a)).status_code == 201
    assert full_client.post("/watchlists", json={"name": "Tech"}, headers=auth_header(b)).status_code == 201  # per-user uniqueness
