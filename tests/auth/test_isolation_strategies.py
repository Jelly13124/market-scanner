"""Isolation tests: strategies are scoped per user_id."""

from tests.auth.conftest import auth_header

_STRATEGY = {"name": "My Strategy", "description": "test"}


def test_strategy_isolation(full_client, two_users):
    a, b = two_users
    r = full_client.post("/lab/strategies", json=_STRATEGY, headers=auth_header(a))
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # B's list does not contain A's strategy
    b_list = full_client.get("/lab/strategies", headers=auth_header(b)).json()
    assert all(s["id"] != sid for s in b_list)

    # B cannot get, patch, or delete A's strategy → 404
    assert full_client.get(f"/lab/strategies/{sid}", headers=auth_header(b)).status_code == 404
    assert full_client.patch(
        f"/lab/strategies/{sid}", json={"name": "hijack"}, headers=auth_header(b)
    ).status_code == 404
    assert full_client.delete(f"/lab/strategies/{sid}", headers=auth_header(b)).status_code == 404

    # A still owns it
    assert full_client.get(f"/lab/strategies/{sid}", headers=auth_header(a)).status_code == 200


def test_strategy_requires_auth(full_client):
    assert full_client.get("/lab/strategies").status_code == 401
    assert full_client.post("/lab/strategies", json=_STRATEGY).status_code == 401


def test_same_name_allowed_across_users(full_client, two_users):
    """Per-user unique constraint: two users can share a strategy name."""
    a, b = two_users
    assert full_client.post("/lab/strategies", json=_STRATEGY, headers=auth_header(a)).status_code == 201
    assert full_client.post("/lab/strategies", json=_STRATEGY, headers=auth_header(b)).status_code == 201
