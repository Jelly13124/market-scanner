from __future__ import annotations
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.backend.repositories.screener_repository import SnapshotRow


def test_constants():
    from app.backend.services.scheduler_service import (
        SCREENER_PRESET_CRON_EXPR, SCREENER_PRESET_JOB_ID)
    assert SCREENER_PRESET_CRON_EXPR == "5 22 * * *"
    assert SCREENER_PRESET_JOB_ID == "screener_presets"


def test_enabled_preset_runs_and_notifies():
    from app.backend.services import scheduler_service as ss
    enabled = MagicMock(id=1, name="p", market="US", filters_json={"pe_max": 20},
                        sort_by="market_cap", sort_dir="desc",
                        notify_channels=["email"])
    repo = MagicMock(); repo.list_enabled.return_value = [enabled]
    screener = MagicMock()
    screener.query.return_value = (
        [SnapshotRow(ticker="JPM", market="US", snapshot_date=date(2026, 5, 28),
                     pe_ttm=Decimal("11"))], 1)
    dispatcher = MagicMock()
    with patch.object(ss, "SessionLocal", return_value=MagicMock()), \
         patch.object(ss, "ScreenerPresetRepository", return_value=repo), \
         patch.object(ss, "ScreenerRepository", return_value=screener), \
         patch.object(ss, "NotificationDispatcher", return_value=dispatcher):
        ss._run_preset_job_body()
    repo.mark_run.assert_called_once()
    dispatcher.dispatch_screener_match.assert_called_once()
    assert dispatcher.dispatch_screener_match.call_args.kwargs.get("event_type") == "screener.match"


def test_zero_match_does_not_notify():
    from app.backend.services import scheduler_service as ss
    enabled = MagicMock(id=1, name="p", market="US", filters_json={},
                        sort_by="market_cap", sort_dir="desc",
                        notify_channels=["email"])
    repo = MagicMock(); repo.list_enabled.return_value = [enabled]
    screener = MagicMock(); screener.query.return_value = ([], 0)
    dispatcher = MagicMock()
    with patch.object(ss, "SessionLocal", return_value=MagicMock()), \
         patch.object(ss, "ScreenerPresetRepository", return_value=repo), \
         patch.object(ss, "ScreenerRepository", return_value=screener), \
         patch.object(ss, "NotificationDispatcher", return_value=dispatcher):
        ss._run_preset_job_body()
    repo.mark_run.assert_called_once()
    dispatcher.dispatch_screener_match.assert_not_called()


def test_two_users_each_match_notifies_only_owner():
    """Wave 6 tenancy: the cron iterates ALL users' enabled presets, and each
    preset's match dispatches with that preset's OWNER user_id — so a user's
    match never fans out to another tenant. The dispatcher's own scoping is
    unit-tested separately; here we assert the cron passes the right owner."""
    from app.backend.services import scheduler_service as ss
    preset_a = MagicMock(id=1, user_id=101, name="A", market="US",
                         filters_json={"pe_max": 20}, sort_by="market_cap",
                         sort_dir="desc", notify_channels=["email"])
    preset_b = MagicMock(id=2, user_id=202, name="B", market="US",
                         filters_json={"pe_max": 15}, sort_by="market_cap",
                         sort_dir="desc", notify_channels=["webhook"])
    repo = MagicMock(); repo.list_enabled.return_value = [preset_a, preset_b]
    screener = MagicMock()
    screener.query.return_value = (
        [SnapshotRow(ticker="JPM", market="US", snapshot_date=date(2026, 5, 28),
                     pe_ttm=Decimal("11"))], 1)
    dispatcher = MagicMock()
    with patch.object(ss, "SessionLocal", return_value=MagicMock()), \
         patch.object(ss, "ScreenerPresetRepository", return_value=repo), \
         patch.object(ss, "ScreenerRepository", return_value=screener), \
         patch.object(ss, "NotificationDispatcher", return_value=dispatcher):
        ss._run_preset_job_body()

    # Both users' presets were processed (mark_run for each).
    assert repo.mark_run.call_count == 2
    # Each match dispatched exactly once, each scoped to its own owner.
    assert dispatcher.dispatch_screener_match.call_count == 2
    owners = {c.kwargs.get("user_id") for c in dispatcher.dispatch_screener_match.call_args_list}
    assert owners == {101, 202}
    # And every dispatch is owner-scoped (no global/unscoped fan-out).
    assert all(c.kwargs.get("user_id") is not None
               for c in dispatcher.dispatch_screener_match.call_args_list)
