"""Read the persisted Scanner selection used as the origin of an analysis."""

from datetime import timezone

from sqlalchemy.orm import Session

from app.backend.database.models import ScannerConfig, ScanRun, UniverseSnapshot, WatchlistEntry
from v2.data.ashare.symbol import is_ashare


def owned_scan_runs(db: Session, user_id: int):
    """Require the config owner and, for new runs, the immutable universe owner."""
    return (
        db.query(ScanRun)
        .join(ScannerConfig, ScannerConfig.id == ScanRun.config_id)
        .outerjoin(UniverseSnapshot, UniverseSnapshot.id == ScanRun.universe_snapshot_id)
        .filter(ScannerConfig.user_id == user_id)
        .filter((ScanRun.universe_snapshot_id.is_(None)) | (UniverseSnapshot.user_id == user_id))
    )


def scan_evidence(entry: WatchlistEntry, run: ScanRun) -> dict:
    config = run.detector_config or {}
    started_at = run.started_at
    if started_at is not None and started_at.tzinfo is None:
        # SQLite drops tzinfo from the UTC start time recorded by the Scanner.
        started_at = started_at.replace(tzinfo=timezone.utc)
    return {
        "scan_result_id": entry.id,
        "scan_run_id": run.id,
        "universe_snapshot_id": run.universe_snapshot_id,
        "ticker": entry.ticker,
        "market": "cn" if is_ashare(entry.ticker) else "us",
        "rank": entry.rank,
        "direction": entry.direction,
        "composite_score": entry.composite_score,
        "scan_started_at": started_at.isoformat() if started_at is not None else None,
        "scan_as_of": config.get("as_of"),
        "triggers": entry.triggers,
        "outcome": (run.outcomes or {}).get(entry.ticker),
        "detector_config": run.detector_config,
    }


def resolve_scan_evidence(db: Session, source_id: int | str, *, user_id: int, ticker: str, market: str):
    if isinstance(source_id, str):
        return _archived_scan_evidence(source_id, user_id=user_id, ticker=ticker, market=market)
    row = (owned_scan_runs(db, user_id)
           .join(WatchlistEntry, WatchlistEntry.scan_run_id == ScanRun.id)
           .add_entity(WatchlistEntry)
           .filter(WatchlistEntry.id == source_id, WatchlistEntry.ticker == ticker)
           .one_or_none())
    evidence = scan_evidence(row.WatchlistEntry, row.ScanRun) if row else None
    return evidence if evidence and evidence["market"] == market else None


def _archived_scan_evidence(source_id: str, *, user_id: int, ticker: str, market: str):
    """Read legacy Mongo identifiers in their own namespace, without allocating SQL rows."""
    from bson import ObjectId
    from src.storage.history import SELECTED_SIGNAL_FILTER
    from src.storage.mongo import get_store, json_value

    def read(archive):
        owner = str(user_id)
        result = archive.scan_results.find_one({"_id": ObjectId(source_id), "owner_id": owner, **SELECTED_SIGNAL_FILTER})
        if result is None:
            return None
        instrument = archive.instruments.find_one({
            "_id": result["instrument_id"], "symbol": ticker, "market": market.upper(),
        })
        run = archive.scan_runs.find_one({"_id": result["scan_run_id"], "owner_id": owner})
        if instrument is None or run is None:
            return None
        quality = result.get("quality", {})
        sessions = quality.get("signal_sessions", {})
        decisions = result.get("detector_results", [])
        triggers = quality.get("legacy_triggers")
        if triggers is None:
            matches = quality.get("rule_group", {}).get("matches")
            triggers = [dict(item, signal_session=sessions.get(item["detector"]), severity_z=item.get("severity"))
                        for item in decisions if item.get("status") == "triggered"
                        and (matches is None or matches.get(item["detector"]) is True)]
        return json_value({
            "scan_result_id": None, "scan_run_id": None, "universe_snapshot_id": None,
            "mongo_scan_result_id": str(result["_id"]), "mongo_scan_run_id": str(run["_id"]),
            "ticker": ticker, "market": market, "rank": result.get("rank"),
            "direction": result.get("direction"), "composite_score": result.get("composite_score"),
            "scan_started_at": run.get("started_at"),
            "scan_as_of": run.get("scan_date"), "triggers": triggers,
            "outcome": {"outcome": result.get("outcome"), "selected": result.get("selected"),
                        "detector_results": decisions, "quality": quality},
            "detector_config": (run.get("config_snapshot") or {}).get("detector_config"),
        })

    return get_store().execute(read, required=True)
