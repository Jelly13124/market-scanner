"""Isolation tests: screener presets are scoped per user_id."""
from tests.auth.conftest import auth_header


def test_preset_isolation(full_client, two_users):
    a, b = two_users
    r = full_client.post(
        "/screener/presets",
        json={"name": "A preset", "market": "US", "filters": {}},
        headers=auth_header(a),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    # B's list does not contain A's preset
    b_list = full_client.get("/screener/presets", headers=auth_header(b)).json()
    assert all(p["id"] != pid for p in b_list)

    # B cannot read (run), patch, or delete A's preset → 404
    assert full_client.post(f"/screener/presets/{pid}/run", headers=auth_header(b)).status_code == 404
    assert full_client.patch(f"/screener/presets/{pid}", json={"name": "hijack"}, headers=auth_header(b)).status_code == 404
    assert full_client.delete(f"/screener/presets/{pid}", headers=auth_header(b)).status_code == 404

    # A still owns and can see it
    a_list = full_client.get("/screener/presets", headers=auth_header(a)).json()
    assert any(p["id"] == pid for p in a_list)


def test_preset_requires_auth(full_client):
    assert full_client.get("/screener/presets").status_code == 401
    assert full_client.post("/screener/presets", json={"name": "x", "market": "US", "filters": {}}).status_code == 401


def test_same_name_allowed_across_users(full_client, two_users):
    a, b = two_users
    assert full_client.post(
        "/screener/presets",
        json={"name": "MyPreset", "market": "US", "filters": {}},
        headers=auth_header(a),
    ).status_code == 201
    assert full_client.post(
        "/screener/presets",
        json={"name": "MyPreset", "market": "US", "filters": {}},
        headers=auth_header(b),
    ).status_code == 201  # per-user: no conflict
