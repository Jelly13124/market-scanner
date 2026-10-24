"""Isolation tests: analyze flows are scoped per user_id."""
from tests.auth.conftest import auth_header

_FLOW = {"name": "My Flow", "included_sections": ["data_health"]}


def test_flow_isolation(full_client, two_users):
    a, b = two_users
    r = full_client.post("/analyze-flows", json=_FLOW, headers=auth_header(a))
    assert r.status_code == 201, r.text
    fid = r.json()["id"]

    # B's list does not contain A's flow
    b_list = full_client.get("/analyze-flows", headers=auth_header(b)).json()
    assert all(f["id"] != fid for f in b_list)

    # B cannot get, patch, or delete A's flow → 404
    assert full_client.get(f"/analyze-flows/{fid}", headers=auth_header(b)).status_code == 404
    assert full_client.patch(f"/analyze-flows/{fid}", json={"name": "hijack"}, headers=auth_header(b)).status_code == 404
    assert full_client.delete(f"/analyze-flows/{fid}", headers=auth_header(b)).status_code == 404

    # A still owns it
    assert full_client.get(f"/analyze-flows/{fid}", headers=auth_header(a)).status_code == 200


def test_flow_requires_auth(full_client):
    assert full_client.get("/analyze-flows").status_code == 401
    assert full_client.post("/analyze-flows", json=_FLOW).status_code == 401


def test_same_name_allowed_across_users(full_client, two_users):
    """Per-user unique constraint: two users can share a flow name."""
    a, b = two_users
    assert full_client.post("/analyze-flows", json=_FLOW, headers=auth_header(a)).status_code == 201
    assert full_client.post("/analyze-flows", json=_FLOW, headers=auth_header(b)).status_code == 201
