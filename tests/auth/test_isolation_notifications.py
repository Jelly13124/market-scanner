"""Tenant-isolation tests for /notifications/subscriptions.

User A creates a subscription; user B cannot list, get, update, or delete it
(404/absent). User A can.  The dispatcher's list_enabled_for_event remains
unscoped — verified by creating subs for two users and confirming both appear.
"""

from __future__ import annotations

import pytest

from tests.auth.conftest import auth_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_sub(client, token, *, target="user@example.com"):
    r = client.post(
        "/notifications/subscriptions",
        json={"channel": "email", "target": target},
        headers=auth_header(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Isolation tests
# ---------------------------------------------------------------------------


class TestSubscriptionIsolation:
    def test_user_a_subscription_invisible_to_b_in_list(
        self, full_client, two_users,
    ):
        """B's list returns empty; A's subscription is not visible to B."""
        tok_a, tok_b = two_users
        _create_sub(full_client, tok_a, target="a@example.com")

        r = full_client.get("/notifications/subscriptions", headers=auth_header(tok_b))
        assert r.status_code == 200
        assert r.json() == []

    def test_user_b_cannot_get_a_subscription(self, full_client, two_users):
        """GET /notifications/subscriptions/{id} by B on A's sub → 404."""
        tok_a, tok_b = two_users
        sub = _create_sub(full_client, tok_a)

        r = full_client.get(
            f"/notifications/subscriptions/{sub['id']}",
            headers=auth_header(tok_b),
        )
        assert r.status_code == 404

    def test_user_b_cannot_update_a_subscription(self, full_client, two_users):
        """PATCH /notifications/subscriptions/{id} by B on A's sub → 404."""
        tok_a, tok_b = two_users
        sub = _create_sub(full_client, tok_a)

        r = full_client.patch(
            f"/notifications/subscriptions/{sub['id']}",
            json={"enabled": False},
            headers=auth_header(tok_b),
        )
        assert r.status_code == 404

    def test_user_b_cannot_delete_a_subscription(self, full_client, two_users):
        """DELETE /notifications/subscriptions/{id} by B on A's sub → 404;
        sub still exists for A."""
        tok_a, tok_b = two_users
        sub = _create_sub(full_client, tok_a)

        r = full_client.delete(
            f"/notifications/subscriptions/{sub['id']}",
            headers=auth_header(tok_b),
        )
        assert r.status_code == 404

        # Still exists for A
        r2 = full_client.get(
            f"/notifications/subscriptions/{sub['id']}",
            headers=auth_header(tok_a),
        )
        assert r2.status_code == 200

    def test_user_a_can_delete_own_subscription(self, full_client, two_users):
        """A deletes their own sub; subsequent GET returns 404."""
        tok_a, _ = two_users
        sub = _create_sub(full_client, tok_a)

        r = full_client.delete(
            f"/notifications/subscriptions/{sub['id']}",
            headers=auth_header(tok_a),
        )
        assert r.status_code == 204

        r2 = full_client.get(
            f"/notifications/subscriptions/{sub['id']}",
            headers=auth_header(tok_a),
        )
        assert r2.status_code == 404
