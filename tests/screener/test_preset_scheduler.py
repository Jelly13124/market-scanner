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
