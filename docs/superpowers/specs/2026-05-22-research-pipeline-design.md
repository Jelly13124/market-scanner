# Per-Stock Research Pipeline — Design

**Date**: 2026-05-22
**Status**: design approved, awaiting plan
**Author**: brainstorming session with user

## Context

Today the `ai-hedge-fund` repo runs a single daily pipeline (`v2/pipeline/orchestrator.run_pipeline`):

  scanner → top-N watchlist → 11 LLM agents (each emits a signal) → portfolio_manager LLM aggregates into BUY/SHORT/HOLD + qty → emailed/logged

The user has built a parallel toolkit (`Jelly13124/stock-analyze-skills`) that takes the opposite shape: per-ticker deep research reports composed of 10 analytical modules plus 8 investor personas, output as a single self-contained HTML report. No portfolio decisions; the user reads the report and decides.

This design integrates the research-toolkit shape into the production cron, **side-by-side with the existing portfolio pipeline** so the two architectures can be A/B compared in paper-trade mode over time.

## Goals

- Per-stock deep research report (HTML), produced by a new pipeline (`src/research/`).
- Each report carries a concrete **single-shot trade plan** (entry / target / stop / horizon / sizing).
- Each trade plan ships with a **detector-replay backtest** that asks "how did this exact trigger combo perform historically on this ticker?"
- Two meta-agents orchestrate per-ticker quality:
  - **persona-router** (upstream): LLM that decides which investor persona each module uses, or whether to stay objective.
  - **synthesizer** (downstream): LLM that compiles all module outputs into the report and writes the trade plan.
- Driven by either the daily cron (scanner picks top-N) or on-demand (user-supplied ticker via UI/API).
- **Old pipeline preserved unchanged** — both pipelines run on the same scanner output so cumulative paper-trade PnL can be compared.

## Non-goals

- Replacing the existing portfolio pipeline. Old `src/agents/`, `src/main.py:run_hedge_fund`, `portfolio_manager` stay in place.
- Real-money trades. Both pipelines remain in paper-trade / report-only mode.
- Cross-ticker portfolio optimization in the new pipeline. The new pipeline is strictly per-ticker.
- Backtesting the new pipeline's overall alpha during this build. A/B comparison happens later, after both pipelines have produced 30+ days of live output.
- New scanner detectors or scoring logic. Scanner stays unchanged.

## Architecture

### Two pipelines, one scanner

```
v2/scanner/ (unchanged)
    ↓ daily 4:30pm ET → top-N watchlist
    ↓
    ├── Pipeline A (NEW, src/research/): per-stock research
    │   produces: HTML report + TradePlan + BacktestSummary
    │   delivery: email per ticker (Daily cron) OR HTTP response (on-demand)
    │
    └── Pipeline B (LEGACY, src/agents/ + src/main.py:run_hedge_fund)
        produces: BUY/SHORT/HOLD + qty + confidence
        delivery: existing paper-trade log + email
```

Both pipelines read the same scanner watchlist. Each ticker gets one report from Pipeline A and one decision from Pipeline B. The user reads the report; the legacy paper-trade log accumulates for comparison.

### New namespace: `src/research/`

The new pipeline lives in a new top-level package, not as a subdirectory of `src/agents/`. Reason: the LangGraph state shape and the per-ticker isolation make it cleaner to draw a hard boundary rather than mix new modules into the cross-ticker `AgentState`.

```
src/research/
  __init__.py
  router.py                # persona-router LLM agent
  synthesizer.py           # final report + trade plan LLM agent
  pipeline.py              # LangGraph orchestration
  models.py                # ResearchRequest / TradePlan / ModuleResult / BacktestSummary
  shared_data.py           # SharedData fetcher (prices, financials, etc.)
  modules/
    __init__.py
    base.py                # AnalysisModule ABC
    macro.py               # objective only
    sector.py              # objective only
    fundamentals.py        # supports Buffett, Munger, Fisher
    financials.py          # objective only
    valuation.py           # supports Buffett, Graham, Munger, Fisher
    technical.py           # objective only
    sentiment.py           # objective only
    risk_position.py       # supports Druckenmiller, Burry
    debate.py              # multi-persona; calls Agent subagents
    detector_backtest.py   # detector-replay backtest (not an LLM call)
  personas/
    __init__.py
    base.py                # PersonaPrompt ABC
    buffett.py wood.py burry.py munger.py
    graham.py lynch.py fisher.py druckenmiller.py
  templates/
    report.html            # Jinja template — final HTML output
```

## Data model

### `ResearchRequest` (input)

```python
@dataclass
class ResearchRequest:
    ticker: str

    # Position context — shapes the framing
    holding_status: Literal["holding", "watching",
                            "considering_buy", "considering_short"]
    target_position_pct: float        # 0.0–1.0 of portfolio
    risk_tolerance: Literal["conservative", "moderate", "aggressive"]
    report_goal: Literal["new_entry", "hold_review",
                         "exit_decision", "general_research"]

    # Toggles
    use_personas: bool
    scanner_context: dict | None      # detector triggers/components; None when
                                      # invoked on-demand without a scan
```

**Daily-cron defaults** (when scanner triggers a research request):
```python
ResearchRequest(
    ticker=ticker,
    holding_status="watching",
    target_position_pct=0.05,
    risk_tolerance="moderate",
    report_goal="new_entry",
    use_personas=True,
    scanner_context=scanner_entry_dict,
)
```

On-demand callers (UI / API) override any field.

### `ResearchState` (LangGraph state)

```python
class ResearchState(TypedDict):
    request: ResearchRequest

    # Set by persona-router; None when use_personas=False
    persona_assignments: dict[str, str | list[str] | None] | None
    # Shape: {"valuation": "buffett",
    #         "risk_position": None,
    #         "debate": ["wood", "burry"], ...}
    # str value: single persona name; list: debate participants; None: objective

    # Set by each analytical module
    module_results: dict[str, ModuleResult]

    # Set by synthesizer
    report_markdown: str | None
    strategy: TradePlan | None

    # Set by detector_backtest node
    backtest_summary: BacktestSummary | None

    # Set by render_html node
    rendered_html: str | None
```

### `ModuleResult`

```python
@dataclass
class ModuleResult:
    module_name: str
    persona_used: str | None          # None = pure objective
    markdown: str                     # the section content
    key_metrics: dict[str, float] = field(default_factory=dict)
    chart_data: dict | None = None    # opaque payload for HTML renderer
    skipped: bool = False             # True when module determined inapplicable
    skip_reason: str | None = None
```

### `TradePlan`

```python
@dataclass
class TradePlan:
    direction: Literal["long", "short", "stand_aside"]
    entry_price: float | None         # None when stand_aside
    target_price: float | None
    stop_price: float | None
    horizon_days: int
    sizing_pct: float                 # 0.0–1.0 of portfolio
    confidence: int                   # 0–100
    rationale: str                    # 1–2 sentence summary
```

`stand_aside` is mandatory when synthesizer judges the data insufficient, the risk too high, or the plan in conflict with `holding_status`. Other price fields are then `None`.

### `BacktestSummary`

```python
@dataclass
class BacktestSummary:
    matches_found: int
    win_rate: float                   # 0.0–1.0 (None when matches_found < 2)
    avg_pnl_pct: float                # average return per match
    max_drawdown_pct: float
    avg_holding_days: float
    sample_quality: Literal["strong", "moderate", "weak", "insufficient"]
    # strong: ≥10 matches | moderate: 5–9 | weak: 2–4 | insufficient: 0–1
    caveat: str | None                # human-readable caveat for low n
```

## LangGraph node DAG

```
                    [router]  (conditional — skipped if use_personas=False)
                       ↓
       ┌───────┬───────┼───────┬───────┐    (fan-out, parallel)
   [macro] [sector] [fundamentals] [financials] [technical] [sentiment] [debate]
                       ↓ (join)
                  [valuation]                              (sequential)
                       ↓
                [risk_position]                            (needs valuation + technical)
                       ↓
                  [synthesizer]
                       ↓
              [detector_backtest]
                       ↓
                 [render_html]
                       ↓
                      END
```

### Dependencies

- `risk_position` depends on `valuation.fair_value` (for stop math) and `technical.support_resistance` (for stop placement).
- `valuation` is sequential after the first fan-out group because `risk_position` blocks on it.
- `synthesizer` waits for every module.
- `detector_backtest` does not need LLM; it reads the `scanner_context` triggers and replays history.

### Parallelism

The first fan-out group runs in parallel via LangGraph's fan-out (or via `asyncio.gather` if the LangGraph version lacks native fan-out). Per-ticker LLM call budget at default `use_personas=True`:

| Node | LLM calls |
|---|---|
| router | 1 |
| 8 objective + persona-capable modules | 8 |
| debate (when triggered, 2 personas × 2 rounds) | 4 (else 0) |
| synthesizer | 1 |
| detector_backtest, render_html | 0 |
| **Total per ticker** | **10 (no debate) — 14 (with debate)** |

At `use_personas=False`: router skipped, debate never fires, modules run objective only → 9 LLM calls per ticker.

For daily-cron top-N=3: 30–42 LLM calls/day. At deepseek-chat pricing (~$0.0005/call), $0.015–0.021/day, ~$0.50/month additional cost on top of the existing legacy pipeline.

## Persona-router

### Input
- `request.ticker`
- `request.scanner_context` (triggered detectors and their components)
- Ticker profile fetched fresh: GICS sector, market_cap, revenue_growth, P/E, dividend_yield, R&D intensity

### Output
A JSON object keyed by module name, value is either a persona name (str), a list of persona names (debate only), or `null` (objective). Module names that don't support personas are omitted.

Example output:
```json
{
  "fundamentals": "buffett",
  "valuation": "graham",
  "risk_position": "druckenmiller",
  "debate": ["wood", "burry"]
}
```

### LLM call shape
One DeepSeek-chat call. Prompt includes:
- The ticker profile (above)
- The available personas per module (from each module's `supports_personas`)
- An instruction to assign a persona only when the ticker profile genuinely matches the persona's framework. Otherwise omit (which the orchestrator interprets as `None` → objective).
- For `debate`: pick 0 or 2 personas, never 1 or 3+. If 0, debate node is skipped entirely.

### Skipping
When `request.use_personas=False`, the orchestrator skips the router node entirely and runs every module with `persona=None`.

## Synthesizer

### Input
- `request` (full ResearchRequest)
- `module_results` (every module's `ModuleResult`)

### Output
- `report_markdown`: the narrative report, ~800–1500 words
- `strategy`: a `TradePlan`

### Prompt structure
1. System: "You are an institutional research analyst. You read 8–10 module outputs and produce a coherent narrative + a single-shot trade plan."
2. User: the ResearchRequest framing (holding_status, risk_tolerance, report_goal, etc.) + each module's `markdown` content (concatenated, labeled).
3. Output: Pydantic schema with two fields — `report_markdown` and `strategy`.

### `report_goal` shapes the report
- `new_entry` — emphasize entry rationale, valuation gap, catalysts.
- `hold_review` — emphasize thesis-check, catalysts since last review, exit signposts.
- `exit_decision` — emphasize bear-case strength, what would change the mind.
- `general_research` — balanced.

### `risk_tolerance` shapes the plan
- `conservative` — tighter stop (1.5× ATR), more conservative target (1.5× R), smaller sizing.
- `moderate` — 2× ATR stop, 2× R target.
- `aggressive` — 3× ATR stop, 3× R target, larger sizing within `target_position_pct` ceiling.

### `stand_aside` path
The synthesizer is instructed to choose `direction="stand_aside"` when:
- Bear case dominates the modules and `holding_status != "holding"` (i.e., not already trapped)
- `target_position_pct=0` or risk_position module flagged the setup as too risky
- Backtest results aren't part of this judgment — they come after.

## Modules

Every module implements:

```python
class AnalysisModule(ABC):
    name: str
    supports_personas: list[str]      # empty list = objective only

    @abstractmethod
    def run(
        self,
        request: ResearchRequest,
        persona: str | None,
        shared_data: SharedData,
    ) -> ModuleResult: ...
```

Each module is one focused LLM call (or a deterministic computation in the case of `detector_backtest`).

### Per-module brief

| Module | Personas | Notes |
|---|---|---|
| `macro` | none | SPY trend, VIX, yield-curve snapshot. Reuses existing `macro_agent` data layer. |
| `sector` | none | GICS sector ETF performance + relative strength. Reuses existing `sector_agent` lookup. |
| `fundamentals` | Buffett, Munger, Fisher | Moat, TAM, capital allocation, management quality. |
| `financials` | none | Income statement / balance sheet / cash flow tables + ratios. |
| `valuation` | Buffett, Graham, Munger, Fisher | DCF / Owner Earnings / Graham number / scenario expected value. |
| `technical` | none | RSI, MACD, KDJ, Bollinger, SMA, support/resistance. |
| `sentiment` | none | Insider trades + news + analyst revisions + short interest. |
| `risk_position` | Druckenmiller, Burry | Stop / target / sizing math using `target_position_pct` and `risk_tolerance`. |
| `debate` | conditional (router-driven) | Two-persona debate; skipped when router returns `null` or empty list. |
| `detector_backtest` | none | Deterministic — no LLM. Replays detector triggers historically. |

### `SharedData`

To avoid 10 modules each refetching the same prices/financials, a single `SharedData` object is fetched once at pipeline start and passed to every module:

```python
@dataclass
class SharedData:
    prices: list[Price]               # 1y daily
    financials: list[FinancialMetrics] # last 8 quarters
    insider_trades: list[InsiderTrade]
    news: list[NewsArticle]
    analyst_actions: list[AnalystAction]
    analyst_targets: AnalystTargets | None
    earnings_history: list[EarningsRecord]
    company_facts: dict
    sector_etf_prices: list[Price]    # for sector RS
    spy_prices: list[Price]           # for macro regime
```

`shared_data.py` exposes `fetch_shared_data(ticker, request) -> SharedData` that delegates to existing `v2/data/*` clients. For v1 the cache is an in-process module-level dict keyed by `(ticker, scan_date)` — no Redis or persistent cache. Cron jobs run in a fresh process daily so the cache simply means the 10 modules within one ticker's pipeline don't re-fetch.

## `detector_backtest` (replay logic)

### Input
- `request.scanner_context.triggered_detectors` — list of detector names that fired today
- `request.ticker`
- `synthesizer.strategy` — the `TradePlan` (need entry/target/stop/horizon)

### Algorithm
1. Query historical scanner-replay data for this ticker. Source: existing `backtest_ndx100_30d_*.csv` plus any additional historical-replay CSVs that get generated. Need a stable source — likely a new `outputs/detector_history/<ticker>.csv` that gets refreshed periodically.
2. Find every past date where the detector set matched today's triggers. Matching rule:
   - If today fires `n` detectors and `n ≤ 2`: require exact set match.
   - If today fires `n ≥ 3`: require Jaccard overlap ≥ 0.6 (e.g., today has {earnings, insider, obv} → past day with {earnings, insider} matches at overlap = 2/3 ≈ 0.67).
3. For each matching past date:
   - Treat past_date's close as entry.
   - Apply same target/stop/horizon distances proportionally (in pct terms, not dollars — since price level changes).
   - Walk forward day-by-day: hit target? hit stop? horizon expired? Record outcome.
4. Aggregate: matches_found, win_rate, avg_pnl_pct, max_drawdown_pct, avg_holding_days.
5. Classify `sample_quality`: strong (≥10) / moderate (5–9) / weak (2–4) / insufficient (0–1). Emit `caveat` string when ≤9.

### Data dependency
The "historical detector trigger CSV per ticker" must exist. Two options:
- **(preferred)** Reuse existing `backtest_ndx100_30d_*.csv` plus extend with a longer-horizon historical replay (e.g., past 2 years of trigger history per ticker). This is a one-time backfill job.
- **(fallback)** When no historical data exists for a ticker (e.g., a ticker outside the NDX100 backtest window), `BacktestSummary.sample_quality = "insufficient"`, `caveat = "No historical detector trigger data for this ticker"`.

### What this does NOT do
- Does not validate the strategy against any other entry/exit logic — only the trade plan that was synthesized.
- Does not adjust for cost-bp (the synthesizer's TradePlan is what gets replayed; backtest report is "would this exact plan have worked?" not "what's the optimal plan?"). 10bp can be added by the consumer who reads the BacktestSummary.

### Synthesizer reads backtest? No.
Per the DAG, `detector_backtest` runs AFTER `synthesizer`. The synthesizer writes the TradePlan based on module evidence only; backtest is informational and shown side-by-side with the plan in the HTML so the user can weight them. This means the LLM cannot tune its plan to backtest results — desirable for v1 (avoids overfitting to historical samples).

## HTML output

Template `templates/report.html`. Sections in order:

1. **Header**: ticker, scan_date, `report_goal` label, persona-usage badge
2. **Executive summary**: 3–5 lines, written by synthesizer, shaped by `report_goal`
3. **Trade plan box**: direction, entry / target / stop / horizon / sizing, confidence bar, rationale
4. **Backtest box**: matches_found, win_rate, avg_pnl_pct, sample_quality badge, caveat
5. **Detail sections**: one per module in fixed order (macro → sector → fundamentals → financials → valuation → technical → sentiment → risk_position → debate). Skipped modules omitted.
6. **Persona assignments footer**: when `use_personas=True`, show router's per-module persona choices + the rationale string from the router LLM.

Styling: inline CSS, dark-mode toggle (matches stock-analyze-skills aesthetic), no external assets except base64-embedded charts. Email-safe (Gmail compatible — same constraints as existing notification system).

## Database additions

Two new tables in `app/backend/database/models.py`:

```python
class ResearchReport(Base):
    __tablename__ = "research_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str]
    scan_date: Mapped[str]          # YYYY-MM-DD
    request_json: Mapped[str]       # serialized ResearchRequest
    report_markdown: Mapped[str]
    rendered_html: Mapped[str]
    use_personas: Mapped[bool]
    persona_assignments_json: Mapped[str | None]  # serialized assignments
    duration_seconds: Mapped[float]
    created_at: Mapped[datetime]
    # FK to PipelineRun? No — research runs in its own job, not bundled with the
    # legacy pipeline runs. Standalone.
    __table_args__ = (Index("ix_research_ticker_date", "ticker", "scan_date"),)


class ResearchTradePlan(Base):
    __tablename__ = "research_trade_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("research_reports.id"))
    direction: Mapped[str]          # long / short / stand_aside
    entry_price: Mapped[float | None]
    target_price: Mapped[float | None]
    stop_price: Mapped[float | None]
    horizon_days: Mapped[int]
    sizing_pct: Mapped[float]
    confidence: Mapped[int]
    rationale: Mapped[str]
    # backtest summary fields inlined here (no separate table — 1:1 with plan)
    backtest_matches_found: Mapped[int]
    backtest_win_rate: Mapped[float | None]
    backtest_avg_pnl_pct: Mapped[float | None]
    backtest_sample_quality: Mapped[str]
    created_at: Mapped[datetime]
```

The legacy `PipelineRun` table is unchanged.

## Scheduler / cron integration

`app/backend/services/scheduler_service.py` gets a second job:

- **Existing `_run_pipeline_job`**: 4:30pm ET weekdays, legacy pipeline. Unchanged.
- **New `_run_research_job`**: 4:35pm ET weekdays (after scanner has cached), runs the new research pipeline on the same top-N watchlist that the legacy pipeline used. Reads from the scanner cache to avoid re-scanning.

Both jobs are independent — failure of one doesn't affect the other.

## API additions

`app/backend/routes/` gains a `research.py`:

- `POST /research/run` — body is `ResearchRequest` JSON, returns research report (sync; takes ~30–60s)
- `GET /research/reports?ticker=X&limit=20` — list recent reports for a ticker
- `GET /research/reports/{id}` — full report JSON + rendered HTML
- `GET /research/reports/{id}/html` — raw HTML for iframe display

## Notification

Email handler (existing `app/backend/services/notifications/email_handler.py`) gets a new render path for research reports. Daily cron sends one email containing all top-N reports concatenated (separator between tickers) so user reads one email per day, N reports inside.

On-demand calls return the report inline; if user wants email delivery they request it explicitly via a query param or UI button.

## A/B comparison

Both pipelines persist their output:
- Legacy: `PipelineRun.agent_decisions[ticker] = {action: BUY, qty: N, confidence: C, ...}`
- New: `ResearchTradePlan` rows linked to `ResearchReport`

After 30+ days, a comparison script (`scripts/compare_pipelines.py`, not in scope of v1) computes paper-trade PnL for each pipeline's decisions over the same ticker / scan_date pairs. The comparison itself is **out of scope of this spec**; the spec only ensures the data needed for the comparison gets persisted.

## What is explicitly unchanged

- `v2/scanner/`, all detectors and scoring logic
- `src/agents/`, all legacy agents and their tests
- `src/main.py:run_hedge_fund`
- `src/graph/state.py`
- Existing tests
- Existing API routes
- Existing notification subscriptions

The new pipeline ships in its own namespace. Nothing the old pipeline reads is mutated.

## Risks

| Risk | Mitigation |
|---|---|
| **Cost scaling**: 10–14 LLM calls × top-N tickers × daily ≈ ~$0.50/month at deepseek-chat; cheap. But if persona-router falls over and starts requesting debate for every ticker, jumps to ~$1.50/month. | Hard cap in router prompt: "debate only when 2 personas genuinely disagree on the ticker thesis"; alert on debate-firing-rate > 50%. |
| **Module data fetching**: SharedData fetcher pulls 10+ sources per ticker; if EODHD or Finnhub rate-limits, modules degrade. | Each module checks `shared_data` field for `None` and emits `skipped=True` rather than raising. SharedData fetch logs partial failures. |
| **Trade-plan price staleness**: synthesizer writes entry_price based on data at scan time; by the time user reads, market may have moved. | Report header timestamps everything. Plan is informational, not auto-executed. |
| **detector_backtest needs historical data not yet captured**: out-of-NDX100 tickers, or recent tickers, may have no trigger history. | Backtest emits `sample_quality="insufficient"` with a clear caveat string; synthesizer's confidence is not gated on backtest result alone. |
| **A/B output drift**: synthesizer's TradePlan can drift from legacy PM decisions in confusing ways, making A/B muddier than expected. | This is the whole point — comparison is exploratory, not pass/fail. |
| **HTML email rendering**: 10-section reports may blow past Gmail's 102KB clip threshold. | Truncate per-module markdown to ~150 words; charts as small base64 PNGs; if total > 100KB, drop chart sections and link to a hosted version. |
| **Persona-router LLM hallucination**: router could pick a persona that isn't in the module's `supports_personas` list. | Validate router output against each module's allowed set; on mismatch, fall back to `None` (objective) for that module. |

## Verification plan

1. Unit tests per module: each `AnalysisModule.run` returns a `ModuleResult` with non-empty markdown given mocked `SharedData`. Objective and persona paths both covered.
2. Router unit test: given a synthetic profile + scanner_context, returns a valid JSON shape; invalid persona names get rejected.
3. Synthesizer unit test: given mocked `module_results`, returns a `TradePlan` with valid field types; `stand_aside` path triggers correctly given a bear-leaning input.
4. `detector_backtest` unit test: given synthetic trigger history CSV, computes win_rate / avg_pnl_pct correctly.
5. Pipeline integration test: one ticker, mocked data, mocked LLMs, asserts a `rendered_html` non-empty string with all expected sections.
6. End-to-end smoke: one real ticker (NVDA), real LLM, real data, manual inspection of the HTML. Inspect Gmail rendering.
7. Database migration: alembic revision adds the two new tables; downgrade clean.
8. Schedule integration: with mocked scanner output, `_run_research_job` triggers correctly at 4:35pm ET; failure doesn't kill the scheduler.

## Open questions (resolved during brainstorming)

- **Why not just port stock-analyze-skills directly?** Because skills are designed for interactive Claude Code sessions, not for production cron. Python implementation needed.
- **Why two meta-agents instead of one?** Separation of concerns: router decides *who* speaks per section; synthesizer compiles *what they said*. Two simpler prompts > one giant prompt.
- **Why preserve legacy?** Both pipelines on the same scanner output gives long-running A/B data; can't get that from a one-shot ablation.
- **Why per-ticker isolated (no portfolio aggregation)?** The user explicitly wants reports first, decisions second — and the legacy pipeline already handles portfolio aggregation, so the new pipeline owns the per-ticker depth.

## Out of scope (future work)

- Cross-pipeline comparison script (`scripts/compare_pipelines.py`)
- Frontend UI for on-demand research requests (the API is in scope; the form UI is a follow-up)
- Persona-router auto-tuning (e.g., reinforcement signal from which assignments correlate with strategy outcomes)
- Multi-day TradePlan revision (today's plan supersedes yesterday's; no incremental edit flow yet)
- Real-money trade integration
- Streaming response from `/research/run` (returns sync for v1)
