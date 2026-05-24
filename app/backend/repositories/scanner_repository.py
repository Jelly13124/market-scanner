"""Repositories for scanner persistence — configs, runs, and watchlist entries.

Mirrors the shape of FlowRepository / FlowRunRepository: sync, Session-injected,
commit/refresh per write. No business logic — services orchestrate.
"""

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import (
    AnalystTargetSnapshot,
    ScannerConfig,
    ScanRun,
    WatchlistEntry,
)


class ScannerConfigRepository:
    """CRUD for ScannerConfig."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        name: str,
        universe_kind: str,
        cron_expr: str = "0 21 * * 1-5",
        is_enabled: bool = True,
        top_n: int = 20,
        universe_tickers: Optional[List[str]] = None,
        weights: Optional[dict] = None,
        user_watchlist_id: Optional[int] = None,
        auto_sop_top_n: int = 0,
        auto_sop_use_personas: bool = False,
    ) -> ScannerConfig:
        config = ScannerConfig(
            name=name,
            universe_kind=universe_kind,
            universe_tickers=universe_tickers,
            cron_expr=cron_expr,
            is_enabled=is_enabled,
            top_n=top_n,
            weights=weights,
            user_watchlist_id=user_watchlist_id,
            auto_sop_top_n=auto_sop_top_n,
            auto_sop_use_personas=auto_sop_use_personas,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def get_by_id(self, config_id: int) -> Optional[ScannerConfig]:
        return self.db.query(ScannerConfig).filter(ScannerConfig.id == config_id).first()

    def list_all(self, enabled_only: bool = False) -> List[ScannerConfig]:
        q = self.db.query(ScannerConfig)
        if enabled_only:
            q = q.filter(ScannerConfig.is_enabled == True)  # noqa: E712
        return q.order_by(desc(ScannerConfig.updated_at), desc(ScannerConfig.created_at)).all()

    def update(
        self,
        config_id: int,
        *,
        name: Optional[str] = None,
        universe_kind: Optional[str] = None,
        universe_tickers: Optional[List[str]] = None,
        cron_expr: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        top_n: Optional[int] = None,
        weights: Optional[dict] = None,
        user_watchlist_id: Optional[int] = None,
        auto_sop_top_n: Optional[int] = None,
        auto_sop_use_personas: Optional[bool] = None,
        _set_watchlist_id: bool = False,
    ) -> Optional[ScannerConfig]:
        """Partial update. ``_set_watchlist_id`` is the explicit flag the
        route uses to distinguish "field omitted" from "field set to null"
        (since ``None`` is a legitimate value for ``user_watchlist_id``)."""
        config = self.get_by_id(config_id)
        if not config:
            return None
        if name is not None:
            config.name = name
        if universe_kind is not None:
            config.universe_kind = universe_kind
        if universe_tickers is not None:
            config.universe_tickers = universe_tickers
        if cron_expr is not None:
            config.cron_expr = cron_expr
        if is_enabled is not None:
            config.is_enabled = is_enabled
        if top_n is not None:
            config.top_n = top_n
        if weights is not None:
            config.weights = weights
        if _set_watchlist_id or user_watchlist_id is not None:
            config.user_watchlist_id = user_watchlist_id
        if auto_sop_top_n is not None:
            config.auto_sop_top_n = auto_sop_top_n
        if auto_sop_use_personas is not None:
            config.auto_sop_use_personas = auto_sop_use_personas
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete(self, config_id: int) -> bool:
        config = self.get_by_id(config_id)
        if not config:
            return False
        self.db.delete(config)
        self.db.commit()
        return True


class ScanRunRepository:
    """CRUD + lifecycle transitions for ScanRun."""

    def __init__(self, db: Session):
        self.db = db

    def create_pending(self, config_id: int) -> ScanRun:
        run = ScanRun(config_id=config_id, status="PENDING")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_running(self, run_id: int, universe_size: Optional[int] = None) -> Optional[ScanRun]:
        run = self.get_by_id(run_id)
        if not run:
            return None
        run.status = "RUNNING"
        run.started_at = datetime.utcnow()
        if universe_size is not None:
            run.universe_size = universe_size
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_complete(self, run_id: int) -> Optional[ScanRun]:
        run = self.get_by_id(run_id)
        if not run:
            return None
        run.status = "COMPLETE"
        run.completed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_error(self, run_id: int, message: str) -> Optional[ScanRun]:
        run = self.get_by_id(run_id)
        if not run:
            return None
        run.status = "ERROR"
        run.completed_at = datetime.utcnow()
        run.error_message = message
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_by_id(self, run_id: int) -> Optional[ScanRun]:
        return self.db.query(ScanRun).filter(ScanRun.id == run_id).first()

    def get_latest_for_config(self, config_id: int) -> Optional[ScanRun]:
        return (
            self.db.query(ScanRun)
            .filter(ScanRun.config_id == config_id)
            .order_by(desc(ScanRun.created_at))
            .first()
        )

    def list_for_config(self, config_id: int, limit: int = 50) -> List[ScanRun]:
        return (
            self.db.query(ScanRun)
            .filter(ScanRun.config_id == config_id)
            .order_by(desc(ScanRun.created_at))
            .limit(limit)
            .all()
        )

    def list_running(self) -> List[ScanRun]:
        """Used at startup to mark interrupted runs as ERROR."""
        return self.db.query(ScanRun).filter(ScanRun.status == "RUNNING").all()


class WatchlistEntryRepository:
    """Bulk insert + read for WatchlistEntry."""

    def __init__(self, db: Session):
        self.db = db

    def bulk_insert(self, scan_run_id: int, entries: List[dict[str, Any]]) -> int:
        """Insert ranked entries for a completed scan run.

        Each entry dict has keys: ticker, composite_score, direction,
        event_score, quant_score, triggers, rank.
        """
        rows = [
            WatchlistEntry(
                scan_run_id=scan_run_id,
                ticker=e["ticker"],
                composite_score=e["composite_score"],
                direction=e.get("direction", "neutral"),
                event_score=e.get("event_score", 0.0),
                quant_score=e.get("quant_score"),
                event_severity=e.get("event_severity", 0.0),
                triggers=e.get("triggers", []),
                rank=e["rank"],
            )
            for e in entries
        ]
        self.db.add_all(rows)
        self.db.commit()
        return len(rows)

    def list_for_run(self, scan_run_id: int) -> List[WatchlistEntry]:
        return (
            self.db.query(WatchlistEntry)
            .filter(WatchlistEntry.scan_run_id == scan_run_id)
            .order_by(WatchlistEntry.rank.asc())
            .all()
        )


class AnalystTargetSnapshotRepository:
    """Daily analyst-target snapshots — read/write for M9.d target-shift detector.

    Idempotent upsert via the unique (ticker, asof_date) constraint: scanning
    the same ticker twice on the same day refreshes the row rather than
    duplicating. ``list_for_tickers`` returns a dict keyed by ticker so the
    detector layer can do O(1) lookups during the scan.
    """

    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        *,
        ticker: str,
        asof_date: str,
        target_mean: Optional[float] = None,
        target_median: Optional[float] = None,
        target_high: Optional[float] = None,
        target_low: Optional[float] = None,
        current_price: Optional[float] = None,
        n_analysts: Optional[int] = None,
        commit: bool = True,
    ) -> AnalystTargetSnapshot:
        """Insert-or-update one snapshot.

        ``commit=False`` is the bulk-load mode — the caller is responsible
        for committing once after the loop. Without that, snapshotting a
        full S&P 500 universe issued 500 separate commits per scan.
        """
        existing = (
            self.db.query(AnalystTargetSnapshot)
            .filter(
                AnalystTargetSnapshot.ticker == ticker,
                AnalystTargetSnapshot.asof_date == asof_date,
            )
            .first()
        )
        if existing is not None:
            # Refresh values on second scan of the day. Don't churn created_at.
            existing.target_mean = target_mean
            existing.target_median = target_median
            existing.target_high = target_high
            existing.target_low = target_low
            existing.current_price = current_price
            existing.n_analysts = n_analysts
            if commit:
                self.db.commit()
                self.db.refresh(existing)
            return existing

        row = AnalystTargetSnapshot(
            ticker=ticker,
            asof_date=asof_date,
            target_mean=target_mean,
            target_median=target_median,
            target_high=target_high,
            target_low=target_low,
            current_price=current_price,
            n_analysts=n_analysts,
        )
        self.db.add(row)
        if commit:
            self.db.commit()
            self.db.refresh(row)
        return row

    def list_for_tickers(
        self,
        tickers: List[str],
        *,
        lookback_days: int = 14,
        end_date: Optional[str] = None,
    ) -> dict[str, List[AnalystTargetSnapshot]]:
        """Return {ticker: [snapshots ordered oldest→newest]} for the given
        tickers, restricted to dates within ``lookback_days`` of ``end_date``.

        ``end_date`` defaults to today's ISO date so callers can pass the
        scan's as-of date without manual datetime work.
        """
        if not tickers:
            return {}
        if end_date is None:
            end_date = datetime.utcnow().date().isoformat()
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return {}
        from datetime import timedelta
        start = (end - timedelta(days=lookback_days)).isoformat()

        rows = (
            self.db.query(AnalystTargetSnapshot)
            .filter(
                AnalystTargetSnapshot.ticker.in_(list(tickers)),
                AnalystTargetSnapshot.asof_date >= start,
                AnalystTargetSnapshot.asof_date <= end_date,
            )
            .order_by(AnalystTargetSnapshot.ticker.asc(), AnalystTargetSnapshot.asof_date.asc())
            .all()
        )

        out: dict[str, List[AnalystTargetSnapshot]] = {}
        for r in rows:
            out.setdefault(r.ticker, []).append(r)
        return out
