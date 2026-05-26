# Scanner → Agent Bridge — Design

**Status:** draft (awaiting user review)
**Date:** 2026-05-18
**Author:** brainstormed via `superpowers:brainstorming` skill

---

## 1. Context

The repo today contains two independently-working systems:

1. **Scanner** (`v2/scanner/`) — 10 detectors that fire on event/setup signals
   (earnings, insider clusters, breakouts, OBV divergence, etc.), composite-scored
   into a daily top-N watchlist. Designed as an **attention filter** for downstream
   AI agents (see `[[project-scanner-design-intent]]`).
2. **Agent layer** (`src/agents/`, `src/main.py`) — a LangGraph workflow with 13
   persona analysts (Buffett, Graham, Wood, Burry, Munger, Damodaran, Lynch,
   Fisher, Druckenmiller, Pabrai, Jhunjhunwala, Taleb, Ackman) + 5 analyst nodes
   (fundamentals, technicals, valuation, sentiment, news sentiment, growth) +
   `risk_management_agent` + `portfolio_manager`. Currently invoked by CLI with a
   manually-supplied ticker list.

**The gap:** the two systems are disconnected. The scanner produces a ranked
watchlist with rich detector context (`triggered_detectors`, `severity_z`,
`direction`, per-detector `components`), but `run_hedge_fund(...)` only accepts
a flat `tickers: list[str]` — the detector context is thrown away. The agents
each independently decide what to look at, oblivious to the work the scanner
already did.

**This spec proposes a bridge** so:

- Scanner output (top-N + detector context) automatically flows into the agent
  workflow.
- A new `scanner_signal` analyst node joins the LangGraph alongside fundamentals/
  technicals/etc., contributing the scanner's view as one more signal that
  `risk_management_agent` and `portfolio_manager` weigh.
- Two consumers share the bridge: an **interactive UI button** ("analyze selected
  with agents") and a **scheduled daily pipeline** (auto-run scanner → agents
  after market close).

## 2. Goals & non-goals

**Goals**
- A first-class LangGraph node `scanner_signal` that turns scanner output into a
  standard analyst signal (signal/confidence/reasoning), idiomatic to the
  existing workflow.
- A thin pipeline orchestrator (`v2/pipeline/orchestrator.py`) that composes
  `run_scan` → `scanner_context` → `run_hedge_fund` with template-selected
  analysts.
- Default analyst **templates** (balanced / value / growth / quick / custom) so
  users don't decide "which 8 of 19 agents" from a blank slate.
- Persistence of pipeline runs to DB so UI can show history and daily runs are
  observable.
- API + UI integration: `POST /pipeline/run`, `GET /pipeline/runs[/{id}]`, a
  watchlist "Analyze with agents" button, an "Agent runs" history panel.

**Non-goals (out of scope, future v2)**
- Backtest scanner→agent end-to-end alpha (would require replaying agents over
  historical scan dates — expensive in LLM tokens, deferred until v1 in
  production).
- Live trading auto-execute on agent decisions.
- Per-agent custom prompt tuning UI.
- Multi-model routing (each persona on a different LLM).
- Real-time websocket streaming of in-progress runs (poll-based for v1).
- Customizable scanner template editor in UI (v1 templates are
  defined in code; UI just picks from a dropdown).

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     scanner→agent bridge                            │
└─────────────────────────────────────────────────────────────────────┘

Two triggers, one orchestrator:
  • UI button:    POST /pipeline/run    {top_n, template, scan_date?, tickers?}
  • Daily cron:   scheduler 4:30 PM ET → POST /pipeline/run with default config

       │
       ▼
┌─────────────────────────────────┐
│ v2/pipeline/orchestrator.py     │
│ ─ run_scan() → ScoredEntry[]    │
│ ─ translate → scanner_context   │
│ ─ resolve template → analysts   │
│ ─ run_hedge_fund(               │
│     tickers, scanner_context,   │
│     selected_analysts)          │
│ ─ persist to pipeline_runs DB   │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│           src/main.py:run_hedge_fund (LangGraph workflow)           │
│                                                                     │
│   start_node                                                        │
│      │                                                              │
│      ├─→ scanner_signal      ──┐  ← NEW analyst node (rule + LLM)  │
│      ├─→ fundamentals_analyst──┤                                    │
│      ├─→ technical_analyst   ──┤                                    │
│      ├─→ valuation_analyst   ──┤  (others by template choice)      │
│      ├─→ warren_buffett      ──┤                                    │
│      └─→ ...                 ──┤                                    │
│                                ▼                                    │
│                      risk_management_agent                          │
│                                │                                    │
│                                ▼                                    │
│                  portfolio_manager → final decisions                │
└─────────────────────────────────────────────────────────────────────┘
```

## 4. ScannerSignalAgent — the new node

**File:** `src/agents/scanner_signal.py`

### Contract

Implements the standard analyst signature established by the existing 19 agents:

```python
def scanner_signal_agent(
    state: AgentState,
    agent_id: str = "scanner_signal_agent",
) -> dict:
    """Read state['data']['scanner_context'][ticker] for each ticker;
    write state['data']['analyst_signals'][agent_id] = {
        ticker: {'signal': ..., 'confidence': ..., 'reasoning': {...}}
    }
    """
```

### Input — `state['data']['scanner_context']`

`dict[str, ScannerContext]` where `ScannerContext` is:

```python
{
    "scan_date": "2024-08-01",
    "rank": 1,
    "composite_score": 87.5,
    "direction": "bullish",          # bullish | bearish | neutral
    "event_severity": 3.2,
    "triggered_detectors": ["earnings_event", "intraday_move"],
    "triggered_components": {        # parsed from triggered_components_json
        "earnings_event": {
            "phase": 2.0,
            "biz_days_to_event": 1.0,
            "surprise_pct": 0.045,
            "raw_z": 1.8,
        },
        "intraday_move": {"z_cvo": 2.4, ...},
    },
}
```

This is a per-ticker subset of `v2.scanner.models.ScoredEntry` plus the
JSON-decoded components — exactly the shape needed for the new agent to
reason about why each ticker was flagged.

### Decision logic — hybrid (rule + LLM)

Per the decisions log, the rule path is deterministic and the LLM path
generates the human-readable reasoning text. The rule output is the
source of truth for `signal` and `confidence`; the LLM produces a
short paragraph that goes into `reasoning.summary`.

**Rule-based signal/confidence:**

```
signal     = scanner_context.direction          # bullish | bearish | neutral
confidence = scanner_context.composite_score    # 0-100, already on the
                                                # right scale
```

Edge case: when `composite_score` is unusually low but a detector still
fired (e.g., a single low-severity SQZ), the agent returns the signal as
specified but the confidence remains the composite score — downstream
agents see "low conviction" naturally.

When a ticker is in the workflow but NOT in `scanner_context` (e.g.,
user added it manually outside the watchlist), the agent returns:

```
signal=neutral, confidence=0,
reasoning="Ticker not in today's scanner watchlist"
```

— a clean abstention that doesn't bias the downstream weighted vote.

**LLM-based reasoning:**

Prompt template (concrete; will live in `scanner_signal.py`):

```
You are an analyst summarizing a multi-detector scanner output.

Ticker: {ticker} (scan date {scan_date})
Composite rank: {rank}, score {composite_score}/100
Scanner-inferred direction: {direction}

Detectors that fired:
{for each triggered detector:}
  - {detector_name} severity_z={severity_z:+.2f} direction={direction}
    components: {short bullet of 2-3 most informative components}

In 2-3 sentences, explain what these signals collectively suggest about
this ticker's near-term setup. Be specific about WHAT the detectors are
telling us (e.g., "post-event drift" vs "pre-event setup"). Do NOT
make a recommendation — that's the portfolio_manager's job.
```

The LLM call uses the same model as the workflow
(`state['metadata']['model_name']` + `model_provider`), so the user's
existing model selection applies.

### Failure modes

1. **`scanner_context` missing entirely** (legacy callers without the bridge):
   agent returns `signal=neutral, confidence=0` for every ticker with
   reasoning `"Scanner context not provided"`. Workflow still runs.
2. **LLM call fails:** rule-based signal still written; reasoning falls back to
   a deterministic string `"Scanner flagged {N} signals: {names}.
   Composite score {score}."`
3. **Ticker present in `scanner_context` but `triggered_detectors` empty**
   (in scope of scan, but didn't fire above any threshold): signal=neutral,
   confidence=composite_score, reasoning notes "scanner saw no qualifying
   signals."

## 5. Templates

**File:** `v2/pipeline/templates.py`

Curated analyst lists so users don't pick from a blank slate. Four defaults
that cover the common archetypes; `custom` lets the user pass an explicit
list.

```python
TEMPLATES: dict[str, list[str]] = {
    # name      → analyst keys (must match keys in ANALYST_CONFIG +
    #             the new "scanner_signal")
    "balanced": [
        "scanner_signal",
        "warren_buffett", "cathie_wood", "michael_burry",  # 3 persona
        "fundamentals_analyst", "technical_analyst",
        "valuation_analyst", "sentiment_analyst", "growth_analyst",
    ],
    "value": [
        "scanner_signal",
        "warren_buffett", "ben_graham", "charlie_munger", "mohnish_pabrai",
        "fundamentals_analyst", "valuation_analyst",
    ],
    "growth": [
        "scanner_signal",
        "cathie_wood", "peter_lynch", "phil_fisher",
        "stanley_druckenmiller",
        "technical_analyst", "sentiment_analyst", "growth_analyst",
    ],
    "quick": [
        "scanner_signal",
        "fundamentals_analyst", "technical_analyst",
        "valuation_analyst", "sentiment_analyst",
    ],
}
DEFAULT_TEMPLATE = "balanced"
```

**Resolution:** the orchestrator accepts either a `template: str` ("balanced") or
an explicit `analysts: list[str]`. Mutually exclusive — `template` is
sugar for picking a pre-baked list.

**Validation:** at orchestrator entry, every name in the resolved list must
either be `"scanner_signal"` or appear in `ANALYST_CONFIG`. Unknown keys raise
`ValueError` early (don't wait for LangGraph to fail mid-workflow).

**Cost reference** (GPT-4.1 at current pricing, ~$0.05/agent/ticker):

| Template | Agents | Top-5 daily | Top-20 daily |
|---|---|---|---|
| quick    | 5 | $1.25/day = $40/mo | $5/day = $150/mo |
| balanced | 9 | $2.25/day = $70/mo | $9/day = $270/mo |
| value    | 7 | $1.75/day = $55/mo | $7/day = $210/mo |
| growth   | 8 | $2.00/day = $60/mo | $8/day = $240/mo |

Plus `risk_management_agent` + `portfolio_manager` (always run, ~$0.10/run
fixed). UI surfaces a cost estimate before running.

## 6. Pipeline orchestrator

**File:** `v2/pipeline/orchestrator.py`

```python
@dataclass
class PipelineResult:
    run_id: str                                # UUID
    scan_date: str
    template: str                              # or "custom"
    selected_analysts: list[str]
    watchlist: list[ScoredEntry]               # full scanner output
    agent_decisions: dict                      # portfolio_manager output
    analyst_signals: dict[str, dict[str, dict]]  # per-agent per-ticker signals
    duration_seconds: float
    error: str | None


def run_pipeline(
    *,
    scan_date: str | None = None,              # default today
    universe: str = "nasdaq100",
    top_n: int = 5,
    template: str = "balanced",
    custom_analysts: list[str] | None = None,  # overrides template
    portfolio: dict | None = None,             # default {"cash": 100_000}
    persist: bool = True,
) -> PipelineResult:
    """Run scanner → agents end-to-end."""
```

Internal flow:

1. Resolve `scan_date` (default = latest trading day ≤ today).
2. Resolve analyst list (`custom_analysts` wins over `template`).
3. Call `run_scan(universe, end_date=scan_date, top_n=top_n)` → `ScoredEntry[]`.
4. Build `scanner_context: dict[ticker, ScannerContext]`.
5. Call `run_hedge_fund(tickers=top_tickers, scanner_context=..., selected_analysts=..., portfolio=...)`.
6. Wrap into `PipelineResult`.
7. If `persist=True`, write to `pipeline_runs` table.

**No new scanner code** — uses `v2.scanner.runner.run_scan` as-is.
**Single minimal change to `run_hedge_fund`** — accept `scanner_context` kwarg
and write it to `state['data']['scanner_context']` before workflow start.

## 7. AgentState shape changes

`src/graph/state.py` extension:

```python
class ScannerContext(TypedDict, total=False):
    scan_date: str
    rank: int
    composite_score: float
    direction: Literal["bullish", "bearish", "neutral"]
    event_severity: float
    triggered_detectors: list[str]
    triggered_components: dict[str, dict[str, float]]


# Extend AgentState['data'] schema docs (it's an open dict, no Pydantic
# enforcement) — add note that data may carry:
#   data["scanner_context"]: dict[str, ScannerContext]
```

`state['data']['analyst_signals']['scanner_signal_agent']` follows the
existing `{ticker: {signal, confidence, reasoning}}` shape. No new top-level
state field.

## 8. Persistence

**New SQLAlchemy model:** `app/backend/database/models.py`

```python
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(String, primary_key=True)         # UUID
    scan_date = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=now)
    template = Column(String, nullable=False)
    selected_analysts = Column(JSON, nullable=False)  # list[str]
    top_n = Column(Integer, nullable=False)
    universe = Column(String, nullable=False)
    watchlist_json = Column(JSON, nullable=False)     # serialized ScoredEntry[]
    agent_decisions_json = Column(JSON, nullable=True)
    analyst_signals_json = Column(JSON, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    status = Column(String, nullable=False)          # running|complete|error
    error = Column(Text, nullable=True)
```

Alembic migration: `app/backend/alembic/versions/<hash>_add_pipeline_runs.py`.

Repository pattern follows the existing `app/backend/repositories/`
convention (see `scanner_repository.py` as the model).

## 9. API surface

**File:** `app/backend/routes/pipeline.py`

```
POST /pipeline/run
  Body: { scan_date?, universe?, top_n?, template?, custom_analysts?,
          portfolio? }
  Behavior: enqueue a run (background task), return immediately with
            { run_id, status: "running" }
  Why background: a balanced template over top-5 takes ~30-60s due to
                  LLM calls; we don't want the HTTP request to hang.

GET /pipeline/runs
  Query: ?limit=20&template=balanced&since=2026-05-01
  Returns: paginated list of PipelineRun summaries (no full JSON blobs)

GET /pipeline/runs/{run_id}
  Returns: full PipelineRun including watchlist + agent decisions

GET /pipeline/templates
  Returns: { templates: { balanced: [...], value: [...], ... },
             agent_metadata: { warren_buffett: {display_name, ...}, ... } }
```

Background execution: `BackgroundTasks` (FastAPI built-in) is enough for v1
since runs are infrequent (a few per day max). If concurrency grows we move
to a real queue.

## 10. Daily scheduling

The existing `app/backend/services/scheduler_service.py` already drives the
daily scanner run; we add one more job:

```python
# Pseudocode for the new job (registered alongside the scan job)
@scheduler.scheduled_job("cron", hour=16, minute=30, timezone="US/Eastern")
def daily_pipeline_job():
    # Wait until daily scan has completed (read latest scan from DB)
    # Default config: top_n=5, template="balanced", universe="nasdaq100"
    pipeline.run_pipeline(...)
```

Daily config (top_n, template, universe) is sourced from a single row in a
new `pipeline_schedule` config table; the row is editable via a small
admin UI / SQL — out of scope to build a full config UI in v1.

## 11. UI integration

**New components** in `app/frontend/src/components/panels/scanner/`:

1. **`analyze-button.tsx`** — appears in the watchlist toolbar. Multi-select
   rows in the watchlist → button enabled. Click opens a modal:
   - Template dropdown (balanced / value / growth / quick / custom)
   - If custom: checkbox list of all 19 agents + scanner_signal
   - "Run analysis" submit
   - On submit: `POST /pipeline/run`, get `run_id`, navigate to detail view

2. **`agent-run-detail.tsx`** — shows one pipeline run:
   - Header: scan date, template, status, duration, agents that ran
   - Per-ticker section (one row per top-N ticker):
     - Scanner badge (composite score, triggered detectors)
     - Grid of agent signals (each agent column shows signal pill + confidence
       bar + collapsible reasoning)
     - portfolio_manager decision row (final BUY/SELL/HOLD + sizing)

3. **`agent-runs-list.tsx`** — history panel under a new top-level route
   (`/scanner/agent-runs`). Sortable list of past runs with click-through to
   detail.

**Service:** `app/frontend/src/services/pipeline-service.ts` — typed fetch
wrappers for the 4 endpoints.

UI work depends on backend endpoints landing first.

## 12. Testing strategy

**Unit tests**

- `src/agents/test_scanner_signal.py`
  - Rule logic across all `direction` values; rank/composite_score edge
    cases (0, 100, missing); ticker missing from `scanner_context` (clean
    abstention); empty `triggered_detectors` set.
  - LLM mocked: assert prompt contains the expected detector context;
    assert fallback reasoning when LLM raises.

- `v2/pipeline/test_orchestrator.py`
  - Mock `run_scan` + `run_hedge_fund`; assert composition order, that
    `scanner_context` is built from `ScoredEntry[]`, that template resolution
    works for all four built-ins + custom, that unknown analyst names raise
    `ValueError` early.

- `v2/pipeline/test_templates.py`
  - Every template's analyst keys validate against `ANALYST_CONFIG` ∪
    `{"scanner_signal"}`.

**Integration tests**

- `tests/test_pipeline_repository.py` — CRUD + JSON serialization roundtrip
  for `PipelineRun`.
- `tests/test_pipeline_routes.py` — HTTP routes with a mocked orchestrator;
  background task fires; status polling works.
- Gated live test (`AGENT_LIVE=1`): one ticker × quick template, asserts a
  `PipelineResult` with non-empty `agent_decisions`.

**No changes to existing tests** are anticipated; the new analyst is opt-in
(only runs when `scanner_signal` is in `selected_analysts`).

## 13. Migration / rollout

The bridge is additive — `run_hedge_fund(..., scanner_context=None)` keeps
working for legacy CLI users. The new analyst node only joins the graph when
the orchestrator (or the user via CLI flag) requests it.

1. Land backend changes behind no flag — the analyst won't be invoked unless
   selected.
2. Land the API + DB.
3. Land the UI button; verify end-to-end manually.
4. Enable the scheduler job once a user confirms manual runs are correct.

## 14. Trade-offs considered

**ScannerSignalAgent: rule-only vs hybrid vs LLM-only.** Decided hybrid: rules
own the deterministic decision (same philosophy as the scanner itself — the
scanner is rule-based by design), LLM only produces the explanation text
downstream agents read. Pure LLM would re-litigate decisions the scanner
already made; pure rules would leave downstream agents reading bare numbers
without the "why."

**Orchestrator vs richer agent.** Considered making the scanner_signal agent
itself call `run_scan` lazily ("if scanner_context is missing, scan now").
Rejected: violates separation of concerns; would slow every workflow run; the
scanner is a separate system with its own thread-pool lifecycle.

**Pre-baked templates vs free-form picker.** Both. Templates as the default
path (low cognitive load + cost predictability); `custom_analysts` for power
users.

**Background task vs synchronous endpoint.** Background is needed —
balanced/value templates take 30-60s, and `POST /pipeline/run` would
otherwise time out at common reverse-proxy defaults (60s nginx, 30s some
load balancers).

**Persistence shape.** Considered normalizing watchlist + agent signals into
relational tables. Rejected for v1: JSON blob is simpler, query patterns
are "fetch run by id" and "list recent runs" (no aggregation across runs
needed yet). If we add cross-run analytics later, ETL the blobs into a
star schema.

## 15. Open questions

1. **Which model should daily pipeline use?** Cheap GPT-4o-mini vs GPT-4.1?
   The reasoning text quality matters because risk_management/portfolio_manager
   read it. Recommend: same model for the whole workflow (consistency), let
   the user pick in pipeline_schedule config.

2. **Should the scheduler wait for the daily scan to finish?** Today the
   scanner runs in `scheduler_service`; the pipeline depends on its output.
   Two options: (a) chain jobs (scan → wait → pipeline); (b) pipeline reads
   the latest persisted scan (could be stale). Recommend chained — fail loud
   if scan is missing.

3. **What's the right default for `top_n` in the daily run?** 5 keeps cost
   bounded; 20 covers the full watchlist. Recommend 5 for v1 — easy to
   bump after observing real usage costs.

## 16. Affected files (high level — implementation plan will detail)

**New**
- `src/agents/scanner_signal.py`
- `src/agents/test_scanner_signal.py`
- `v2/pipeline/__init__.py`
- `v2/pipeline/orchestrator.py`
- `v2/pipeline/templates.py`
- `v2/pipeline/test_orchestrator.py`
- `v2/pipeline/test_templates.py`
- `app/backend/routes/pipeline.py`
- `app/backend/repositories/pipeline_repository.py`
- `app/backend/models/pipeline_schemas.py`
- `app/backend/alembic/versions/<hash>_add_pipeline_runs.py`
- `tests/test_pipeline_routes.py`
- `tests/test_pipeline_repository.py`
- `app/frontend/src/services/pipeline-service.ts`
- `app/frontend/src/components/panels/scanner/analyze-button.tsx`
- `app/frontend/src/components/panels/scanner/agent-run-detail.tsx`
- `app/frontend/src/components/panels/scanner/agent-runs-list.tsx`
- `app/frontend/src/types/pipeline.ts`

**Modified**
- `src/main.py` — `run_hedge_fund` accepts `scanner_context` kwarg
- `src/utils/analysts.py` — register `scanner_signal` in `ANALYST_CONFIG`
- `src/graph/state.py` — `ScannerContext` TypedDict for documentation
- `app/backend/main.py` — register `/pipeline` router
- `app/backend/database/models.py` — add `PipelineRun` model
- `app/backend/services/scheduler_service.py` — register daily pipeline job
- `app/frontend/src/components/panels/scanner/watchlist-table.tsx` — add
  toolbar slot for `<AnalyzeButton/>`
