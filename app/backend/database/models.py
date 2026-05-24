from sqlalchemy import Column, Integer, Float, String, DateTime, Text, Boolean, JSON, ForeignKey, Index, UniqueConstraint
from sqlalchemy.sql import func
from .connection import Base


class HedgeFundFlow(Base):
    """Table to store React Flow configurations (nodes, edges, viewport)"""
    __tablename__ = "hedge_fund_flows"
    
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Flow metadata
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    
    # React Flow state
    nodes = Column(JSON, nullable=False)  # Store React Flow nodes as JSON
    edges = Column(JSON, nullable=False)  # Store React Flow edges as JSON
    viewport = Column(JSON, nullable=True)  # Store viewport state (zoom, x, y)
    data = Column(JSON, nullable=True)  # Store node internal states (tickers, models, etc.)
    
    # Additional metadata
    is_template = Column(Boolean, default=False)  # Mark as template for reuse
    tags = Column(JSON, nullable=True)  # Store tags for categorization


class HedgeFundFlowRun(Base):
    """Table to track individual execution runs of a hedge fund flow"""
    __tablename__ = "hedge_fund_flow_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    flow_id = Column(Integer, ForeignKey("hedge_fund_flows.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Run execution tracking
    status = Column(String(50), nullable=False, default="IDLE")  # IDLE, IN_PROGRESS, COMPLETE, ERROR
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Run configuration
    trading_mode = Column(String(50), nullable=False, default="one-time")  # one-time, continuous, advisory
    schedule = Column(String(50), nullable=True)  # hourly, daily, weekly (for continuous mode)
    duration = Column(String(50), nullable=True)  # 1day, 1week, 1month (for continuous mode)
    
    # Run data
    request_data = Column(JSON, nullable=True)  # Store the request parameters (tickers, agents, models, etc.)
    initial_portfolio = Column(JSON, nullable=True)  # Store initial portfolio state
    final_portfolio = Column(JSON, nullable=True)  # Store final portfolio state
    results = Column(JSON, nullable=True)  # Store the output/results from the run
    error_message = Column(Text, nullable=True)  # Store error details if run failed
    
    # Metadata
    run_number = Column(Integer, nullable=False, default=1)  # Sequential run number for this flow


class HedgeFundFlowRunCycle(Base):
    """Individual analysis cycles within a trading session"""
    __tablename__ = "hedge_fund_flow_run_cycles"
    
    id = Column(Integer, primary_key=True, index=True)
    flow_run_id = Column(Integer, ForeignKey("hedge_fund_flow_runs.id"), nullable=False, index=True)
    cycle_number = Column(Integer, nullable=False)  # 1, 2, 3, etc. within the run
    
    # Timing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Analysis results
    analyst_signals = Column(JSON, nullable=True)  # All agent decisions/signals
    trading_decisions = Column(JSON, nullable=True)  # Portfolio manager decisions
    executed_trades = Column(JSON, nullable=True)  # Actual trades executed (paper trading)
    
    # Portfolio state after this cycle
    portfolio_snapshot = Column(JSON, nullable=True)  # Cash, positions, performance metrics
    
    # Performance metrics for this cycle
    performance_metrics = Column(JSON, nullable=True)  # Returns, sharpe ratio, etc.
    
    # Execution tracking
    status = Column(String(50), nullable=False, default="IN_PROGRESS")  # IN_PROGRESS, COMPLETED, ERROR
    error_message = Column(Text, nullable=True)  # Store error details if cycle failed
    
    # Cost tracking
    llm_calls_count = Column(Integer, nullable=True, default=0)  # Number of LLM calls made
    api_calls_count = Column(Integer, nullable=True, default=0)  # Number of financial API calls made
    estimated_cost = Column(String(20), nullable=True)  # Estimated cost in USD
    
    # Metadata
    trigger_reason = Column(String(100), nullable=True)  # scheduled, manual, market_event, etc.
    market_conditions = Column(JSON, nullable=True)  # Market data snapshot at cycle start


class ApiKey(Base):
    """Table to store API keys for various services"""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # API key details
    provider = Column(String(100), nullable=False, unique=True, index=True)  # e.g., "ANTHROPIC_API_KEY"
    key_value = Column(Text, nullable=False)  # The actual API key (encrypted in production)
    is_active = Column(Boolean, default=True)  # Enable/disable without deletion

    # Optional metadata
    description = Column(Text, nullable=True)  # Human-readable description
    last_used = Column(DateTime(timezone=True), nullable=True)  # Track usage


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

    __table_args__ = (
        UniqueConstraint("ticker", "asof_date", name="uq_target_snapshot_ticker_date"),
    )


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
    watchlist_json = Column(JSON, nullable=True)             # list[ScoredEntry.model_dump()]
    agent_decisions_json = Column(JSON, nullable=True)       # portfolio_manager output
    analyst_signals_json = Column(JSON, nullable=True)       # per-agent per-ticker signals
    duration_seconds = Column(Float, nullable=True)


class PipelineSchedule(Base):
    """Single-row config for the daily pipeline cron job.

    Repository upserts the row with id=1 (a hard-coded singleton). UI
    edits go through ``GET /pipeline/schedule`` / ``PATCH``; the daily
    scheduler job reads this row on every fire. Keeping it as a table
    rather than a config file means we can hot-edit via the UI without
    redeploying.
    """
    __tablename__ = "pipeline_schedule"

    id = Column(Integer, primary_key=True, default=1)
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
        Integer, ForeignKey("notification_subscriptions.id"),
        nullable=False, index=True,
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

    __table_args__ = (
        Index("ix_research_reports_ticker_scan_date", "ticker", "scan_date"),
    )


class UserWatchlist(Base):
    """User-curated watchlist of tickers, shown in the left sidebar.

    Separate from ``WatchlistEntry`` (which is scanner output): this table
    holds named, hand-picked ticker lists the user maintains via the UI.
    """
    __tablename__ = "user_watchlists"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    name = Column(String(200), nullable=False, unique=True, index=True)
    # list[str] of uppercased tickers; defaults to empty list
    tickers = Column(JSON, nullable=False, default=list)


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

    name = Column(String(200), nullable=False, unique=True, index=True)
    included_sections = Column(JSON, nullable=False, default=list)  # list[str]
    persona_overrides = Column(JSON, nullable=True)  # dict[section_name, persona_name]
    use_personas = Column(Boolean, nullable=False, default=False)


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
        nullable=False, index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ---- TradePlan fields ----
    # 'long' | 'short' | 'stand_aside'
    direction = Column(String(20), nullable=False)
    entry_price = Column(Float, nullable=True)   # null when stand_aside
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
