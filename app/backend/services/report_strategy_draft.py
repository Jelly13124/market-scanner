"""Recover a strategy entry group from the completed report's saved inputs."""

from datetime import date

from pydantic import ValidationError

from app.backend.database.models import UniverseSnapshot
from src.lab.spec.strategy import StrategySpec
from v2.rules.spec import RuleGroup


def draft_inputs(report):
    request = report.analyze_request_json or {}
    if request.get("analysis_status") not in (None, "succeeded", "partial"):
        return None
    source = request.get("source_scan_evidence") or {}
    snapshot_id = source.get("universe_snapshot_id")
    if (source.get("market") != "us" or source.get("ticker") != report.ticker or not isinstance(snapshot_id, int)
            or not isinstance(source.get("scan_result_id"), int)):
        return None
    group = ((source.get("detector_config") or {}).get("weights") or {}).get("rule_group")
    try:
        rules = RuleGroup.model_validate(group)
    except ValidationError:
        return None
    if len(rules.signals) > 5:
        return None
    return source, rules


def matches_report_universe(snapshot, ticker):
    return snapshot.origin == "scanner" and snapshot.market.upper() == "US" and ticker in snapshot.tickers


def eligible_report_ids(db, reports, user_id):
    """Load only the owner's frozen universes, once for the whole report page."""
    candidates = {}
    for report in reports:
        inputs = draft_inputs(report)
        if inputs is not None:
            candidates[report.id] = (report.ticker, inputs[0]["universe_snapshot_id"])
    if not candidates:
        return set()
    snapshot_ids = {snapshot_id for _, snapshot_id in candidates.values()}
    snapshots = {row.id: row for row in db.query(UniverseSnapshot).filter(
        UniverseSnapshot.user_id == user_id, UniverseSnapshot.id.in_(snapshot_ids)
    )}
    return {report_id for report_id, (ticker, snapshot_id) in candidates.items()
            if snapshot_id in snapshots and matches_report_universe(snapshots[snapshot_id], ticker)}


def validate_draft_spec(spec):
    """Require concrete, reviewable execution settings for a report-linked draft."""
    parsed = StrategySpec.model_validate(spec, extra="forbid")
    RuleGroup.model_validate(spec["entry"])
    config = spec.get("backtest_config") or {}
    required = {"start_date", "end_date", "commission_bps", "slippage_bps", "starting_capital_usd",
                "max_concurrent_positions", "is_oos_split"}
    if required.difference(config):
        raise ValueError("Choose dates, capital, allocation limits, split and costs before confirmation")
    start = date.fromisoformat(config["start_date"] or "")
    end = date.fromisoformat(config["end_date"] or "")
    if start >= end:
        raise ValueError("Choose a start date before the end date")
    if parsed.sizing.type != "fixed_pct" or "pct" not in spec["sizing"]:
        raise ValueError("Analyze drafts require an explicit fixed percentage allocation")
    if parsed.backtest_config.full_position_policy != "skip":
        raise ValueError("Analyze drafts support skipping entries when fully invested")
    return parsed.model_dump(exclude_none=True)
