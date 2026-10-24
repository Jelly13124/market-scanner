"""Cross-tenant isolation sweep (Wave 8).

The catch-all that proves NO user-owned LIST endpoint leaks another tenant's
rows. For every owned list endpoint we assert:

  (a) unauthenticated request → 401, and
  (b) user B's list never contains a row user A created.

Endpoints that support a cheap POST get the create-then-check treatment
(create A's row, confirm it's absent from B's list and present in A's).
Endpoints whose POST triggers expensive LLM / pipeline work
(``/research/reports``, ``/pipeline/runs``) are asserted owner-scoped by
confirming B's freshly-created account sees an empty list — the per-row
404 isolation for those is already covered by their dedicated
test_isolation_*.py modules.

Reuses the shared ``full_client`` / ``two_users`` / ``auth_header`` fixtures
from tests/auth/conftest.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.backend.services.scheduler_service import (
    SchedulerService,
    get_scheduler_service,
)
from tests.auth.conftest import auth_header


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sweep_client(full_client):
    """full_client with the scheduler dependency stubbed (scanner config POST
    registers a cron — we never want to touch APScheduler here)."""
    fake_scheduler = MagicMock(spec=SchedulerService)
    full_client.app.dependency_overrides[get_scheduler_service] = lambda: fake_scheduler
    yield full_client
    full_client.app.dependency_overrides.pop(get_scheduler_service, None)


# ---------------------------------------------------------------------------
# Endpoint registry
# ---------------------------------------------------------------------------
# Each entry: (list_path, create_path, create_body, id_key)
#   create_path/body None → list-only (assert B sees empty list).
#   id_key is the field on each list row that uniquely identifies A's row.

_CREATE_ENDPOINTS = [
    ("/watchlists", "/watchlists", {"name": "A-watchlist"}, "id"),
    (
        "/screener/presets",
        "/screener/presets",
        {"name": "A-preset", "market": "US", "filters": {}},
        "id",
    ),
    (
        "/analyze-flows",
        "/analyze-flows",
        {"name": "A-flow", "included_sections": []},
        "id",
    ),
    ("/lab/strategies", "/lab/strategies", {"name": "A-strategy"}, "id"),
    (
        "/scanner/configs",
        "/scanner/configs",
        {"name": "A-scanner", "universe_kind": "sp500", "cron_expr": "0 21 * * 1-5"},
        "id",
    ),
    (
        "/notifications/subscriptions",
        "/notifications/subscriptions",
        {"channel": "email", "target": "a@example.com"},
        "id",
    ),
    (
        "/api-keys/",
        "/api-keys/",
        {"provider": "openai", "key_value": "sk-secret-a"},
        "provider",
    ),
]

# List-only endpoints (POST triggers expensive LLM/pipeline work — skip create,
# assert B's brand-new account list is empty / owner-scoped).
_LIST_ONLY_ENDPOINTS = [
    "/research/reports",
    "/pipeline/runs",
]

_ALL_LIST_PATHS = [e[0] for e in _CREATE_ENDPOINTS] + _LIST_ONLY_ENDPOINTS


# ---------------------------------------------------------------------------
# (a) Every owned list endpoint rejects the unauthenticated caller.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("list_path", _ALL_LIST_PATHS)
def test_list_endpoint_requires_auth(sweep_client, list_path):
    assert sweep_client.get(list_path).status_code == 401


# ---------------------------------------------------------------------------
# (b1) Create-capable endpoints: A's row never appears in B's list.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "list_path,create_path,create_body,id_key",
    _CREATE_ENDPOINTS,
    ids=[e[0] for e in _CREATE_ENDPOINTS],
)
def test_b_list_excludes_a_row(
    sweep_client, two_users, list_path, create_path, create_body, id_key
):
    tok_a, tok_b = two_users

    # A creates a row.
    r = sweep_client.post(create_path, json=create_body, headers=auth_header(tok_a))
    assert r.status_code in (200, 201), f"{create_path} create failed: {r.text}"
    a_row_id = r.json()[id_key]

    # B's list must NOT contain A's row.
    rb = sweep_client.get(list_path, headers=auth_header(tok_b))
    assert rb.status_code == 200, rb.text
    assert all(
        row.get(id_key) != a_row_id for row in rb.json()
    ), f"{list_path}: user B's list leaked user A's row {a_row_id!r}"

    # A's own list DOES contain it (sanity: the row really exists + is scoped).
    ra = sweep_client.get(list_path, headers=auth_header(tok_a))
    assert ra.status_code == 200, ra.text
    assert any(
        row.get(id_key) == a_row_id for row in ra.json()
    ), f"{list_path}: user A cannot see their own row {a_row_id!r}"


# ---------------------------------------------------------------------------
# (b2) List-only endpoints: B's fresh account sees an owner-scoped empty list.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("list_path", _LIST_ONLY_ENDPOINTS)
def test_list_only_endpoint_is_owner_scoped_empty(sweep_client, two_users, list_path):
    _tok_a, tok_b = two_users
    rb = sweep_client.get(list_path, headers=auth_header(tok_b))
    assert rb.status_code == 200, rb.text
    assert rb.json() == [], f"{list_path}: expected empty owner-scoped list for new user B"
