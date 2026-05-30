"""Tenant-isolation tests for /scanner/* routes.

User A creates a scanner config; user B cannot list/get/patch/delete/run it.
User B also cannot read A's scan runs or watchlist entries (scoped via parent
config ownership — ScanRun has no user_id column; the chain is
  ScanRun.config_id → ScannerConfig.user_id).
User A can perform all operations on their own config/runs.

The scheduler dependency is stubbed so tests never touch APScheduler.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.backend.database.models import ScanRun, ScannerConfig, WatchlistEntry
from app.backend.services.scheduler_service import SchedulerService, get_scheduler_service
from tests.auth.conftest import auth_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_config(client, token, *, name="My Scanner"):
    r = client.post(
        "/scanner/configs",
        json={"name": name, "universe_kind": "sp500", "cron_expr": "0 21 * * 1-5"},
        headers=auth_header(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _seed_run(db_session, config_id: int):
    """Insert a COMPLETE scan run with one watchlist entry directly in the DB.

    Used to test run/entry read isolation without invoking the actual scanner.
    """
    run = ScanRun(config_id=config_id, status="COMPLETE")
    db_session.add(run)
    db_session.flush()  # get run.id
    entry = WatchlistEntry(
        scan_run_id=run.id,
        ticker="AAPL",
        composite_score=85.0,
        direction="bullish",
        event_score=80.0,
        event_severity=2.5,
        triggers=[],
        rank=1,
    )
    db_session.add(entry)
    db_session.commit()
    return run.id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scanner_client(full_client):
    """full_client with the scheduler dependency stubbed out."""
    fake_scheduler = MagicMock(spec=SchedulerService)
    fake_scheduler.run_now.return_value = 42
    full_client.app.dependency_overrides[get_scheduler_service] = lambda: fake_scheduler
    yield full_client
    # Restore
    full_client.app.dependency_overrides.pop(get_scheduler_service, None)


# ---------------------------------------------------------------------------
# Config isolation
# ---------------------------------------------------------------------------


class TestScannerConfigIsolation:
    def test_b_cannot_see_a_config_in_list(self, scanner_client, two_users):
        tok_a, tok_b = two_users
        cfg = _create_config(scanner_client, tok_a)
        cid = cfg["id"]

        r = scanner_client.get("/scanner/configs", headers=auth_header(tok_b))
        assert r.status_code == 200
        assert all(c["id"] != cid for c in r.json())

    def test_b_cannot_get_a_config(self, scanner_client, two_users):
        tok_a, tok_b = two_users
        cid = _create_config(scanner_client, tok_a)["id"]

        r = scanner_client.get(f"/scanner/configs/{cid}", headers=auth_header(tok_b))
        assert r.status_code == 404

    def test_b_cannot_patch_a_config(self, scanner_client, two_users):
        tok_a, tok_b = two_users
        cid = _create_config(scanner_client, tok_a)["id"]

        r = scanner_client.patch(
            f"/scanner/configs/{cid}",
            json={"name": "hijacked"},
            headers=auth_header(tok_b),
        )
        assert r.status_code == 404

    def test_b_cannot_delete_a_config(self, scanner_client, two_users):
        tok_a, tok_b = two_users
        cid = _create_config(scanner_client, tok_a)["id"]

        r = scanner_client.delete(f"/scanner/configs/{cid}", headers=auth_header(tok_b))
        assert r.status_code == 404

    def test_b_cannot_run_a_config(self, scanner_client, two_users):
        tok_a, tok_b = two_users
        cid = _create_config(scanner_client, tok_a)["id"]

        r = scanner_client.post(f"/scanner/configs/{cid}/run", headers=auth_header(tok_b))
        assert r.status_code == 404

    def test_a_can_manage_own_config(self, scanner_client, two_users):
        tok_a, _ = two_users
        cid = _create_config(scanner_client, tok_a)["id"]

        assert scanner_client.get(f"/scanner/configs/{cid}", headers=auth_header(tok_a)).status_code == 200
        assert (
            scanner_client.patch(
                f"/scanner/configs/{cid}",
                json={"top_n": 5},
                headers=auth_header(tok_a),
            ).status_code
            == 200
        )
        # Run triggers the stub scheduler, which returns run_id=42
        r = scanner_client.post(f"/scanner/configs/{cid}/run", headers=auth_header(tok_a))
        assert r.status_code == 202


# ---------------------------------------------------------------------------
# Scan run + watchlist entry isolation (scoped via config ownership)
# ---------------------------------------------------------------------------


class TestScanRunIsolation:
    def test_b_cannot_get_a_scan_run(self, scanner_client, two_users):
        """B gets 404 for a run whose parent config is owned by A."""
        tok_a, tok_b = two_users

        # Create config as A, then seed a run in the DB directly.
        cid = _create_config(scanner_client, tok_a)["id"]
        from sqlalchemy.orm import Session
        from app.backend.database import get_db

        # Extract the db session via the app's dependency — use the DB
        # override installed by full_client to access the in-memory DB.
        override_fn = scanner_client.app.dependency_overrides.get(get_db)
        gen = override_fn()
        db: Session = next(gen)
        try:
            run_id = _seed_run(db, cid)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

        # B cannot see A's run
        assert scanner_client.get(f"/scanner/runs/{run_id}", headers=auth_header(tok_b)).status_code == 404
        assert scanner_client.get(f"/scanner/runs/{run_id}/entries", headers=auth_header(tok_b)).status_code == 404

    def test_a_can_read_own_scan_run(self, scanner_client, two_users):
        """A can read their own run and entries."""
        tok_a, _ = two_users

        cid = _create_config(scanner_client, tok_a)["id"]
        from sqlalchemy.orm import Session
        from app.backend.database import get_db

        override_fn = scanner_client.app.dependency_overrides.get(get_db)
        gen = override_fn()
        db: Session = next(gen)
        try:
            run_id = _seed_run(db, cid)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

        assert scanner_client.get(f"/scanner/runs/{run_id}", headers=auth_header(tok_a)).status_code == 200
        r = scanner_client.get(f"/scanner/runs/{run_id}/entries", headers=auth_header(tok_a))
        assert r.status_code == 200
        assert len(r.json()["entries"]) == 1


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


def test_scanner_requires_auth(scanner_client):
    assert scanner_client.get("/scanner/configs").status_code == 401
    assert scanner_client.post("/scanner/configs", json={}).status_code == 401
    assert scanner_client.get("/scanner/runs/1").status_code == 401
