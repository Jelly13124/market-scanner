"""Task 3.1 — verify user_id column exists on all 11 user-owned tables."""


def test_user_id_added_to_owned_tables():
    from app.backend.database.models import Base
    owned = {"api_keys", "scanner_configs", "pipeline_runs", "pipeline_schedule",
             "notification_subscriptions", "research_reports", "user_watchlists",
             "analyze_flows", "strategies", "lab_chat_messages", "backtests"}
    for t in owned:
        cols = {c.name for c in Base.metadata.tables[t].columns}
        assert "user_id" in cols, f"{t} missing user_id"


def test_user_id_is_not_null_on_owned_tables():
    from app.backend.database.models import Base
    owned = {"api_keys", "scanner_configs", "pipeline_runs", "pipeline_schedule",
             "notification_subscriptions", "research_reports", "user_watchlists",
             "analyze_flows", "strategies", "lab_chat_messages", "backtests"}
    for t in owned:
        col = Base.metadata.tables[t].columns["user_id"]
        assert col.nullable is False, f"{t}.user_id must be NOT NULL"
