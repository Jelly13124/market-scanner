# AI Strategy Lab — Design Spec

> **Phase 6** of the ai-hedge-fund project. Brainstormed 2026-05-25; this doc is the input to the writing-plans phase.

## Context

After Phase 5 shipped (charts + watchlist + flow-style Analyze + auto-SOP cron), the next user-facing feature is an **AI-driven quantitative strategy lab**: user describes a strategy in natural language, AI assists by emitting structured spec, system runs walk-forward backtest on a multi-ticker portfolio, returns honest in-sample / out-of-sample verdict.

Two design directions were considered. The other (A-share data integration + auth + db management) was deferred — it's 4 separate sub-projects that are productionization work, premature while core features are still iterating.

The strategy lab is a natural extension of the current research pipeline (which is per-ticker analysis): the user has been asking "what's the right buy/sell call on this ticker"; now they can ask "what strategy works across my watchlist over 5 years?"

## Goals

- **Primary**: let the user describe a strategy idea in chat, have AI translate it into a structured spec, backtest it on a portfolio of US stocks with walk-forward IS/OOS validation, return an honest verdict (no false positives from overfitting).
- **Reuse**: leverage existing `call_research_llm` infrastructure, `src/research/charts/` for visualization, `v2/data/` for OHLCV, watchlist subsystem, Phase 5 React Flow conventions in the UI.
- **Honest results**: in-sample / out-of-sample split is mandatory; overfit strategies get a clear "REJECT" label, not a glowing CAGR number.

## Non-goals (explicit out of scope)

| Excluded | Reason |
|---|---|
| Long/short positions | Long-only matches 95% of retail use; short adds shorting cost, locate, regulation complexity |
| Intraday bars (1m/5m) | Daily-bar backtest is informative + cheap; intraday is a separate engineering bet |
| Walk-forward optimization (rolling re-train) | Static 70/30 split is the industry baseline; rolling adds 5-10× run time |
| Live trading / broker API | This is a backtest tool, not an order management system |
| Custom Python blocks | 18-block catalog is the contract; users can request new blocks, but no arbitrary code |
| Multi-user permissions | Single-user app |
| Strategy sharing / export | Single user, no audience |
| A-share data | US-only v1; A-shares is a separate project tracked elsewhere |
| Background backtest queue | Sync run with spinner is acceptable for ≤5 min runs |
| Portfolio comparison | User runs each backtest separately and reads results |
| Strategy template library | All strategies originate from chat, no preset templates |

## Architecture

Three layers, each owns one job:

```
┌────────────────────────────────────────────────────────────┐
│ Layer 1: LLM → Strategy Spec                                │
│   User chats in natural language                            │
│   LLM sees catalog (18 blocks) as system prompt             │
│   LLM emits Pydantic-validated StrategySpec patch           │
│   Spec stored in DB (Strategy table) + visible in UI        │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ Layer 2: Spec → Backtest Engine                             │
│   Load universe (watchlist or index) → OHLCV → indicators   │
│   Split IS / OOS by time (70/30 default)                    │
│   Per-bar simulation: entries, exits, position management   │
│   Compute metrics (IS + OOS) + verdict via degradation     │
│   Persist BacktestResult                                    │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ Layer 3: UI — New "Lab" tab                                 │
│   Strategy list (left) ↔ Chat (middle) ↔ Spec viewer (right)│
│   Backtest result panel below (charts + metrics + trades)   │
└────────────────────────────────────────────────────────────┘
```

### Reuse from existing infrastructure

| Use | Location |
|---|---|
| LLM call + structured output | `src/research/llm.py:call_research_llm` |
| Chart rendering (matplotlib Agg + PNG endpoint pattern) | `src/research/charts/render.py` + `app/backend/routes/research.py` chart route |
| OHLCV data | `v2/data/client.py` composite client |
| Universe loading (watchlist + indices) | `v2/scanner/universes/loader.py` (extended in Phase 5C) |
| Watchlist subsystem | Phase 5B `UserWatchlist` + repo |
| Repository / Pydantic / Alembic patterns | Phase 1-5 conventions |
| Tab system + display:none preservation | Phase 5 polish v2 `tab-content.tsx` |
| React Flow patterns (if needed) | XyFlow v12, already wired in Phase 5D Analyze |

### New surface (Phase 6 scope)

- `src/lab/` — block catalog, spec models, backtest engine, LLM chat wrapper
- `app/backend/routes/lab.py` — REST API (12 endpoints, see API section)
- `app/backend/repositories/lab_*.py` — Strategy / ChatMessage / Backtest repos
- `app/backend/models/lab_schemas.py` — Pydantic request/response shapes
- `app/frontend/src/components/panels/lab/` — Lab tab UI (~10 components, see Frontend section)
- 3 new DB tables: `strategies`, `lab_chat_messages`, `backtests`
- 1 new npm dependency: `@monaco-editor/react` for manual spec editing (optional — could fall back to plain `<textarea>` + JSON.parse client-side validation if dep is rejected)

## Strategy Spec format

Top-level `StrategySpec` (Pydantic v2):

```python
class StrategySpec(BaseModel):
    name: str
    description: str  # 1-2 sentence summary
    universe: UniverseSpec
    entry: EntryGroup
    exit: list[ExitSpec]
    filters: list[FilterSpec]
    sizing: SizingSpec
    backtest_config: BacktestConfig

class UniverseSpec(BaseModel):
    kind: Literal["watchlist", "sp500", "nasdaq100"]
    watchlist_id: int | None = None  # required if kind == "watchlist"
    # csi300 omitted from v1 enum — A-share data is a separate project,
    # add the literal value when akshare data client lands.

class EntryGroup(BaseModel):
    combiner: Literal["and", "or"] = "and"
    signals: list[EntrySpec]  # 1-3 blocks

class BacktestConfig(BaseModel):
    start_date: str | None = None        # default: today - 5y
    end_date: str | None = None          # default: today
    is_oos_split: float = 0.7
    starting_capital_usd: float = 100_000
    commission_bps: float = 5
    slippage_bps: float = 5
    max_concurrent_positions: int = 10
    benchmark: Literal["spy", "none"] = "spy"  # csi300 added when A-share lands
    reverse_signal_as_exit: bool = True
    full_position_policy: Literal["skip", "replace_weakest"] = "skip"
```

`EntrySpec` / `ExitSpec` / `FilterSpec` / `SizingSpec` are discriminated unions over the block types below. LLM uses `with_structured_output(StrategySpec, method="json_mode")` to emit validated JSON in one shot.

## Block catalog (18 v1 blocks)

### Entry signals (8)

| Block | Parameters | Description |
|---|---|---|
| `rsi` | period (2-100), level (0-100), direction (oversold_buy / overbought_short) | RSI threshold trigger |
| `rsi_cross` | period, level, direction (up / down) | RSI crosses level |
| `ma_cross` | fast, slow, ma_type (sma / ema), direction (golden / death) | Two MA cross |
| `price_vs_ma` | ma_period, ma_type, direction (above / below) | Price-vs-MA filter |
| `macd` | fast, slow, signal, trigger (bullish_cross / bearish_cross / histogram_flip_up / histogram_flip_down) | MACD events |
| `bollinger_break` | period, num_std, direction (break_up / break_down) | Close outside band |
| `donchian_break` | period (2-252), direction | N-day high/low break |
| `volume_spike` | avg_period, multiplier (1-10) | Volume > X × avg |

### Exit signals (4)

| Block | Parameters | Description |
|---|---|---|
| `stop_loss` | mode (pct / atr), value | Fixed % or ATR-multiple stop |
| `take_profit` | pct | Fixed % from entry |
| `trailing_stop` | mode (pct / atr), value | Trailing stop |
| `time_stop` | bars (1-500) | Exit after N bars |

### Position sizing (3 — choose 1)

| Block | Parameters | Description |
|---|---|---|
| `fixed_pct` | pct (0.5-100%) | N% of equity per position |
| `equal_weight` | — | Split available cash across all open positions |
| `vol_targeted` | target_dollar_vol_per_position, atr_period | Size inversely to ATR |

### Filters (3 — gate entry)

| Block | Parameters | Description |
|---|---|---|
| `trend` | ma_period, ma_type, direction (rising / falling) | MA slope filter |
| `volatility` | atr_period, percentile_min, percentile_max | ATR in percentile range |
| `liquidity` | min_daily_dollar_volume, lookback_days | Minimum $ volume |

### Combiner semantics

- `entry.combiner = "and"`: every signal must be True simultaneously to fire
- `entry.combiner = "or"`: any one signal firing is enough
- `exit`: ANY exit signal True → close position
- `filters`: ALL filters must pass for entry to be considered
- `reverse_signal_as_exit = true`: if `entry` would NOT fire today and position is open, close it (default on)

## Backtest engine

### Data flow

```
StrategySpec
  ↓
UniverseLoader → list[ticker]
  ↓
DataLoader → DataFrame[ticker × date] of OHLCV (5y default, batch fetch)
  ↓
SignalPrecompute → DataFrame[ticker × date × indicator] for RSI/MA/ATR/MACD/Bollinger/Donchian/volume_avg
  ↓
Splitter → IS (start..midpoint), OOS (midpoint..end), midpoint = start + (end-start) × is_oos_split
  ↓
For IS, then OOS:
  SimulationLoop(spec, bars, indicators) → SimulationOutput(trades, equity_curve, final_cash)
  MetricsCompute(simulation_output) → Metrics
  ↓
VerdictEngine(is_metrics, oos_metrics, benchmark_cagr) → Verdict
  ↓
BacktestResult (persisted)
```

### Per-bar simulation loop (pseudocode)

```python
def simulate(spec, bars, indicators) -> SimulationOutput:
    cash = spec.backtest_config.starting_capital_usd
    positions: dict[ticker, Position] = {}
    trades, equity_curve = [], []

    for date in bars.dates:
        # 1. EXITS first (on next bar's open)
        for ticker, pos in list(positions.items()):
            reason = check_exit_signals(spec.exit, pos, date, indicators)
            if reason is None and spec.reverse_signal_as_exit:
                if not entry_signals_still_fire(spec.entry, ticker, date, indicators):
                    reason = "reverse_signal"
            if reason:
                close_price = bars[ticker, date].open
                cost = (close_price * pos.shares) * (commission_bps + slippage_bps) / 10000
                cash += close_price * pos.shares - cost
                trades.append(Trade(ticker, pos.entry_date, date, pos.entry_price,
                                     close_price, pos.shares, pnl_after_costs, reason))
                del positions[ticker]

        # 2. ENTRIES if capacity
        if len(positions) < max_concurrent_positions:
            candidates = []
            for ticker in bars.tickers:
                if ticker in positions:
                    continue
                if not all_filters_pass(spec.filters, ticker, date, indicators):
                    continue
                if entry_signals_fire(spec.entry, ticker, date, indicators):
                    candidates.append(ticker)
            for ticker in candidates:
                if len(positions) >= max_concurrent_positions:
                    if spec.full_position_policy == "replace_weakest":
                        evict_weakest(positions, date, bars)
                    else:
                        break  # skip
                value = compute_sizing(spec.sizing, cash, positions, ticker)
                price = bars[ticker, date].open
                shares = int(value / price)
                cost = (price * shares) * (commission_bps + slippage_bps) / 10000
                if shares == 0 or cash < price * shares + cost:
                    continue
                cash -= price * shares + cost
                positions[ticker] = Position(ticker, date, price, shares)

        # 3. Mark-to-market equity
        equity_curve.append(cash + sum(p.shares * bars[t, date].close for t, p in positions.items()))

    return SimulationOutput(trades, equity_curve, cash, positions)
```

### Metrics (computed per IS and OOS)

| Metric | Formula |
|---|---|
| `total_return` | final_equity / start - 1 |
| `cagr` | (final/start) ^ (252/n_bars) - 1 |
| `sharpe` | mean(daily_returns) / std(daily_returns) × sqrt(252) |
| `sortino` | mean(daily_returns) / downside_std × sqrt(252) |
| `max_drawdown` | min((equity - rolling_peak) / rolling_peak) |
| `calmar` | cagr / abs(max_drawdown) |
| `win_rate` | winning_trades / total_trades |
| `profit_factor` | sum(wins) / abs(sum(losses)) |
| `avg_holding_days` | mean(trade.exit_date - trade.entry_date) |
| `n_trades` | total trades closed |
| `exposure_pct` | mean fraction of capital deployed |

Pure numpy / pandas computation; no backtrader or vectorbt dependency. Estimated ~150 lines.

### Verdict rules

```
if n_trades < 5 in either IS or OOS:
    verdict = "insufficient" (loosen entries or extend window)
elif oos_cagr < 0:
    verdict = "reject" (loses money OOS — overfit or regime-dependent)
elif degradation_ratio (oos_cagr / is_cagr) < 0.4:
    verdict = "overfit" (heavy degradation)
elif degradation_ratio < 0.6:
    verdict = "weak" (positive but suggest re-test on other markets)
elif oos_cagr < benchmark_cagr:
    verdict = "underperform_bench" (passive SPY beats this)
else:
    verdict = "positive_edge" (genuine edge after costs, beats SPY)
```

These rules are adapted from the `stock-analyze-skills` repo's `backtest.md` hard rules — the same overfit-protection heuristics the user's existing skill uses.

### Charts produced

Three PNGs, generated on-demand via `GET /lab/backtests/{id}/chart/{type}.png`:

1. `equity_curve` — IS portion + OOS portion (different colors) + benchmark line + drawdown shading
2. `drawdown` — % below rolling peak over time
3. `monthly_heatmap` — calendar grid of monthly returns

Uses matplotlib Agg backend (Phase 5A pattern).

## Chat UX

### System prompt composition (~2k tokens)

Three parts assembled per turn:

1. **CATALOG** — 18 blocks with JSON schema + 1-line description each (~600 tokens)
2. **PRIOR CONTEXT** — user's prior strategies (last 5) with their most recent backtest summary (CAGR, Sharpe, verdict label) (~300 tokens)
3. **TASK** — explicit instructions: emit either `ProposeSpecPatch` or `ChatReply`; rationale required for patches; respect catalog only; no inventing blocks

### Chat response model

```python
class ProposeSpecPatch(BaseModel):
    """LLM proposes a patch to current spec. Frontend renders a diff."""
    rationale: str  # 1-2 sentences explaining WHY
    patch: dict     # full StrategySpec dict (v1: replace entire spec; jsonpatch may come later)

class ChatReply(BaseModel):
    """Plain text answer; no spec change."""
    message: str

ChatResponse = Annotated[Union[ProposeSpecPatch, ChatReply], Field(discriminator="kind")]
```

### Chat turn flow

```
1. User sends message via Lab UI
2. POST /lab/strategies/{id}/chat
3. Backend:
   - Load strategy + last 20 chat_messages + recent backtest summary
   - Build system prompt (catalog + prior + task)
   - call_research_llm(prompt, ChatResponse) → either ProposeSpecPatch or ChatReply
   - Save user msg + AI msg to lab_chat_messages
   - If patch: store spec_snapshot_json (the resulting spec if accepted) + spec_patch_json
   - Return {message, kind: 'reply'|'patch', diff_against_current_spec (if patch)}
4. Frontend:
   - Render new AI message in chat history
   - If patch: render inline diff with "Apply" / "Reject" buttons
   - Apply: POST /lab/strategies/{id}/chat/apply {message_id} → spec updated + version++
   - Reject: just mark message.patch_accepted = false (no spec write)
```

### Manual spec edit (bypass AI)

Spec viewer has an "Edit JSON" button → Monaco editor modal → user edits → client-side Pydantic-like validation (zod schema mirrors backend) → PATCH /lab/strategies/{id}. Also creates a `lab_chat_messages` row with `role="user_manual_edit"` and `spec_snapshot_json` so the audit trail stays complete.

### Long-term memory (v1 scope)

Two layers shipped:

- **Per-strategy chat history**: every message + spec snapshot stored, last 20 messages passed to LLM each turn
- **Cross-strategy context**: system prompt includes summary of user's last 5 strategies + their most recent backtest verdict; AI can reference ("your earlier MA Cross v1 OOS-degraded; try adding a trend filter")

Layer 3 (auto-extracted user preferences / insights from chat patterns) is **v2 scope** — requires a nightly summarization job.

## Database schema

### `strategies`

```python
class Strategy(Base):
    __tablename__ = "strategies"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    name = Column(String(200), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    spec_json = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
```

### `lab_chat_messages`

```python
class LabChatMessage(Base):
    __tablename__ = "lab_chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    role = Column(String(20), nullable=False)  # 'user' | 'assistant' | 'user_manual_edit'
    content = Column(Text, nullable=False)
    spec_snapshot_json = Column(JSON, nullable=True)
    spec_patch_json = Column(JSON, nullable=True)
    patch_accepted = Column(Boolean, nullable=True)
```

### `backtests`

```python
class Backtest(Base):
    __tablename__ = "backtests"
    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Snapshot of spec at run-time (immutable)
    spec_snapshot_json = Column(JSON, nullable=False)
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    midpoint_date = Column(String(10), nullable=False)
    universe_size = Column(Integer, nullable=False)

    # IS metrics
    is_total_return = Column(Float); is_cagr = Column(Float)
    is_sharpe = Column(Float); is_sortino = Column(Float)
    is_max_drawdown = Column(Float); is_calmar = Column(Float)
    is_win_rate = Column(Float); is_profit_factor = Column(Float)
    is_n_trades = Column(Integer); is_avg_holding_days = Column(Float)

    # OOS metrics (same fields, oos_ prefix)
    oos_total_return = Column(Float); oos_cagr = Column(Float)
    oos_sharpe = Column(Float); oos_sortino = Column(Float)
    oos_max_drawdown = Column(Float); oos_calmar = Column(Float)
    oos_win_rate = Column(Float); oos_profit_factor = Column(Float)
    oos_n_trades = Column(Integer); oos_avg_holding_days = Column(Float)

    degradation_ratio = Column(Float)
    benchmark_cagr = Column(Float, nullable=True)
    verdict_label = Column(String(30), nullable=False)
    verdict_text = Column(Text, nullable=False)

    trades_json = Column(JSON, nullable=False)
    equity_curve_is = Column(JSON, nullable=False)
    equity_curve_oos = Column(JSON, nullable=False)
    benchmark_curve = Column(JSON, nullable=True)

    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
```

### Alembic migration

New migration `c3e7f9d2b8a4_add_lab_tables.py`. Down-revision: `a1b2c3d4e5f6` (Phase 5E + flow drop). Additive; safe.

## REST API

```
# Strategy CRUD
GET    /lab/strategies
POST   /lab/strategies                      body: {name}
GET    /lab/strategies/{id}
PATCH  /lab/strategies/{id}                 body: partial spec (manual edit)
DELETE /lab/strategies/{id}

# Chat
GET    /lab/strategies/{id}/chat?limit=50
POST   /lab/strategies/{id}/chat            body: {message}
POST   /lab/strategies/{id}/chat/apply      body: {message_id}

# Backtest
POST   /lab/strategies/{id}/backtest        body: {} (uses current spec)
GET    /lab/strategies/{id}/backtests
GET    /lab/backtests/{id}
GET    /lab/backtests/{id}/chart/{type}.png    # type ∈ {equity_curve, drawdown, monthly_heatmap}

# Catalog (for frontend rendering + LLM prompt building)
GET    /lab/catalog
```

12 endpoints. Sync execution for `POST /backtest` (30s-5min). Background queue is v2.

## Frontend layout

New left-sidebar action: `<LabAction />` (FlaskConical icon, opens "Lab" tab). New TabType union member.

Lab tab structure:

```
app/frontend/src/components/panels/lab/
├── lab-panel.tsx              # 3-column layout container
├── strategy-list.tsx          # Left: list of saved strategies + "New" button
├── chat-panel.tsx             # Middle: chat history + input + patch diff
├── chat-message.tsx           # Single bubble (user / ai / manual_edit variants)
├── spec-viewer.tsx            # Right: block-by-block visual
├── spec-block-card.tsx        # One block as a labeled card with params
├── spec-json-editor.tsx       # Monaco modal for manual edit
├── backtest-runner.tsx        # Bottom toolbar: Run button + spinner
├── backtest-result.tsx        # Below canvas: verdict + metrics + charts
├── trade-log-table.tsx        # Collapsible trade list
└── backtest-history.tsx       # All backtest runs for this strategy
```

Layout proportions: 200px / 1fr / 400px for the three top columns; backtest result below as a full-width accordion.

Tab state preservation (Phase 5 polish v2): chat history + current spec persist when user switches to Scanner/Analyze and back.

New npm dep: `@monaco-editor/react` (~150KB) for the JSON editor.

## Testing strategy

### Backend (~70-80 tests target)

```
tests/lab/
├── test_block_validation.py        # 18 blocks × Pydantic validation (~30 tests)
├── test_signal_compute.py          # synthetic OHLCV → expected signal triggers (~15 tests)
├── test_simulation.py              # single + multi ticker, position cap, sizing (~10 tests)
├── test_metrics.py                 # equity curve fixtures → expected Sharpe / DD / CAGR (~6 tests)
├── test_verdict.py                 # IS/OOS combinations → expected verdict label (~6 tests)
├── test_backtest_engine_e2e.py     # full spec → BacktestResult (mock data, no LLM) (~3 tests)
├── test_lab_chat.py                # mock LLM returns patch / reply → routing (~5 tests)
└── test_lab_routes.py              # FastAPI TestClient contract tests (~8 tests)

tests/test_lab_repository.py        # Strategy / ChatMessage / Backtest CRUD (~10 tests)
```

### Frontend

- Manual smoke: create strategy → chat 2-3 turns → Apply patch → Run backtest → view results
- TypeScript: tsc clean
- Vitest: not in current project infra, skip

## Phasing within Phase 6

Sub-phase breakdown for the writing-plans phase:

| Sub-phase | Scope | Estimate | Depends on |
|---|---|---|---|
| 6A | Spec models + block catalog + Pydantic validation | 1d | — |
| 6B | Backtest engine (universe + simulation + sizing) | 2d | 6A |
| 6C | Metrics + verdict | 0.5d | 6B |
| 6D | DB schema + migration + repositories | 0.5d | 6A |
| 6E | REST API + LLM chat wrapper | 1d | 6A, 6D |
| 6F | Frontend Lab tab + chat + spec viewer | 1.5d | 6D, 6E |
| 6G | Backtest result UI + chart endpoints | 0.5d | 6B, 6F |
| 6H | E2E smoke + progress.md | 0.5d | all |

Total: ~7-8 working days. 6A/6D run first (no deps). 6B/6E run in parallel after 6A. 6F/6G run last in parallel after 6E.

## Risks

1. **LLM emits invalid blocks** — mitigated by Pydantic `with_structured_output(method="json_mode")` validation + catalog in system prompt; fallback: AI explains validation error to user.
2. **Backtest run-time on SP500** — 500 tickers × 5y daily = ~625k bars × 8 indicators precomputed = manageable (~30s for indicator pass, ~30s for simulation loop). If too slow, add multi-process for indicator pass.
3. **Overfit verdicts user disagrees with** — verdict logic is deterministic + visible; user can ignore label and inspect numbers. Verdict text explains the reasoning, not just the label.
4. **Chat token cost** — 2k input × 20 turns/day × DeepSeek $0.0001/1k = $0.004/day. Negligible.
5. **`@monaco-editor/react` bundle size** — ~150KB; Vite tree-shakes if not opened. Acceptable.

## Verification (post-implementation smoke)

```
1. Backend + frontend running.
2. Lab tab opens (FlaskConical icon in sidebar).
3. Click "+ New strategy" → name it → empty spec shown on right.
4. Chat: "做一个 MA 趋势跟踪策略，50/200 金叉，5% 止损"
5. AI returns patch with rationale; click Apply.
6. Right pane shows spec: MACross 50/200 + StopLoss 5% + FixedPct 5%.
7. Click "Edit JSON" → modal opens with current spec → close.
8. Backtest config → set universe = "watchlist (id=1)" with 10 tickers.
9. Click Run → spinner for ~30s.
10. Result panel shows: verdict label + 3 chart PNGs + IS/OOS metric grid + trade log.
11. Tab to Scanner, tab back → chat history + spec + result still there.
12. Chat: "把 50 改成 20" → AI proposes patch → Apply → Run again → new backtest row appears in history.
```

## Open questions deferred to plan phase

These are implementation details, not design decisions:

- Pandas vs raw numpy for the indicator/simulation tables (lean numpy for less memory, pandas for readability — likely pandas)
- Monaco editor `language: 'json'` schema injection for autocomplete (nice-to-have)
- Whether to compress `trades_json` for backtests with > 1000 trades (defer until we hit it)
- Whether the catalog endpoint also serves a Pydantic JSON Schema (yes, useful for frontend form generation later)
