"""Tests for on-demand snapshot refresh (app.backend.services.snapshot_refresh).

The background-thread machinery is exercised by calling the synchronous worker
``_run_refresh`` directly with mocked SnapshotBuilder/ScreenerRepository, plus
unit tests for the start_refresh lock + bad-market guard. No live data.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.backend.services import snapshot_refresh as sr


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts from a clean idle state and restores it after."""
    sr._state.__init__()  # reset dataclass to defaults
    yield
    sr._state.__init__()


def test_bad_market_raises():
    with pytest.raises(ValueError):
        sr.start_refresh("XX")


def test_start_refresh_blocked_when_running():
    # Simulate an in-flight build; start_refresh must NOT spawn a second.
    sr._state.running = True
    sr._state.market = "US"
    started, state = sr.start_refresh("US")
    assert started is False
    assert state["running"] is True
    assert state["market"] == "US"


def test_run_refresh_updates_state_and_inserts():
    """_run_refresh drives progress, upserts, and clears running on success."""
    fake_rows = [object(), object(), object()]

    def fake_build(market, kind, asof, on_progress=None):
        assert market == "US" and kind == "sp500"
        if on_progress:
            on_progress(1, 3)
            on_progress(3, 3)
        return fake_rows

    builder = MagicMock()
    builder.build_for_universe.side_effect = fake_build
    repo = MagicMock()
    repo.bulk_upsert.return_value = 3

    # Mark running as start_refresh would, then run the worker synchronously.
    sr._state.running = True
    sr._state.market = "US"
    with patch.object(sr, "SessionLocal", return_value=MagicMock()), \
         patch.object(sr, "ScreenerRepository", return_value=repo), \
         patch.object(sr, "SnapshotBuilder", return_value=builder):
        sr._run_refresh("US")

    repo.bulk_upsert.assert_called_once_with(fake_rows)
    assert sr._state.running is False          # cleared in finally
    assert sr._state.inserted == 3
    assert sr._state.done == 3 and sr._state.total == 3
    assert sr._state.error is None
    assert sr._state.finished_at is not None


def test_run_refresh_records_error_and_clears_running():
    """A build exception is captured in state.error; running still clears."""
    builder = MagicMock()
    builder.build_for_universe.side_effect = RuntimeError("yfinance boom")

    sr._state.running = True
    with patch.object(sr, "SessionLocal", return_value=MagicMock()), \
         patch.object(sr, "ScreenerRepository", return_value=MagicMock()), \
         patch.object(sr, "SnapshotBuilder", return_value=builder):
        sr._run_refresh("US")

    assert sr._state.running is False
    assert sr._state.error is not None and "boom" in sr._state.error
    assert sr._state.inserted is None


def test_cn_inits_ashare_metrics():
    """CN path constructs AshareMetrics; US path does not."""
    builder = MagicMock()
    builder.build_for_universe.return_value = []
    repo = MagicMock()
    repo.bulk_upsert.return_value = 0

    sr._state.running = True
    with patch.object(sr, "SessionLocal", return_value=MagicMock()), \
         patch.object(sr, "ScreenerRepository", return_value=repo), \
         patch.object(sr, "SnapshotBuilder", return_value=builder), \
         patch.object(sr, "AshareMetrics") as ashare_cls:
        sr._run_refresh("CN")
    ashare_cls.assert_called_once()
