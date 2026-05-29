"""On-demand screener snapshot refresh.

The nightly cron (``_run_snapshot_job_body``) rebuilds the full US+CN snapshot
at 22:00 ET. This module lets the UI trigger a refresh of a SINGLE market on
demand, running the (multi-minute) universe build on a background thread so the
HTTP request returns immediately. Progress is tracked in an in-memory singleton
the UI polls via ``GET /screener/snapshot/refresh``.

A process-wide lock guarantees only one refresh runs at a time — repeated
button clicks (or a click racing the cron) won't fire concurrent universe pulls
at yfinance/akshare.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone

from app.backend.database import SessionLocal
from app.backend.repositories.screener_repository import ScreenerRepository
from src.screener.ashare_metrics import AshareMetrics
from src.screener.snapshot_builder import SnapshotBuilder

logger = logging.getLogger(__name__)

_UNIVERSE_KIND = {"US": "sp500", "CN": "csi300"}


@dataclass
class _RefreshState:
    running: bool = False
    market: str | None = None
    done: int = 0
    total: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    inserted: int | None = None
    error: str | None = None

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "market": self.market,
            "done": self.done,
            "total": self.total,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "inserted": self.inserted,
            "error": self.error,
        }


_state = _RefreshState()
_lock = threading.Lock()


def get_refresh_state() -> dict:
    """Return a copy of the current refresh state for polling."""
    with _lock:
        return _state.snapshot()


def start_refresh(market: str) -> tuple[bool, dict]:
    """Begin a single-market snapshot rebuild on a background thread.

    Returns ``(started, state)``. ``started=False`` means a refresh was already
    in flight — the caller should just poll the returned state.
    """
    market = market.upper()
    if market not in _UNIVERSE_KIND:
        raise ValueError(f"unsupported market: {market!r} (expected US or CN)")

    with _lock:
        if _state.running:
            return False, _state.snapshot()
        # Reset + mark running atomically so a second caller can't slip through.
        _state.running = True
        _state.market = market
        _state.done = 0
        _state.total = 0
        _state.started_at = datetime.now(timezone.utc).isoformat()
        _state.finished_at = None
        _state.inserted = None
        _state.error = None
        state_copy = _state.snapshot()

    thread = threading.Thread(
        target=_run_refresh, args=(market,), daemon=True,
        name=f"snapshot-refresh-{market}",
    )
    thread.start()
    return True, state_copy


def _run_refresh(market: str) -> None:
    """Background worker: build one market's universe, upsert, update state.

    Owns its own DB session (never share a Session across threads). Always
    clears ``running`` and stamps ``finished_at`` in the finally block so a
    failed build can't wedge the lock.
    """
    db = SessionLocal()
    try:
        repo = ScreenerRepository(db)
        ashare = None
        if market == "CN":
            try:
                ashare = AshareMetrics()
            except Exception as e:
                logger.warning("AshareMetrics init failed (CN refresh degraded): %s", e)
        builder = SnapshotBuilder(ashare_metrics=ashare)

        def on_progress(i: int, total: int) -> None:
            with _lock:
                _state.done = i
                _state.total = total

        rows = builder.build_for_universe(
            market, _UNIVERSE_KIND[market], date.today(), on_progress=on_progress,
        )
        inserted = repo.bulk_upsert(rows)
        with _lock:
            _state.inserted = inserted
        logger.info("on-demand snapshot %s: %d rows", market, inserted)
    except Exception as e:
        logger.exception("on-demand snapshot %s failed: %s", market, e)
        with _lock:
            _state.error = str(e)
    finally:
        db.close()
        with _lock:
            _state.running = False
            _state.finished_at = datetime.now(timezone.utc).isoformat()
