import sqlalchemy as sa
from sqlalchemy import Column, Integer, Float, String, DateTime, Text, Boolean, JSON, ForeignKey, Index, UniqueConstraint, BigInteger, Date, Numeric
from sqlalchemy.sql import func, text
from .connection import Base


class ApiKey(Base):
    """Table to store API keys for various services"""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # API key details
    provider = Column(String(100), nullable=False, index=True)  # e.g., "ANTHROPIC_API_KEY"
    key_value = Column(Text, nullable=False)  # The actual API key (encrypted in production)
    is_active = Column(Boolean, default=True)  # Enable/disable without deletion

    # Optional metadata
    description = Column(Text, nullable=True)  # Human-readable description
    last_used = Column(DateTime(timezone=True), nullable=True)  # Track usage

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_api_key_user_provider"),)


class ReportRecipient(Base):
    """Extra email addresses a user binds to receive their reports.

    Each must be verified (the user clicks an emailed link) before it receives
    reports. Capped at 3 per user in the route layer. Scoped by user_id like
    every other owned table. Created lazily via Base.metadata.create_all — this
    table has no alembic migration (create_all is the schema source of truth)."""

    __tablename__ = "report_recipients"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, index=True)
    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)
    email = Column(String(320), nullable=False)
    is_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_report_recipient_user_email"),)


class ReportSchedule(Base):
    """A user's scheduled auto-analyze: run the SOP for a list of tickers on a
    cron and email each rendered report to the user's verified recipients.

    Created by create_all (no migration). The cron is (un)registered with the
    APScheduler-backed SchedulerService as rows are created / toggled / deleted.
    Scoped by user_id like every other owned table."""

    __tablename__ = "report_schedules"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, index=True)
    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)
    tickers = Column(JSON, nullable=False, default=list)  # list[str]
    cron_expr = Column(String(120), nullable=False)  # interpreted in America/New_York
    report_language = Column(String(4), nullable=False, default="en")  # "en" | "zh"
    is_enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ScannerConfig(Base):
    """Saved configuration for the daily market scanner."""

    __tablename__ = "scanner_configs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    name = Column(String(200), nullable=False)
    # 'sp500' | 'russell3000' | 'all_us' | 'custom'
    universe_kind = Column(String(50), nullable=False)
    # Only populated when universe_kind == 'custom'
    universe_tickers = Column(JSON, nullable=True)

    # 5-field cron expression in America/New_York; validated by APScheduler at save time
    cron_expr = Column(String(100), nullable=False, default="0 21 * * 1-5")
    is_enabled = Column(Boolean, nullable=False, default=True)
    top_n = Column(Integer, nullable=False, default=20)

    # Scoring weights override; null means use defaults from v2/scanner/scoring.py
    weights = Column(JSON, nullable=True)

    # Phase 5C — when universe_kind == 'watchlist', points at the UserWatchlist
    # row whose ``tickers`` list becomes the scan universe. Null for non-watchlist
    # kinds (sp500/nasdaq100/custom/etc.).
    user_watchlist_id = Column(
        Integer,
        ForeignKey("user_watchlists.id"),
        nullable=True,
        index=True,
    )

    # Phase 5E — when > 0, the scanner runs full SOP analysis on the top-N
    # watchlist entries after each scan completes and emits ONE bundled email
    # with all reports. 0 = disabled (default; the legacy behavior).
    auto_sop_top_n = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Phase 5E — whether the auto-SOP follow-up routes sections through the
    # persona router (more LLM calls, richer reports) or runs objective.
    auto_sop_use_personas = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
    )
    # When True, email the watchlist ticker list to the user's verified report
    # recipients after a scan completes. Delivery wiring is a later task.
    email_watchlist = Column(Boolean, nullable=False, default=False, server_default=sa.false())
    # When True, also email the auto-SOP reports to those recipients.
    email_reports = Column(Boolean, nullable=False, default=False, server_default=sa.false())

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)


class ScanRun(Base):
    """A single execution of the scanner against a configured universe."""

    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("scanner_configs.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # PENDING -> RUNNING -> COMPLETE | ERROR
    status = Column(String(50), nullable=False, default="PENDING")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    universe_size = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)


class WatchlistEntry(Base):
    """One ranked ticker produced by a ScanRun."""

    __tablename__ = "watchlist_entries"

    id = Column(Integer, primary_key=True, index=True)
    scan_run_id = Column(Integer, ForeignKey("scan_runs.id"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)

    composite_score = Column(Float, nullable=False)
    # 'bullish' | 'bearish' | 'neutral'
    direction = Column(String(20), nullable=False, default="neutral")
    event_score = Column(Float, nullable=False, default=0.0)
    quant_score = Column(Float, nullable=True)
    # Raw max |severity_z| pre-clip — tiebreaker when composite_score = 100.
    event_severity = Column(Float, nullable=False, default=0.0)

    # list of EventTrigger dicts (detector, severity_z, direction, reason, components, asof_date)
    triggers = Column(JSON, nullable=False, default=list)
    rank = Column(Integer, nullable=False)


class AnalystTargetSnapshot(Base):
    """Daily snapshot of analyst price-target consensus per ticker.

    Written by ``ScannerService`` at the start of each scan (one row per
    ``(ticker, asof_date)``; subsequent scans on the same day upsert).
    Read back by ``TargetPriceChangeDetector`` to compute N-day target
    drift — the signal that yfinance's static ``analyst_price_targets``
    can't express by itself.

    Storing the full mean/median/high/low spread gives the detector
    freedom to switch which point statistic it z-scores against; v1 uses
    ``target_median``.
    """

    __tablename__ = "analyst_target_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    # ISO YYYY-MM-DD; one snapshot per ticker per day (enforced below).
    asof_date = Column(String(10), nullable=False, index=True)

    target_mean = Column(Float, nullable=True)
    target_median = Column(Float, nullable=True)
    target_high = Column(Float, nullable=True)
    target_low = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    n_analysts = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("ticker", "asof_date", name="uq_target_snapshot_ticker_date"),)


class PipelineRun(Base):
    """One end-to-end scanner→agent pipeline execution.

    Created in ``PENDING`` by ``POST /pipeline/run``; the background task
    flips it to ``RUNNING`` then ``COMPLETE`` / ``ERROR``. JSON blobs hold
    the full watchlist + per-agent signals + final portfolio_manager
    decisions so the detail UI can render without re-running anything.
    """

    __tablename__ = "pipeline_runs"

    # UUID hex (not autoincrement) so we can return the run_id to the
    # client BEFORE the DB row is inserted (background task creates it).
    id = Column(String(32), primary_key=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # ISO YYYY-MM-DD; the trading-day the scanner replayed against.
    scan_date = Column(String(10), nullable=False, index=True)

    # "balanced" | "value" | "growth" | "quick" | "custom"
    template = Column(String(50), nullable=False)
    # list[str] of analyst keys actually run for this pipeline.
    selected_analysts = Column(JSON, nullable=False)
    top_n = Column(Integer, nullable=False)
    universe = Column(String(50), nullable=False)

    # PENDING -> RUNNING -> COMPLETE | ERROR
    status = Column(String(50), nullable=False, default="PENDING", index=True)
    error = Column(Text, nullable=True)

    # JSON blobs — see v2.pipeline.orchestrator.PipelineResult shape.
    # Stored as JSON columns rather than a normalized schema because v1
    # query patterns are "fetch run by id" + "list recent runs"; no
    # cross-run aggregation needed yet.
    watchlist_json = Column(JSON, nullable=True)  # list[ScoredEntry.model_dump()]
    agent_decisions_json = Column(JSON, nullable=True)  # portfolio_manager output
    analyst_signals_json = Column(JSON, nullable=True)  # per-agent per-ticker signals
    duration_seconds = Column(Float, nullable=True)

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)


class PipelineSchedule(Base):
    """Per-user config for the daily pipeline cron job.

    Wave 4 tenancy: this was a single-row id=1 singleton; it is now one row
    per user (``user_id`` FK). The route creates each user's row lazily on
    first ``GET /pipeline/schedule`` and the cron uses the seed owner's row.
    Keeping it as a table rather than a config file means we can hot-edit
    via the UI without redeploying.
    """

    __tablename__ = "pipeline_schedule"

    # Plain autoincrement PK. (Used to carry ``default=1`` for the singleton
    # convention — removed in Wave 4 so per-user rows don't all collide on
    # id=1. SQLite INTEGER PRIMARY KEY auto-increments natively; no DDL/
    # migration change is needed — the existing column already supports it.)
    id = Column(Integer, primary_key=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Opt-in switch — daily LLM cost is non-trivial, ship OFF by default
    # so the cron doesn't burn tokens on first install (plan §Top risks).
    enabled = Column(Boolean, nullable=False, default=False)

    # Pipeline parameters baked into the daily run.
    top_n = Column(Integer, nullable=False, default=5)
    template = Column(String(50), nullable=False, default="balanced")
    universe = Column(String(50), nullable=False, default="nasdaq100")
    model_name = Column(String(100), nullable=False, default="gpt-4.1")
    model_provider = Column(String(50), nullable=False, default="OpenAI")

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)


class NotificationSubscription(Base):
    """One outbound notification target. Multiple rows per event_type are fine.

    ``channel`` discriminates how ``target`` is interpreted:
      * ``email``   → ``target`` is an email address sent via Resend API
      * ``webhook`` → ``target`` is an HTTPS URL POSTed by the WebhookHandler

    The dispatcher fans out the pipeline-completion event to every enabled
    row matching the event_type. Delivery attempts are recorded in
    ``NotificationDelivery`` for debugging.
    """

    __tablename__ = "notification_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    enabled = Column(Boolean, nullable=False, default=True, index=True)
    event_type = Column(String(50), nullable=False, default="pipeline.completed", index=True)
    channel = Column(String(20), nullable=False)  # 'email' | 'webhook'
    target = Column(String(500), nullable=False)
    label = Column(String(200), nullable=True)
    # Optional header value for webhook channel (e.g. "Bearer xxx" or
    # "X-Hub-Signature: ..."). Email channel ignores this.
    auth_header = Column(String(500), nullable=True)

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)


class NotificationDelivery(Base):
    """Log of every dispatch attempt. Bounded by retention you set elsewhere.

    Keeping a full delivery audit lets the UI surface "this subscription
    silently failed" without users having to dig in server logs. We
    record both ok and error attempts so the absence of a row tells you
    the dispatcher never fired.
    """

    __tablename__ = "notification_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    subscription_id = Column(
        Integer,
        ForeignKey("notification_subscriptions.id"),
        nullable=False,
        index=True,
    )
    run_id = Column(String(32), nullable=True, index=True)  # nullable for /test sends
    status = Column(String(10), nullable=False)  # 'ok' | 'error'
    http_code = Column(Integer, nullable=True)
    error_text = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)


class ResearchReport(Base):
    """One per-ticker research run from src.research.pipeline.run_research.

    Lives alongside (not inside) PipelineRun — the research pipeline is a
    parallel A/B subsystem with its own state shape and its own daily cron.
    Cross-referencing is intentionally absent: each subsystem persists what
    its own pipeline produced.
    """

    __tablename__ = "research_reports"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    ticker = Column(String(20), nullable=False, index=True)
    scan_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD

    # Serialized ResearchRequest dataclass (asdict)
    request_json = Column(JSON, nullable=False)

    # synthesizer output
    report_markdown = Column(Text, nullable=False)

    # final HTML payload (already rendered; served by GET /reports/{id}/html)
    rendered_html = Column(Text, nullable=False)

    # Phase 2 metadata: True when the run used the persona router. JSON
    # field stores the router's assignments dict (or null when objective).
    use_personas = Column(Boolean, nullable=False, default=False)
    persona_assignments_json = Column(JSON, nullable=True)

    # wall-clock seconds for the full run_research call
    duration_seconds = Column(Float, nullable=True)

    # Phase 4 — full SOP structured payload + AnalyzeRequest serialization
    analyze_request_json = Column(JSON, nullable=True)
    sections_json = Column(JSON, nullable=True)

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (Index("ix_research_reports_ticker_scan_date", "ticker", "scan_date"),)


class UserWatchlist(Base):
    """User-curated watchlist of tickers, shown in the left sidebar.

    Separate from ``WatchlistEntry`` (which is scanner output): this table
    holds named, hand-picked ticker lists the user maintains via the UI.
    """

    __tablename__ = "user_watchlists"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    name = Column(String(200), nullable=False, index=True)
    # list[str] of uppercased tickers; defaults to empty list
    tickers = Column(JSON, nullable=False, default=list)

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_watchlist_user_name"),)


class AnalyzeFlow(Base):
    """Saved AnalyzeFlow template — a named canvas layout the UI loads back.

    Phase 5D persists the React Flow canvas state for the Analyze panel.
    The canvas itself is visual scaffolding; what we persist is the
    *effective* configuration the orchestrator needs:

      * ``included_sections`` — list[str] of SECTION_ORDER names enabled
      * ``persona_overrides`` — dict[section_name -> persona_name] for
        sections the user explicitly pinned a persona on. Absent or None
        means defer to the router (when use_personas) or run objective.
      * ``use_personas`` — convenience toggle stored alongside; overrides
        still take precedence when set even if this is False.

    Intentionally NOT FK'd to ResearchReport: templates are reusable
    across runs and across tickers.
    """

    __tablename__ = "analyze_flows"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    name = Column(String(200), nullable=False, index=True)
    included_sections = Column(JSON, nullable=False, default=list)  # list[str]
    persona_overrides = Column(JSON, nullable=True)  # dict[section_name, persona_name]
    use_personas = Column(Boolean, nullable=False, default=False)

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_analyze_flow_user_name"),)


class ResearchTradePlan(Base):
    """One TradePlan + inlined BacktestSummary, 1-to-1 with ResearchReport.

    Inlined rather than two separate tables because the backtest result
    is always paired with the plan it replayed; no query patterns benefit
    from splitting. ON DELETE CASCADE so deleting a report cleans up the
    plan automatically.
    """

    __tablename__ = "research_trade_plans"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(
        Integer,
        ForeignKey("research_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ---- TradePlan fields ----
    # 'long' | 'short' | 'stand_aside'
    direction = Column(String(20), nullable=False)
    entry_price = Column(Float, nullable=True)  # null when stand_aside
    target_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    horizon_days = Column(Integer, nullable=False, default=0)
    sizing_pct = Column(Float, nullable=False, default=0.0)
    confidence = Column(Integer, nullable=False, default=0)  # 0-100
    rationale = Column(Text, nullable=False, default="")

    # ---- BacktestSummary fields (inlined) ----
    backtest_matches_found = Column(Integer, nullable=False, default=0)
    backtest_win_rate = Column(Float, nullable=True)
    backtest_avg_pnl_pct = Column(Float, nullable=True)
    backtest_max_drawdown_pct = Column(Float, nullable=True)
    backtest_avg_holding_days = Column(Float, nullable=True)
    # 'strong' | 'moderate' | 'weak' | 'insufficient'
    backtest_sample_quality = Column(String(20), nullable=False, default="insufficient")
    backtest_caveat = Column(Text, nullable=True)


class Strategy(Base):
    """Phase 6: a saved StrategySpec. Spec lives in spec_json; version bumps
    every time user accepts an AI patch or manually edits."""

    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    spec_json = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_strategy_user_name"),)


class LabChatMessage(Base):
    """Phase 6: one chat turn under a Strategy. AI proposals include a
    spec_patch_json + the resulting spec_snapshot_json if accepted."""

    __tablename__ = "lab_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(
        Integer,
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    role = Column(String(20), nullable=False)  # 'user' | 'assistant' | 'user_manual_edit'
    content = Column(Text, nullable=False)
    spec_snapshot_json = Column(JSON, nullable=True)  # spec AFTER accept
    spec_patch_json = Column(JSON, nullable=True)  # raw AI patch
    patch_accepted = Column(Boolean, nullable=True)  # null if N/A

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)


class Backtest(Base):
    """Phase 6: one backtest run on a Strategy's spec snapshot."""

    __tablename__ = "backtests"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(
        Integer,
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    spec_snapshot_json = Column(JSON, nullable=False)
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    midpoint_date = Column(String(10), nullable=False)
    universe_size = Column(Integer, nullable=False)

    # IS metrics
    is_total_return = Column(Float, nullable=True)
    is_cagr = Column(Float, nullable=True)
    is_sharpe = Column(Float, nullable=True)
    is_sortino = Column(Float, nullable=True)
    is_max_drawdown = Column(Float, nullable=True)
    is_calmar = Column(Float, nullable=True)
    is_win_rate = Column(Float, nullable=True)
    is_profit_factor = Column(Float, nullable=True)
    is_n_trades = Column(Integer, nullable=True)
    is_avg_holding_days = Column(Float, nullable=True)

    # OOS metrics
    oos_total_return = Column(Float, nullable=True)
    oos_cagr = Column(Float, nullable=True)
    oos_sharpe = Column(Float, nullable=True)
    oos_sortino = Column(Float, nullable=True)
    oos_max_drawdown = Column(Float, nullable=True)
    oos_calmar = Column(Float, nullable=True)
    oos_win_rate = Column(Float, nullable=True)
    oos_profit_factor = Column(Float, nullable=True)
    oos_n_trades = Column(Integer, nullable=True)
    oos_avg_holding_days = Column(Float, nullable=True)

    degradation_ratio = Column(Float, nullable=True)
    benchmark_cagr = Column(Float, nullable=True)
    verdict_label = Column(String(30), nullable=False)
    verdict_text = Column(Text, nullable=False)

    trades_json = Column(JSON, nullable=False)
    equity_curve_is = Column(JSON, nullable=False)
    equity_curve_oos = Column(JSON, nullable=False)
    benchmark_curve = Column(JSON, nullable=True)

    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)

    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)


class TickerSnapshot(Base):
    """Per-ticker per-day snapshot of all filterable Screener metrics.

    Built nightly by SnapshotBuilder; queried by ScreenerRepository.
    PK on (ticker, snapshot_date) makes daily upserts idempotent.
    """

    __tablename__ = "ticker_snapshots"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False)
    market = Column(String(8), nullable=False)
    snapshot_date = Column(Date, nullable=False)

    # Price / volume
    price = Column(Numeric(12, 4))
    prev_close = Column(Numeric(12, 4))
    change_pct = Column(Numeric(8, 4))
    volume = Column(BigInteger)
    avg_volume_10d = Column(BigInteger)
    rel_volume = Column(Numeric(6, 3))

    # Market cap
    market_cap = Column(Numeric(20, 2))

    # Valuation
    pe_ttm = Column(Numeric(10, 3))
    pe_forward = Column(Numeric(10, 3))
    pb = Column(Numeric(10, 3))
    ps = Column(Numeric(10, 3))
    peg = Column(Numeric(10, 3))

    # Growth
    eps_growth_yoy = Column(Numeric(10, 4))
    revenue_growth_yoy = Column(Numeric(10, 4))

    # Profitability
    roe = Column(Numeric(10, 4))
    profit_margin = Column(Numeric(10, 4))

    # Dividend
    dividend_yield_pct = Column(Numeric(8, 4))

    # Risk
    beta = Column(Numeric(8, 3))

    # Classification
    sector = Column(String(64))
    industry = Column(String(128))
    exchange = Column(String(16))

    # Analyst
    analyst_rating = Column(String(16))
    analyst_count = Column(Integer)
    target_mean_price = Column(Numeric(12, 4))

    # Earnings dates
    recent_earnings_date = Column(Date)
    upcoming_earnings_date = Column(Date)

    # Performance windows
    perf_1d = Column(Numeric(8, 4))
    perf_5d = Column(Numeric(8, 4))
    perf_1m = Column(Numeric(8, 4))
    perf_3m = Column(Numeric(8, 4))
    perf_ytd = Column(Numeric(8, 4))
    perf_1y = Column(Numeric(8, 4))

    # Meta
    data_source = Column(String(16))
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", name="uq_snapshot_ticker_date"),
        Index("idx_snapshot_date", "snapshot_date"),
        Index("idx_snapshot_market_date", "market", "snapshot_date"),
        Index("idx_snapshot_sector", "sector", "snapshot_date"),
    )


class ScreenerPreset(Base):
    """A saved Screener filter set, optionally run on a daily cron."""

    __tablename__ = "screener_presets"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    market = Column(String(8))  # 'US' | 'CN' | None(all)
    filters_json = Column(JSON, nullable=False, default=dict)
    sort_by = Column(String(32), nullable=False, default="market_cap")
    sort_dir = Column(String(4), nullable=False, default="desc")
    schedule_enabled = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    # Per-preset cron cadence, evaluated in the owner's timezone. server_default
    # = 22:05 daily so rows predating this column keep the old global preset-cron
    # time; users can now set a per-preset frequency/time.
    cron_expr = Column(String(100), nullable=False, server_default="5 22 * * *")
    notify_channels = Column(JSON)  # ["email","webhook"]
    last_run_at = Column(DateTime(timezone=True))
    last_match_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)


class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)  # null = OAuth-only account
    full_name = Column(String(120))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    is_superuser = Column(Boolean, nullable=False, server_default=text("false"))
    # Password signups land False and must verify via emailed token; OAuth
    # logins arrive verified from the provider. Gated by REQUIRE_EMAIL_VERIFICATION.
    is_verified = Column(Boolean, nullable=False, server_default=text("false"))
    # IANA timezone name used to interpret this user's scheduled-report crons
    # (read by the scheduler in a separate task). Existing rows backfill to ET.
    timezone = Column(String(64), nullable=False, server_default="America/New_York")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(BigInteger().with_variant(Integer(), "sqlite"), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(16), nullable=False)  # 'google' | 'github'
    provider_account_id = Column(String(128), nullable=False)
    email = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),)
