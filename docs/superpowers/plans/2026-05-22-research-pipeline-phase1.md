# Per-Stock Research Pipeline — Phase 1 (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core programmatic research pipeline at `src/research/` — 8 objective analysis modules + synthesizer LLM + deterministic detector-replay backtest — wired through LangGraph and runnable via CLI. No personas, no DB, no API, no scheduler integration, no HTML email. Phase 1 ships when `python -m src.research --ticker NVDA` returns a `TradePlan` + `BacktestSummary` printout.

**Architecture:** New `src/research/` package, hard-isolated from `src/agents/` (legacy pipeline preserved). Each module is one focused LLM call + deterministic data prep; modules share a single `SharedData` fetch per pipeline run. LangGraph state carries `request → module_results → strategy → backtest_summary`. The 9th "module" (`detector_backtest`) is deterministic Python, no LLM.

**Tech Stack:** Python 3.13, LangGraph (already installed), Pydantic v2 (already installed), DeepSeek-chat via `src/llm/models.py`. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-22-research-pipeline-design.md`

**This plan is Phase 1 of 3.** Phase 2 adds personas (router + 8 persona files + debate module). Phase 3 adds production wiring (DB + API + cron + HTML email). Each phase ships independently.

---

## File structure (Phase 1)

```
src/research/
  __init__.py                     # exports public types
  models.py                       # ResearchRequest, TradePlan, ModuleResult, BacktestSummary, ResearchState
  llm.py                          # small helper: call_research_llm(prompt, pydantic_model)
  shared_data.py                  # SharedData dataclass + fetch_shared_data() with per-process cache
  synthesizer.py                  # synthesize(request, module_results) -> (report_markdown, TradePlan)
  pipeline.py                     # LangGraph wiring; run_research(request) -> ResearchState
  __main__.py                     # CLI: python -m src.research --ticker NVDA
  modules/
    __init__.py                   # exports ALL_MODULES list
    base.py                       # AnalysisModule ABC
    macro.py
    sector.py
    fundamentals.py
    financials.py
    valuation.py
    technical.py
    sentiment.py
    risk_position.py              # sequential after valuation + technical
    detector_backtest.py          # deterministic, no LLM

tests/research/
  __init__.py
  conftest.py                     # fixtures: mock SharedData, mock LLM
  test_models.py
  test_shared_data.py
  test_modules_base.py            # AnalysisModule ABC contract
  test_module_macro.py            # repeated pattern per module
  test_module_sector.py
  test_module_fundamentals.py
  test_module_financials.py
  test_module_valuation.py
  test_module_technical.py
  test_module_sentiment.py
  test_module_risk_position.py
  test_module_detector_backtest.py
  test_synthesizer.py
  test_pipeline.py
  test_cli.py
```

**What is NOT touched in Phase 1:**
- `src/agents/` (legacy pipeline lives, unchanged)
- `src/main.py:run_hedge_fund` (unchanged)
- `v2/scanner/` (unchanged)
- `app/backend/` (unchanged)
- Database schema (no migrations in Phase 1)

---

## Task 1: Package scaffold + data models

**Files:**
- Create: `src/research/__init__.py`
- Create: `src/research/models.py`
- Create: `tests/research/__init__.py`
- Create: `tests/research/test_models.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_models.py`:

```python
"""Smoke tests for src.research.models — every dataclass round-trips
through dict serialization without losing information, and Literal
field validation rejects bad values."""

from __future__ import annotations

import pytest
from dataclasses import asdict

from src.research.models import (
    ResearchRequest,
    TradePlan,
    ModuleResult,
    BacktestSummary,
)


class TestResearchRequest:
    def test_minimal_construction(self):
        r = ResearchRequest(
            ticker="NVDA",
            holding_status="watching",
            target_position_pct=0.05,
            risk_tolerance="moderate",
            report_goal="new_entry",
            use_personas=False,
            scanner_context=None,
        )
        assert r.ticker == "NVDA"
        assert r.target_position_pct == 0.05
        assert r.scanner_context is None

    def test_with_scanner_context(self):
        ctx = {"triggered_detectors": ["earnings_event"], "rank": 1}
        r = ResearchRequest(
            ticker="MU",
            holding_status="considering_buy",
            target_position_pct=0.03,
            risk_tolerance="aggressive",
            report_goal="new_entry",
            use_personas=True,
            scanner_context=ctx,
        )
        assert r.scanner_context == ctx


class TestTradePlan:
    def test_long_plan(self):
        p = TradePlan(
            direction="long",
            entry_price=145.0,
            target_price=165.0,
            stop_price=138.0,
            horizon_days=30,
            sizing_pct=0.05,
            confidence=72,
            rationale="Earnings beat + insider cluster + below 50d SMA.",
        )
        assert p.direction == "long"
        assert p.target_price - p.entry_price == 20.0

    def test_stand_aside_has_none_prices(self):
        p = TradePlan(
            direction="stand_aside",
            entry_price=None,
            target_price=None,
            stop_price=None,
            horizon_days=0,
            sizing_pct=0.0,
            confidence=0,
            rationale="Data insufficient.",
        )
        assert p.direction == "stand_aside"
        assert p.entry_price is None


class TestModuleResult:
    def test_default_metrics_empty(self):
        m = ModuleResult(
            module_name="macro",
            persona_used=None,
            markdown="SPY +5%, regime up.",
        )
        assert m.key_metrics == {}
        assert m.chart_data is None
        assert m.skipped is False

    def test_skipped_module(self):
        m = ModuleResult(
            module_name="sentiment",
            persona_used=None,
            markdown="",
            skipped=True,
            skip_reason="No news data available",
        )
        assert m.skipped is True


class TestBacktestSummary:
    def test_strong_sample(self):
        b = BacktestSummary(
            matches_found=15,
            win_rate=0.6,
            avg_pnl_pct=0.08,
            max_drawdown_pct=-0.12,
            avg_holding_days=18.5,
            sample_quality="strong",
            caveat=None,
        )
        assert b.sample_quality == "strong"

    def test_insufficient_sample_carries_caveat(self):
        b = BacktestSummary(
            matches_found=0,
            win_rate=None,
            avg_pnl_pct=None,
            max_drawdown_pct=None,
            avg_holding_days=None,
            sample_quality="insufficient",
            caveat="No historical trigger matches for this ticker",
        )
        assert b.win_rate is None
        assert b.caveat is not None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_models.py -v
```
Expected: ModuleNotFoundError for `src.research.models`.

- [ ] **Step 3: Implement models**

Write `src/research/__init__.py`:

```python
"""Per-stock research pipeline (Phase 1: core).

Public types live in ``src.research.models``. Pipeline entry-point is
``src.research.pipeline.run_research``. CLI: ``python -m src.research``.

This package is intentionally isolated from ``src/agents/`` (the legacy
portfolio pipeline). Both live in parallel; the scanner feeds both.
"""

from src.research.models import (
    BacktestSummary,
    ModuleResult,
    ResearchRequest,
    ResearchState,
    TradePlan,
)

__all__ = [
    "BacktestSummary",
    "ModuleResult",
    "ResearchRequest",
    "ResearchState",
    "TradePlan",
]
```

Write `src/research/models.py`:

```python
"""Dataclass models for the research pipeline.

All types here are pure data — no I/O, no business logic. They define
the contract between modules, the synthesizer, the backtest, and the
LangGraph state. Phase 1 keeps these stable; Phase 2 adds persona
plumbing without changing the shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict


HoldingStatus = Literal["holding", "watching", "considering_buy", "considering_short"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
ReportGoal = Literal["new_entry", "hold_review", "exit_decision", "general_research"]
Direction = Literal["long", "short", "stand_aside"]
SampleQuality = Literal["strong", "moderate", "weak", "insufficient"]


@dataclass
class ResearchRequest:
    """Inputs to a single per-ticker research run.

    ``holding_status``, ``target_position_pct``, ``risk_tolerance`` and
    ``report_goal`` shape what the synthesizer writes. ``use_personas``
    is a no-op in Phase 1 (no router yet) but persisted so Phase 2 can
    pick it up. ``scanner_context`` is populated by the cron path and
    omitted for on-demand calls.
    """

    ticker: str
    holding_status: HoldingStatus
    target_position_pct: float
    risk_tolerance: RiskTolerance
    report_goal: ReportGoal
    use_personas: bool
    scanner_context: dict | None = None


@dataclass
class ModuleResult:
    """One analytical module's output.

    ``markdown`` is the human-readable section content that the synthesizer
    will reference. ``key_metrics`` is a numeric extract that the
    synthesizer can quote without re-parsing markdown. ``skipped=True``
    means the module ran cleanly but couldn't produce useful output
    (e.g., no news data) — the pipeline carries on; the section is
    omitted from the final report.
    """

    module_name: str
    persona_used: str | None
    markdown: str
    key_metrics: dict[str, float] = field(default_factory=dict)
    chart_data: dict | None = None
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class TradePlan:
    """Single-shot trade plan emitted by the synthesizer.

    ``direction="stand_aside"`` is the explicit no-trade signal; in that
    case ``entry_price``/``target_price``/``stop_price`` are all None and
    ``horizon_days``/``sizing_pct`` are 0. Synthesizer uses stand_aside
    when the bear case dominates, the user is not already holding, and
    no high-confidence long setup exists.
    """

    direction: Direction
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    horizon_days: int
    sizing_pct: float
    confidence: int  # 0-100
    rationale: str


@dataclass
class BacktestSummary:
    """Output of the detector-replay backtest.

    Replays the synthesizer's TradePlan over past dates on this ticker
    where the same detector trigger set fired. Sample size quality is
    bucketed so the consumer (HTML report / synthesizer prompt) can
    surface a caveat for small-n cases.
    """

    matches_found: int
    win_rate: float | None
    avg_pnl_pct: float | None
    max_drawdown_pct: float | None
    avg_holding_days: float | None
    sample_quality: SampleQuality
    caveat: str | None = None


class ResearchState(TypedDict, total=False):
    """LangGraph state carried through the pipeline.

    ``total=False`` so intermediate nodes can populate fields incrementally
    without TypedDict yelling about missing keys.
    """

    request: ResearchRequest
    persona_assignments: dict[str, str | list[str] | None] | None
    module_results: dict[str, ModuleResult]
    report_markdown: str | None
    strategy: TradePlan | None
    backtest_summary: BacktestSummary | None
    rendered_html: str | None
```

Also write `tests/research/__init__.py` (empty file).

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_models.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/__init__.py src/research/models.py tests/research/__init__.py tests/research/test_models.py
git commit -m "feat(research): scaffold package + data models

ResearchRequest, ModuleResult, TradePlan, BacktestSummary, ResearchState
defined as pure dataclasses. No business logic yet; subsequent commits
add SharedData, modules, synthesizer, pipeline.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: SharedData fetcher

**Files:**
- Create: `src/research/shared_data.py`
- Create: `tests/research/test_shared_data.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_shared_data.py`:

```python
"""SharedData should fetch once per (ticker, scan_date) and reuse on
subsequent calls within the same Python process. Caching is just a
module-level dict — no Redis."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from src.research.shared_data import SharedData, fetch_shared_data, _CACHE


def _clear_cache():
    _CACHE.clear()


class TestSharedDataCache:
    def setup_method(self):
        _clear_cache()

    @patch("src.research.shared_data._fetch_raw")
    def test_cache_hit_avoids_refetch(self, mock_fetch):
        mock_fetch.return_value = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={}, sector_etf_prices=[],
            spy_prices=[],
        )
        d1 = fetch_shared_data("NVDA", "2026-05-22")
        d2 = fetch_shared_data("NVDA", "2026-05-22")
        assert d1 is d2  # exact object identity → cache hit
        assert mock_fetch.call_count == 1

    @patch("src.research.shared_data._fetch_raw")
    def test_different_date_different_fetch(self, mock_fetch):
        mock_fetch.side_effect = lambda t, d: SharedData(
            ticker=t, scan_date=d,
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={}, sector_etf_prices=[],
            spy_prices=[],
        )
        fetch_shared_data("NVDA", "2026-05-22")
        fetch_shared_data("NVDA", "2026-05-23")
        assert mock_fetch.call_count == 2


class TestSharedDataShape:
    def test_dataclass_fields(self):
        d = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={"sector": "Tech"},
            sector_etf_prices=[], spy_prices=[],
        )
        assert d.ticker == "NVDA"
        assert d.company_facts == {"sector": "Tech"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_shared_data.py -v
```
Expected: ModuleNotFoundError for `src.research.shared_data`.

- [ ] **Step 3: Implement SharedData**

Write `src/research/shared_data.py`:

```python
"""Per-ticker shared data bundle.

Each pipeline run fetches once via ``fetch_shared_data(ticker, scan_date)``
and passes the result to every module so the 10 modules don't each
re-fetch the same price/financial/news lists.

Cache is a module-level dict keyed on ``(ticker, scan_date)``. Lives for
the lifetime of the Python process. Cron runs spin up fresh processes
daily so this is effectively per-run caching.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SharedData:
    """All raw data needed by the analytical modules.

    Per-ticker bundle plus benchmark prices (SPY, sector ETF) needed by
    the macro and sector modules.
    """

    ticker: str
    scan_date: str
    prices: list                          # list[Price] from v2.data.models
    financials: list                      # list[FinancialMetrics]
    insider_trades: list                  # list[InsiderTrade]
    news: list                            # list[NewsArticle]
    analyst_actions: list                 # list[AnalystAction]
    analyst_targets: Any | None           # AnalystTargets or None
    earnings_history: list                # list[EarningsRecord]
    company_facts: dict
    sector_etf_prices: list               # benchmark for sector module
    spy_prices: list                      # benchmark for macro module


_CACHE: dict[tuple[str, str], SharedData] = {}
_LOCK = threading.Lock()


# Sector → SPDR ETF mapping for the sector module benchmark. Same table
# used by src/agents/sector_agent.py; kept duplicated here to keep
# src/research/ free of cross-dependency on the legacy agent layer.
_SECTOR_ETF = {
    "Technology": "XLK", "Information Technology": "XLK",
    "Health Care": "XLV", "Healthcare": "XLV", "Pharmaceuticals": "XLV",
    "Financials": "XLF", "Banking": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
    "Communication Services": "XLC",
    "Semiconductors": "XLK",
}


def _fetch_raw(ticker: str, scan_date: str) -> SharedData:
    """Hit the v2 data layer for every field. Best-effort: each subfetch
    is wrapped so a single source failing doesn't kill the whole bundle.
    """
    from v2.data.factory import get_provider_factory

    factory = get_provider_factory()
    client = factory()

    end_dt = datetime.strptime(scan_date, "%Y-%m-%d").date()
    start_dt = (end_dt - timedelta(days=400)).isoformat()  # ~1 year + buffer

    bundle = SharedData(
        ticker=ticker, scan_date=scan_date,
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )

    try:
        bundle.prices = client.get_prices(ticker, start_dt, scan_date)
    except Exception as e:
        logger.warning("shared_data: prices(%s) failed: %s", ticker, e)
    try:
        bundle.financials = client.get_financial_metrics(ticker, scan_date)
    except Exception as e:
        logger.warning("shared_data: financials(%s) failed: %s", ticker, e)
    try:
        bundle.insider_trades = client.get_insider_trades(
            ticker, start_date=start_dt, end_date=scan_date, limit=200,
        )
    except Exception as e:
        logger.warning("shared_data: insider_trades(%s) failed: %s", ticker, e)
    try:
        bundle.news = client.get_company_news(
            ticker, start_date=start_dt, end_date=scan_date, limit=100,
        )
    except Exception as e:
        logger.warning("shared_data: news(%s) failed: %s", ticker, e)
    if hasattr(client, "get_analyst_actions"):
        try:
            bundle.analyst_actions = client.get_analyst_actions(
                ticker, end_date=scan_date, start_date=start_dt, limit=200,
            )
        except Exception as e:
            logger.warning("shared_data: analyst_actions(%s) failed: %s", ticker, e)
    if hasattr(client, "get_analyst_targets"):
        try:
            bundle.analyst_targets = client.get_analyst_targets(ticker, asof_date=scan_date)
        except Exception as e:
            logger.warning("shared_data: analyst_targets(%s) failed: %s", ticker, e)
    try:
        bundle.earnings_history = client.get_earnings_history(ticker, limit=12)
    except Exception as e:
        logger.warning("shared_data: earnings_history(%s) failed: %s", ticker, e)
    try:
        bundle.company_facts = client.get_company_facts(ticker) or {}
    except Exception as e:
        logger.warning("shared_data: company_facts(%s) failed: %s", ticker, e)

    # Benchmarks
    sector = (bundle.company_facts.get("sector") or
              bundle.company_facts.get("industry") or "")
    etf = _SECTOR_ETF.get(sector)
    if etf:
        try:
            bundle.sector_etf_prices = client.get_prices(etf, start_dt, scan_date)
        except Exception as e:
            logger.warning("shared_data: sector_etf(%s)=%s failed: %s", ticker, etf, e)
    try:
        bundle.spy_prices = client.get_prices("SPY", start_dt, scan_date)
    except Exception as e:
        logger.warning("shared_data: spy_prices failed: %s", e)

    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    return bundle


def fetch_shared_data(ticker: str, scan_date: str) -> SharedData:
    """Cached fetch — returns the same SharedData instance for repeated
    calls with the same (ticker, scan_date) within a single process.
    """
    key = (ticker, scan_date)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    bundle = _fetch_raw(ticker, scan_date)
    with _LOCK:
        _CACHE[key] = bundle
    return bundle
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_shared_data.py -v
```
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/shared_data.py tests/research/test_shared_data.py
git commit -m "feat(research): SharedData fetcher with per-process cache

One fetch per (ticker, scan_date); 10 modules reuse the bundle. Each
subfetch wrapped so a single source failing degrades gracefully rather
than killing the run. Sector-ETF lookup table duplicated here to keep
src/research/ independent of src/agents/sector_agent.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: LLM helper

**Files:**
- Create: `src/research/llm.py`
- Create: `tests/research/test_llm.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_llm.py`:

```python
"""call_research_llm should call the underlying LLM with structured
output, retry up to 3x on parse failures, and return the pydantic
model. Default factory fires on terminal failure."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from src.research.llm import call_research_llm


class _DummyOut(BaseModel):
    text: str


class TestCallResearchLLM:
    @patch("src.research.llm.get_model")
    def test_happy_path_returns_pydantic(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value.invoke.return_value = _DummyOut(text="hi")
        mock_get_model.return_value = mock_model

        out = call_research_llm("prompt text", _DummyOut)
        assert isinstance(out, _DummyOut)
        assert out.text == "hi"

    @patch("src.research.llm.get_model")
    def test_default_factory_on_terminal_failure(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value.invoke.side_effect = ValueError("boom")
        mock_get_model.return_value = mock_model

        out = call_research_llm(
            "prompt", _DummyOut,
            default_factory=lambda: _DummyOut(text="fallback"),
        )
        assert out.text == "fallback"

    @patch("src.research.llm.get_model")
    def test_no_default_factory_raises(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value.invoke.side_effect = ValueError("boom")
        mock_get_model.return_value = mock_model

        with __import__("pytest").raises(ValueError):
            call_research_llm("prompt", _DummyOut)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_llm.py -v
```
Expected: ModuleNotFoundError for `src.research.llm`.

- [ ] **Step 3: Implement LLM helper**

Write `src/research/llm.py`:

```python
"""Small LLM-call helper for the research pipeline.

Why a separate helper instead of reusing src/utils/llm.py:call_llm?
The legacy helper extracts model config from AgentState (the LangGraph
state used by src/agents/). The research pipeline has its own state
shape and doesn't need that coupling. This helper takes raw prompts +
pydantic models and uses the DeepSeek default that matches the
production cron's cost target (~$0.0005/call).

Override via env vars RESEARCH_MODEL_NAME / RESEARCH_MODEL_PROVIDER for
local experimentation.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, TypeVar

from pydantic import BaseModel
from src.llm.models import get_model

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_PROVIDER = "DeepSeek"


def call_research_llm(
    prompt,
    pydantic_model: type[_T],
    *,
    max_retries: int = 3,
    default_factory: Callable[[], _T] | None = None,
) -> _T:
    """Call the LLM with structured output. Retry on parse/transient
    errors up to ``max_retries``. If all retries fail and
    ``default_factory`` is provided, return its result; otherwise
    re-raise the last exception.

    ``prompt`` can be anything the LangChain ``invoke`` accepts — a
    string, a ChatPromptTemplate, a message list. Callers usually
    pre-format into a string for simplicity.
    """
    model_name = os.environ.get("RESEARCH_MODEL_NAME", _DEFAULT_MODEL)
    model_provider = os.environ.get("RESEARCH_MODEL_PROVIDER", _DEFAULT_PROVIDER)

    llm = get_model(model_name, model_provider)
    structured = llm.with_structured_output(pydantic_model, method="json_mode")

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return structured.invoke(prompt)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "call_research_llm attempt %d/%d failed: %s",
                attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))

    if default_factory is not None:
        logger.warning("call_research_llm exhausted retries; using default_factory")
        return default_factory()
    assert last_exc is not None
    raise last_exc
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_llm.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/llm.py tests/research/test_llm.py
git commit -m "feat(research): call_research_llm helper with retry + default factory

Wraps get_model() with structured-output, 3-retry loop, and optional
fallback factory. Defaults to deepseek-chat to match production cost
target; overridable via RESEARCH_MODEL_NAME env var for experimentation.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: AnalysisModule ABC

**Files:**
- Create: `src/research/modules/__init__.py`
- Create: `src/research/modules/base.py`
- Create: `tests/research/test_modules_base.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_modules_base.py`:

```python
"""AnalysisModule contract: subclasses must declare name + supports_personas
and implement run(). Calling the ABC directly must raise."""

from __future__ import annotations

import pytest
from src.research.modules.base import AnalysisModule
from src.research.models import ResearchRequest, ModuleResult
from src.research.shared_data import SharedData


def _fake_request() -> ResearchRequest:
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=None,
    )


def _fake_shared() -> SharedData:
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={}, sector_etf_prices=[],
        spy_prices=[],
    )


class TestAnalysisModuleABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AnalysisModule()  # type: ignore[abstract]

    def test_concrete_subclass_runs(self):
        class Dummy(AnalysisModule):
            name = "dummy"
            supports_personas = []

            def run(self, request, persona, shared_data):
                return ModuleResult(
                    module_name=self.name,
                    persona_used=persona,
                    markdown="ok",
                )

        m = Dummy()
        out = m.run(_fake_request(), None, _fake_shared())
        assert out.module_name == "dummy"
        assert out.persona_used is None
        assert out.markdown == "ok"

    def test_concrete_subclass_rejects_unsupported_persona(self):
        class Dummy(AnalysisModule):
            name = "dummy"
            supports_personas = ["buffett"]

            def run(self, request, persona, shared_data):
                return ModuleResult(module_name=self.name,
                                    persona_used=persona, markdown="ok")

        m = Dummy()
        # Validation helper provided by the base class — modules call it
        # in their own run() to coerce bad persona to None.
        assert m._coerce_persona("buffett") == "buffett"
        assert m._coerce_persona("wood") is None  # not in supports_personas
        assert m._coerce_persona(None) is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_modules_base.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the ABC**

Write `src/research/modules/__init__.py`:

```python
"""Analytical modules for the research pipeline.

Each module is a focused unit of analysis: macro context, sector
strength, fundamentals quality, etc. Phase 1 ships 8 LLM-driven
modules + 1 deterministic backtest module. Phase 2 adds persona
variants. ``ALL_MODULES`` is the registry the pipeline orchestrator
iterates over.
"""

from src.research.modules.base import AnalysisModule

# ALL_MODULES populated by subsequent commits; intentionally empty here
# so importing the package doesn't try to load modules that don't exist
# yet during Task 4. Each module file adds itself in subsequent tasks.
ALL_MODULES: list[type[AnalysisModule]] = []

__all__ = ["AnalysisModule", "ALL_MODULES"]
```

Write `src/research/modules/base.py`:

```python
"""Base class for analytical modules.

Every module exposes:
  * ``name`` (str) — stable identifier used in logs and module_results
  * ``supports_personas`` (list[str]) — empty = objective only; non-empty
    enumerates which persona prompts the module understands
  * ``run(request, persona, shared_data)`` — returns a ModuleResult

The persona-router (Phase 2) writes ``persona_assignments[name]`` from
the supports_personas list. In Phase 1, persona is always None.

Modules MUST NOT raise — on missing/insufficient data, return a
ModuleResult with ``skipped=True`` and a ``skip_reason``. The pipeline
orchestrator surfaces skipped modules in the report but does not abort.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.research.models import ModuleResult, ResearchRequest
from src.research.shared_data import SharedData


class AnalysisModule(ABC):
    """Abstract base for one analytical section."""

    name: str = "base"
    supports_personas: list[str] = []  # empty = objective only

    @abstractmethod
    def run(
        self,
        request: ResearchRequest,
        persona: str | None,
        shared_data: SharedData,
    ) -> ModuleResult:
        """Produce one ModuleResult. Must not raise; on insufficient data
        return ModuleResult(..., skipped=True, skip_reason='...').
        """
        ...

    def _coerce_persona(self, persona: str | None) -> str | None:
        """Validate persona is in supports_personas; coerce to None
        otherwise. Modules call this at the top of run() to defend
        against a misconfigured router."""
        if persona is None:
            return None
        if persona in self.supports_personas:
            return persona
        return None
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_modules_base.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/__init__.py src/research/modules/base.py tests/research/test_modules_base.py
git commit -m "feat(research): AnalysisModule ABC + module registry

Modules declare name + supports_personas (empty = objective only) and
implement run(request, persona, shared_data) -> ModuleResult. _coerce_persona
helper defends against router misconfiguration. ALL_MODULES list is
the registry the orchestrator iterates; populated by subsequent module
commits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Macro module

**Files:**
- Create: `src/research/modules/macro.py`
- Create: `tests/research/test_module_macro.py`
- Modify: `src/research/modules/__init__.py` (append to ALL_MODULES)

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_macro.py`:

```python
"""Macro module: read SPY trailing return + VIX from SharedData,
compute regime classification, call LLM for narrative. Returns a
ModuleResult with markdown + key_metrics."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from src.research.modules.macro import MacroModule
from src.research.models import ResearchRequest, ModuleResult
from src.research.shared_data import SharedData


def _make_request():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=None,
    )


def _make_shared(spy_returns_pct: float = 0.05):
    """Build SharedData with 21 SPY closes producing a known trailing 20d return."""
    from types import SimpleNamespace
    base = 400.0
    end = base * (1 + spy_returns_pct)
    closes = [base + (end - base) * (i / 20) for i in range(21)]
    spy_prices = [
        SimpleNamespace(time=f"2026-04-{i + 1:02d}", close=c, adjusted_close=c)
        for i, c in enumerate(closes)
    ]
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={"sector": "Technology"},
        sector_etf_prices=[], spy_prices=spy_prices,
    )


class TestMacroModule:
    def test_name_and_no_personas(self):
        m = MacroModule()
        assert m.name == "macro"
        assert m.supports_personas == []

    @patch("src.research.modules.macro.call_research_llm")
    def test_run_returns_module_result(self, mock_llm):
        from src.research.modules.macro import _MacroNarrative
        mock_llm.return_value = _MacroNarrative(narrative="SPY up 5%, regime up.")

        m = MacroModule()
        out = m.run(_make_request(), None, _make_shared(spy_returns_pct=0.05))
        assert isinstance(out, ModuleResult)
        assert out.module_name == "macro"
        assert out.markdown
        assert "spy_return_20d" in out.key_metrics
        assert out.key_metrics["spy_return_20d"] == round(0.05, 4)
        assert out.skipped is False

    def test_skipped_when_no_spy_data(self):
        shared = _make_shared()
        shared.spy_prices = []
        m = MacroModule()
        out = m.run(_make_request(), None, shared)
        assert out.skipped is True
        assert "SPY" in (out.skip_reason or "")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_macro.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the module**

Write `src/research/modules/macro.py`:

```python
"""Macro module — SPY trailing return + regime label as narrative.

Phase 1 is objective-only (no Druckenmiller persona variant). Reads
SharedData.spy_prices (already fetched once at pipeline start), computes
trailing 20d return + regime label deterministically, and asks the LLM
for a 2-3 sentence narrative anchored on those numbers.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _MacroNarrative(BaseModel):
    narrative: str = Field(
        description="2-3 sentences describing the macro regime and its "
                    "relevance to this ticker. Reference the numbers."
    )


def _compute_macro(shared: SharedData) -> dict[str, float] | None:
    bars = sorted(shared.spy_prices, key=lambda p: p.time[:10])
    if len(bars) < 21:
        return None
    closes = [float(getattr(b, "adjusted_close", None) or b.close) for b in bars[-21:]]
    ret_20d = (closes[-1] / closes[0]) - 1.0
    regime = "up" if ret_20d > 0.01 else ("down" if ret_20d < -0.01 else "chop")
    return {
        "spy_return_20d": round(ret_20d, 4),
        "regime_code": 1.0 if regime == "up" else (-1.0 if regime == "down" else 0.0),
    }


class MacroModule(AnalysisModule):
    name = "macro"
    supports_personas: list[str] = []  # Phase 2 may add ["druckenmiller"]

    def run(
        self,
        request: ResearchRequest,
        persona: str | None,
        shared_data: SharedData,
    ) -> ModuleResult:
        persona = self._coerce_persona(persona)  # None always in Phase 1

        metrics = _compute_macro(shared_data)
        if metrics is None:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="SPY price history insufficient",
            )

        regime = {1.0: "up", -1.0: "down", 0.0: "chop"}[metrics["regime_code"]]
        ret_pct = metrics["spy_return_20d"] * 100

        prompt = (
            f"Macro regime snapshot for {shared_data.scan_date}:\n"
            f"  SPY trailing 20-day return: {ret_pct:+.2f}%\n"
            f"  Regime label: {regime}\n"
            f"\nTicker under analysis: {request.ticker}.\n"
            f"Holding status: {request.holding_status}.\n"
            f"\nWrite a 2-3 sentence objective summary of the macro context\n"
            f"and its implications for a position in {request.ticker}. Cite\n"
            f"the numbers above. Do not predict; describe."
        )

        try:
            narrative = call_research_llm(
                prompt, _MacroNarrative,
                default_factory=lambda: _MacroNarrative(
                    narrative=f"SPY {ret_pct:+.2f}% over 20d ({regime} regime)."
                ),
            )
        except Exception as e:
            logger.warning("macro module LLM failed: %s", e)
            narrative = _MacroNarrative(
                narrative=f"SPY {ret_pct:+.2f}% over 20d ({regime} regime).",
            )

        return ModuleResult(
            module_name=self.name,
            persona_used=None,
            markdown=narrative.narrative,
            key_metrics=metrics,
        )
```

Modify `src/research/modules/__init__.py` to register:

```python
"""Analytical modules for the research pipeline.

Each module is a focused unit of analysis: macro context, sector
strength, fundamentals quality, etc. Phase 1 ships 8 LLM-driven
modules + 1 deterministic backtest module. Phase 2 adds persona
variants. ``ALL_MODULES`` is the registry the pipeline orchestrator
iterates over.
"""

from src.research.modules.base import AnalysisModule
from src.research.modules.macro import MacroModule

ALL_MODULES: list[type[AnalysisModule]] = [
    MacroModule,
]

__all__ = ["AnalysisModule", "ALL_MODULES", "MacroModule"]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_macro.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/macro.py src/research/modules/__init__.py tests/research/test_module_macro.py
git commit -m "feat(research): macro module (objective)

Reads SPY trailing 20d from SharedData, classifies regime, asks LLM
for a 2-3 sentence summary anchored on the numbers. Skipped when SPY
history insufficient. Registered in ALL_MODULES.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Sector module

**Files:**
- Create: `src/research/modules/sector.py`
- Create: `tests/research/test_module_sector.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_sector.py`:

```python
"""Sector module: read ticker prices + sector ETF prices from SharedData,
compute relative strength (RS = ticker_20d_return - etf_20d_return)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.sector import SectorModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _bars(start: float, ret: float, n: int = 21):
    end = start * (1 + ret)
    closes = [start + (end - start) * (i / (n - 1)) for i in range(n)]
    return [
        SimpleNamespace(time=f"2026-04-{i + 1:02d}", close=c, adjusted_close=c)
        for i, c in enumerate(closes)
    ]


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=None,
    )


def _shared(ticker_ret=0.10, etf_ret=0.04):
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=_bars(100.0, ticker_ret),
        financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None,
        earnings_history=[],
        company_facts={"sector": "Technology"},
        sector_etf_prices=_bars(200.0, etf_ret),
        spy_prices=[],
    )


class TestSectorModule:
    def test_name(self):
        assert SectorModule().name == "sector"

    @patch("src.research.modules.sector.call_research_llm")
    def test_relative_strength_positive(self, mock_llm):
        from src.research.modules.sector import _SectorNarrative
        mock_llm.return_value = _SectorNarrative(narrative="NVDA outperforms XLK.")

        out = SectorModule().run(_req(), None, _shared(ticker_ret=0.10, etf_ret=0.04))
        assert out.skipped is False
        assert out.key_metrics["relative_strength_pp"] == round((0.10 - 0.04) * 100, 2)

    def test_skipped_when_no_etf_data(self):
        shared = _shared()
        shared.sector_etf_prices = []
        out = SectorModule().run(_req(), None, shared)
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_sector.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/sector.py`:

```python
"""Sector module — relative strength vs sector ETF."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _SectorNarrative(BaseModel):
    narrative: str = Field(
        description="2-3 sentences on the ticker's sector and relative strength."
    )


def _ret_20d(bars) -> float | None:
    bars = sorted(bars, key=lambda b: b.time[:10])
    if len(bars) < 21:
        return None
    closes = [float(getattr(b, "adjusted_close", None) or b.close) for b in bars[-21:]]
    return (closes[-1] / closes[0]) - 1.0


class SectorModule(AnalysisModule):
    name = "sector"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        ticker_ret = _ret_20d(shared_data.prices)
        etf_ret = _ret_20d(shared_data.sector_etf_prices)
        if ticker_ret is None or etf_ret is None:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason="Insufficient ticker or sector-ETF price history",
            )

        rs_pp = round((ticker_ret - etf_ret) * 100, 2)
        sector = shared_data.company_facts.get("sector") or "Unknown"
        prompt = (
            f"Sector context for {request.ticker} (sector: {sector}):\n"
            f"  Ticker 20d return: {ticker_ret * 100:+.2f}%\n"
            f"  Sector ETF 20d return: {etf_ret * 100:+.2f}%\n"
            f"  Relative strength: {rs_pp:+.2f}pp\n"
            f"\nWrite 2-3 sentences summarizing whether the ticker is\n"
            f"leading, lagging, or in line with its sector. Describe,\n"
            f"do not predict."
        )
        narrative = call_research_llm(
            prompt, _SectorNarrative,
            default_factory=lambda: _SectorNarrative(
                narrative=f"{request.ticker} {rs_pp:+.2f}pp vs sector over 20d."
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative,
            key_metrics={
                "ticker_return_20d": round(ticker_ret, 4),
                "etf_return_20d": round(etf_ret, 4),
                "relative_strength_pp": rs_pp,
            },
        )
```

Modify `src/research/modules/__init__.py` — add `from src.research.modules.sector import SectorModule` and append `SectorModule` to ALL_MODULES.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_sector.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/sector.py src/research/modules/__init__.py tests/research/test_module_sector.py
git commit -m "feat(research): sector module (objective)

20d ticker vs sector-ETF relative strength, LLM summarizes leader/
lagger/in-line. Skipped when either price series insufficient.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Fundamentals module (objective)

**Files:**
- Create: `src/research/modules/fundamentals.py`
- Create: `tests/research/test_module_fundamentals.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_fundamentals.py`:

```python
"""Fundamentals module: extract revenue_growth / margins / ROIC etc.
from SharedData.financials, ask LLM for moat/quality narrative."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.fundamentals import FundamentalsModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _fundamentals():
    return [SimpleNamespace(
        report_period="2025-Q4",
        revenue=50_000_000_000, revenue_growth=0.38,
        gross_margin=0.74, operating_margin=0.55,
        net_margin=0.45, return_on_invested_capital=0.42,
        free_cash_flow_margin=0.40, debt_to_equity=0.18,
    )]


class TestFundamentalsModule:
    def test_name(self):
        m = FundamentalsModule()
        assert m.name == "fundamentals"

    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_emits_key_metrics(self, mock_llm):
        from src.research.modules.fundamentals import _FundamentalsNarrative
        mock_llm.return_value = _FundamentalsNarrative(
            narrative="Strong margins, high ROIC, growing 38%.",
        )
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        out = FundamentalsModule().run(_req(), None, shared)
        assert out.skipped is False
        assert out.key_metrics["revenue_growth"] == 0.38
        assert out.key_metrics["roic"] == 0.42

    def test_skipped_when_no_financials(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = FundamentalsModule().run(_req(), None, shared)
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_fundamentals.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/fundamentals.py`:

```python
"""Fundamentals module — moat / margins / capital efficiency."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _FundamentalsNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences on revenue growth, margin profile, "
                    "capital efficiency, and apparent moat."
    )


def _safe(getter, default=None):
    try:
        v = getter()
        return v if v is not None else default
    except (AttributeError, IndexError, TypeError):
        return default


class FundamentalsModule(AnalysisModule):
    name = "fundamentals"
    # Phase 2 will add ["buffett", "munger", "fisher"]
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        if not shared_data.financials:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="No financial_metrics available",
            )
        latest = shared_data.financials[0]

        metrics = {
            "revenue_growth": _safe(lambda: float(latest.revenue_growth), 0.0) or 0.0,
            "gross_margin": _safe(lambda: float(latest.gross_margin), 0.0) or 0.0,
            "operating_margin": _safe(lambda: float(latest.operating_margin), 0.0) or 0.0,
            "net_margin": _safe(lambda: float(latest.net_margin), 0.0) or 0.0,
            "roic": _safe(lambda: float(latest.return_on_invested_capital), 0.0) or 0.0,
            "fcf_margin": _safe(lambda: float(latest.free_cash_flow_margin), 0.0) or 0.0,
            "debt_to_equity": _safe(lambda: float(latest.debt_to_equity), 0.0) or 0.0,
        }

        prompt = (
            f"Company fundamentals for {request.ticker} "
            f"(latest period: {_safe(lambda: latest.report_period, 'recent')}):\n"
            f"  Revenue growth (YoY): {metrics['revenue_growth'] * 100:+.1f}%\n"
            f"  Gross margin: {metrics['gross_margin'] * 100:.1f}%\n"
            f"  Operating margin: {metrics['operating_margin'] * 100:.1f}%\n"
            f"  Net margin: {metrics['net_margin'] * 100:.1f}%\n"
            f"  ROIC: {metrics['roic'] * 100:.1f}%\n"
            f"  FCF margin: {metrics['fcf_margin'] * 100:.1f}%\n"
            f"  Debt/Equity: {metrics['debt_to_equity']:.2f}\n"
            f"\nWrite 3-5 sentences objectively describing the company's\n"
            f"profitability, capital efficiency, and apparent moat strength.\n"
            f"Anchor every claim on a number above. Do not predict price."
        )
        narrative = call_research_llm(
            prompt, _FundamentalsNarrative,
            default_factory=lambda: _FundamentalsNarrative(
                narrative=(
                    f"Revenue growth {metrics['revenue_growth'] * 100:+.1f}%, "
                    f"net margin {metrics['net_margin'] * 100:.1f}%, "
                    f"ROIC {metrics['roic'] * 100:.1f}%."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

Modify `src/research/modules/__init__.py` — append FundamentalsModule.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_fundamentals.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/fundamentals.py src/research/modules/__init__.py tests/research/test_module_fundamentals.py
git commit -m "feat(research): fundamentals module (objective)

Extracts revenue growth + margins + ROIC + FCF + leverage from latest
financial_metrics, asks LLM for 3-5 sentence moat/quality summary.
Skipped when no financial_metrics data.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Financials module (objective)

**Files:**
- Create: `src/research/modules/financials.py`
- Create: `tests/research/test_module_financials.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_financials.py`:

```python
"""Financials module: quarter-over-quarter trend summary from the last
N financial_metrics rows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.financials import FinancialsModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _series():
    return [
        SimpleNamespace(
            report_period=f"2025-Q{q}",
            revenue=40e9 + q * 1e9,
            net_income=15e9 + q * 0.3e9,
            free_cash_flow=12e9 + q * 0.25e9,
        )
        for q in range(4, 0, -1)
    ]


class TestFinancialsModule:
    def test_name(self):
        assert FinancialsModule().name == "financials"

    @patch("src.research.modules.financials.call_research_llm")
    def test_run_with_4q_data(self, mock_llm):
        from src.research.modules.financials import _FinancialsNarrative
        mock_llm.return_value = _FinancialsNarrative(narrative="Revenue grew QoQ.")
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_series(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        out = FinancialsModule().run(_req(), None, shared)
        assert out.skipped is False
        assert "revenue_latest" in out.key_metrics

    def test_skipped_when_empty(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = FinancialsModule().run(_req(), None, shared)
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_financials.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/financials.py`:

```python
"""Financials module — quarter-over-quarter trend in income / cash flow."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _FinancialsNarrative(BaseModel):
    narrative: str = Field(
        description="3-4 sentences on QoQ trend in revenue, net income, and FCF."
    )


def _f(getter, default=0.0):
    try:
        v = getter()
        return float(v) if v is not None else default
    except (AttributeError, TypeError, ValueError):
        return default


class FinancialsModule(AnalysisModule):
    name = "financials"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        if not shared_data.financials:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="No financial_metrics history",
            )

        series = shared_data.financials[:4]  # most recent 4 quarters
        rev = [_f(lambda x=row: x.revenue) for row in series]
        ni = [_f(lambda x=row: x.net_income) for row in series]
        fcf = [_f(lambda x=row: x.free_cash_flow) for row in series]

        metrics = {
            "revenue_latest": rev[0] if rev else 0.0,
            "net_income_latest": ni[0] if ni else 0.0,
            "fcf_latest": fcf[0] if fcf else 0.0,
            "n_quarters": float(len(series)),
        }
        if len(series) >= 4 and rev[3] > 0:
            metrics["revenue_yoy_growth"] = round((rev[0] / rev[3]) - 1.0, 4)
        if len(series) >= 4 and ni[3] != 0:
            metrics["net_income_yoy_growth"] = round((ni[0] / ni[3]) - 1.0, 4)

        rows_md = "\n".join(
            f"  {row.report_period}: revenue ${rev[i] / 1e9:.2f}B, "
            f"NI ${ni[i] / 1e9:.2f}B, FCF ${fcf[i] / 1e9:.2f}B"
            for i, row in enumerate(series)
        )
        prompt = (
            f"Recent quarterly financials for {request.ticker}:\n"
            f"{rows_md}\n"
            f"\nWrite 3-4 sentences objectively describing the QoQ trend\n"
            f"in revenue, net income, and free cash flow. Note any\n"
            f"acceleration or deceleration. Anchor every claim on a number\n"
            f"above. Do not predict."
        )
        narrative = call_research_llm(
            prompt, _FinancialsNarrative,
            default_factory=lambda: _FinancialsNarrative(
                narrative=(
                    f"Latest revenue ${rev[0] / 1e9:.2f}B, "
                    f"net income ${ni[0] / 1e9:.2f}B, FCF ${fcf[0] / 1e9:.2f}B."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

Modify `src/research/modules/__init__.py` — append FinancialsModule.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_financials.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/financials.py src/research/modules/__init__.py tests/research/test_module_financials.py
git commit -m "feat(research): financials module (objective)

Last 4 quarters of revenue / NI / FCF; LLM summarizes QoQ + YoY trend.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Valuation module (objective)

**Files:**
- Create: `src/research/modules/valuation.py`
- Create: `tests/research/test_module_valuation.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_valuation.py`:

```python
"""Valuation module: compute simple DCF + relative multiples;
emit fair_value_low / fair_value_high in key_metrics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.valuation import ValuationModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _shared(price=145.0, eps_ttm=4.0, fcf=12e9, shares=24e9):
    fin = SimpleNamespace(
        earnings_per_share=eps_ttm, free_cash_flow=fcf,
        revenue=50e9, net_income=eps_ttm * shares,
    )
    bars = [SimpleNamespace(time="2026-05-22", close=price, adjusted_close=price)]
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=bars, financials=[fin],
        insider_trades=[], news=[], analyst_actions=[],
        analyst_targets=None, earnings_history=[],
        company_facts={"market_cap": price * shares, "shares_outstanding": shares},
        sector_etf_prices=[], spy_prices=[],
    )


class TestValuationModule:
    def test_name(self):
        assert ValuationModule().name == "valuation"

    @patch("src.research.modules.valuation.call_research_llm")
    def test_outputs_fair_value_range(self, mock_llm):
        from src.research.modules.valuation import _ValuationNarrative
        mock_llm.return_value = _ValuationNarrative(narrative="Fairly valued.")
        out = ValuationModule().run(_req(), None, _shared())
        assert out.skipped is False
        assert "fair_value_low" in out.key_metrics
        assert "fair_value_high" in out.key_metrics
        assert out.key_metrics["fair_value_low"] <= out.key_metrics["fair_value_high"]

    def test_skipped_when_no_eps(self):
        shared = _shared(eps_ttm=0.0)
        # No financials at all
        shared.financials = []
        out = ValuationModule().run(_req(), None, shared)
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_valuation.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/valuation.py`:

```python
"""Valuation module — simple DCF + multiple-based fair value range."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _ValuationNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences on fair value range vs current price."
    )


def _current_price(shared: SharedData) -> float | None:
    if not shared.prices:
        return None
    bars = sorted(shared.prices, key=lambda b: b.time[:10])
    last = bars[-1]
    return float(getattr(last, "adjusted_close", None) or last.close)


def _fair_value_range(
    eps_ttm: float, fcf: float, shares: float,
    growth_rate: float = 0.10, discount_rate: float = 0.10,
) -> tuple[float, float] | None:
    """Two anchor methods:
      * PE multiple: low = eps * 15, high = eps * 25 (conservative growth band)
      * DCF (perpetuity): FCF * (1 + g) / (r - g) / shares — simplified
        Gordon growth; low = with g - 2pp, high = with g + 2pp.
    Returns (low, high) intersected/blended.
    """
    pe_low = eps_ttm * 15 if eps_ttm > 0 else None
    pe_high = eps_ttm * 25 if eps_ttm > 0 else None

    dcf_low = dcf_high = None
    if fcf > 0 and shares > 0:
        g_lo = max(growth_rate - 0.02, 0.0)
        g_hi = min(growth_rate + 0.02, discount_rate - 0.005)
        if discount_rate - g_lo > 0:
            dcf_low = (fcf * (1 + g_lo) / (discount_rate - g_lo)) / shares
        if discount_rate - g_hi > 0:
            dcf_high = (fcf * (1 + g_hi) / (discount_rate - g_hi)) / shares

    candidates_low = [v for v in (pe_low, dcf_low) if v is not None and v > 0]
    candidates_high = [v for v in (pe_high, dcf_high) if v is not None and v > 0]
    if not candidates_low or not candidates_high:
        return None
    return (min(candidates_low), max(candidates_high))


class ValuationModule(AnalysisModule):
    name = "valuation"
    # Phase 2 will add ["buffett", "graham", "munger", "fisher"]
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        if not shared_data.financials:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="No financials for valuation",
            )

        latest = shared_data.financials[0]
        eps = float(getattr(latest, "earnings_per_share", 0.0) or 0.0)
        fcf = float(getattr(latest, "free_cash_flow", 0.0) or 0.0)
        shares = float(shared_data.company_facts.get("shares_outstanding") or 0.0)
        if eps <= 0 and fcf <= 0:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="Neither EPS nor FCF positive",
            )

        rng = _fair_value_range(eps, fcf, shares or 1.0)
        price = _current_price(shared_data) or 0.0
        if rng is None:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="Fair value range not computable",
            )

        metrics = {
            "current_price": round(price, 2),
            "fair_value_low": round(rng[0], 2),
            "fair_value_high": round(rng[1], 2),
            "eps_ttm": round(eps, 2),
        }
        prompt = (
            f"Valuation snapshot for {request.ticker}:\n"
            f"  Current price: ${price:.2f}\n"
            f"  Fair value range: ${rng[0]:.2f} – ${rng[1]:.2f}\n"
            f"  EPS (TTM): ${eps:.2f}\n"
            f"\nWrite 3-5 sentences objectively comparing the current price\n"
            f"to the fair value range. Identify whether the stock looks\n"
            f"cheap, fair, or stretched, and by how much. Do not predict\n"
            f"future price; describe the gap."
        )
        narrative = call_research_llm(
            prompt, _ValuationNarrative,
            default_factory=lambda: _ValuationNarrative(
                narrative=(
                    f"Price ${price:.2f}; fair value range "
                    f"${rng[0]:.2f}-${rng[1]:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

Modify `src/research/modules/__init__.py` — append ValuationModule.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_valuation.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/valuation.py src/research/modules/__init__.py tests/research/test_module_valuation.py
git commit -m "feat(research): valuation module (objective)

PE-multiple and DCF perpetuity anchor methods, blended into a fair-
value range. LLM compares current price to range and describes the
gap. Skipped when neither EPS nor FCF is positive.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Technical module (objective)

**Files:**
- Create: `src/research/modules/technical.py`
- Create: `tests/research/test_module_technical.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_technical.py`:

```python
"""Technical module: compute RSI(14), 50d/200d SMA, recent support/resistance
from SharedData.prices."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.technical import TechnicalModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _bars(closes):
    return [
        SimpleNamespace(
            time=f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
            close=c, adjusted_close=c,
            high=c * 1.01, low=c * 0.99, open=c, volume=1_000_000,
        )
        for i, c in enumerate(closes)
    ]


class TestTechnicalModule:
    def test_name(self):
        assert TechnicalModule().name == "technical"

    @patch("src.research.modules.technical.call_research_llm")
    def test_run_with_long_history(self, mock_llm):
        from src.research.modules.technical import _TechnicalNarrative
        mock_llm.return_value = _TechnicalNarrative(narrative="Above 50d SMA.")
        closes = [100 + i * 0.5 for i in range(250)]
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=_bars(closes), financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = TechnicalModule().run(_req(), None, shared)
        assert out.skipped is False
        assert "rsi_14" in out.key_metrics
        assert "sma_50" in out.key_metrics
        assert "support" in out.key_metrics

    def test_skipped_when_short_history(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=_bars([100, 101, 102]),
            financials=[], insider_trades=[], news=[],
            analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = TechnicalModule().run(_req(), None, shared)
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_technical.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/technical.py`:

```python
"""Technical module — RSI(14), 50d/200d SMA, recent support/resistance."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _TechnicalNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences on trend, momentum, and proximity to S/R."
    )


def _rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, 15)]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


class TechnicalModule(AnalysisModule):
    name = "technical"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        bars = sorted(shared_data.prices, key=lambda b: b.time[:10])
        if len(bars) < 60:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason=f"Need ≥60 bars for technical analysis, got {len(bars)}",
            )

        closes = [float(getattr(b, "adjusted_close", None) or b.close) for b in bars]
        price = closes[-1]

        sma_50 = round(sum(closes[-50:]) / 50, 2)
        sma_200 = round(sum(closes[-200:]) / 200, 2) if len(closes) >= 200 else None
        rsi = _rsi14(closes)

        # Support / resistance: 60-day extremes
        recent = closes[-60:]
        support = round(min(recent), 2)
        resistance = round(max(recent), 2)

        metrics = {
            "current_price": round(price, 2),
            "sma_50": sma_50,
            "rsi_14": rsi if rsi is not None else 0.0,
            "support": support,
            "resistance": resistance,
        }
        if sma_200 is not None:
            metrics["sma_200"] = sma_200

        trend_bits = []
        if price > sma_50:
            trend_bits.append(f"above 50d SMA ({sma_50:.2f})")
        else:
            trend_bits.append(f"below 50d SMA ({sma_50:.2f})")
        if sma_200 is not None:
            trend_bits.append(f"vs 200d SMA ${sma_200:.2f}")

        prompt = (
            f"Technical snapshot for {request.ticker}:\n"
            f"  Price: ${price:.2f}\n"
            f"  RSI(14): {rsi}\n"
            f"  50d SMA: ${sma_50:.2f}\n"
            + (f"  200d SMA: ${sma_200:.2f}\n" if sma_200 is not None else "")
            + f"  60d support / resistance: ${support:.2f} / ${resistance:.2f}\n"
            f"\nWrite 3-5 sentences objectively describing the trend\n"
            f"({', '.join(trend_bits)}), momentum (RSI), and proximity to\n"
            f"support/resistance. Anchor on numbers. Do not predict."
        )
        narrative = call_research_llm(
            prompt, _TechnicalNarrative,
            default_factory=lambda: _TechnicalNarrative(
                narrative=(
                    f"Price ${price:.2f}, RSI {rsi}, "
                    f"S/R ${support:.2f}/${resistance:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

Modify `src/research/modules/__init__.py` — append TechnicalModule.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_technical.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/technical.py src/research/modules/__init__.py tests/research/test_module_technical.py
git commit -m "feat(research): technical module (objective)

RSI(14), 50d/200d SMA, 60d support/resistance. LLM summarizes trend +
momentum + proximity to S/R. Skipped when <60 bars available.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Sentiment module (objective)

**Files:**
- Create: `src/research/modules/sentiment.py`
- Create: `tests/research/test_module_sentiment.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_sentiment.py`:

```python
"""Sentiment module: aggregate insider flow + recent news sentiment +
analyst-action net upgrades into a single narrative."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.sentiment import SentimentModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _shared():
    insider_trades = [
        SimpleNamespace(
            transaction_date="2026-05-15", name="CEO",
            transaction_shares=10_000, transaction_value=1_500_000,
            transaction_type="P",
        ),
    ]
    news = [
        SimpleNamespace(date="2026-05-20", sentiment="positive"),
        SimpleNamespace(date="2026-05-19", sentiment="positive"),
        SimpleNamespace(date="2026-05-18", sentiment="neutral"),
    ]
    actions = [
        SimpleNamespace(action_date="2026-05-21", action="up"),
        SimpleNamespace(action_date="2026-05-20", action="up"),
    ]
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[],
        insider_trades=insider_trades, news=news,
        analyst_actions=actions, analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


class TestSentimentModule:
    def test_name(self):
        assert SentimentModule().name == "sentiment"

    @patch("src.research.modules.sentiment.call_research_llm")
    def test_aggregates_all_three(self, mock_llm):
        from src.research.modules.sentiment import _SentimentNarrative
        mock_llm.return_value = _SentimentNarrative(narrative="Bullish-tilt.")
        out = SentimentModule().run(_req(), None, _shared())
        assert out.skipped is False
        assert out.key_metrics["insider_net_value"] == 1_500_000.0
        assert out.key_metrics["news_positive_pct"] > 0
        assert out.key_metrics["analyst_net_upgrades"] == 2.0

    def test_skipped_when_all_empty(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = SentimentModule().run(_req(), None, shared)
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_sentiment.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/sentiment.py`:

```python
"""Sentiment module — insider flow + news polarity + analyst revisions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _SentimentNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences synthesizing insider, news, and analyst signals."
    )


def _window_filter(items, date_attr: str, scan_date: str, days: int = 30):
    cutoff = (datetime.strptime(scan_date, "%Y-%m-%d") - timedelta(days=days)).date()
    out = []
    for it in items:
        d = getattr(it, date_attr, None)
        if not d:
            continue
        try:
            dd = datetime.strptime(d[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if dd >= cutoff:
            out.append(it)
    return out


class SentimentModule(AnalysisModule):
    name = "sentiment"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        insider_recent = _window_filter(
            shared_data.insider_trades, "transaction_date",
            shared_data.scan_date, days=30,
        )
        news_recent = _window_filter(
            shared_data.news, "date", shared_data.scan_date, days=14,
        )
        actions_recent = _window_filter(
            shared_data.analyst_actions, "action_date",
            shared_data.scan_date, days=14,
        )

        if not insider_recent and not news_recent and not actions_recent:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason="No sentiment signals in 14-30 day window",
            )

        net_insider = sum(
            float(getattr(t, "transaction_value", 0) or 0)
            for t in insider_recent
        )
        pos = sum(1 for n in news_recent if (getattr(n, "sentiment", "") or "").lower() == "positive")
        neg = sum(1 for n in news_recent if (getattr(n, "sentiment", "") or "").lower() == "negative")
        n_news = len(news_recent) or 1
        net_upgrades = sum(
            (1 if (getattr(a, "action", "") or "").lower() == "up" else
             -1 if (getattr(a, "action", "") or "").lower() == "down" else 0)
            for a in actions_recent
        )

        metrics = {
            "insider_net_value": round(net_insider, 2),
            "insider_trade_count_30d": float(len(insider_recent)),
            "news_positive_pct": round(pos / n_news * 100, 1) if news_recent else 0.0,
            "news_negative_pct": round(neg / n_news * 100, 1) if news_recent else 0.0,
            "analyst_net_upgrades": float(net_upgrades),
        }
        prompt = (
            f"Sentiment snapshot for {request.ticker} as of {shared_data.scan_date}:\n"
            f"  Insider net $ flow (30d): ${net_insider:+,.0f} "
            f"({len(insider_recent)} trades)\n"
            f"  News polarity (14d): {pos} positive, {neg} negative, "
            f"{len(news_recent) - pos - neg} neutral\n"
            f"  Analyst net upgrades (14d): {net_upgrades:+d}\n"
            f"\nWrite 3-5 sentences synthesizing what these three signals\n"
            f"jointly say about market positioning. Note any divergence.\n"
            f"Anchor on numbers; do not predict direction."
        )
        narrative = call_research_llm(
            prompt, _SentimentNarrative,
            default_factory=lambda: _SentimentNarrative(
                narrative=(
                    f"Insider ${net_insider:+,.0f}, "
                    f"news {pos}+/{neg}-, analyst net {net_upgrades:+d}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

Modify `src/research/modules/__init__.py` — append SentimentModule.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_sentiment.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/sentiment.py src/research/modules/__init__.py tests/research/test_module_sentiment.py
git commit -m "feat(research): sentiment module (objective)

Aggregates 30d insider $ flow + 14d news polarity + 14d analyst
revisions into one synthesis. Skipped when all three windows empty.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: Risk-position module (objective, depends on valuation + technical)

**Files:**
- Create: `src/research/modules/risk_position.py`
- Create: `tests/research/test_module_risk_position.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_risk_position.py`:

```python
"""Risk-position module: takes request.target_position_pct + risk_tolerance
+ outputs from technical (S/R) and valuation (fair value) to suggest
a stop/target ladder. Pure deterministic math + LLM rationale."""

from __future__ import annotations

from unittest.mock import patch

from src.research.modules.risk_position import RiskPositionModule
from src.research.models import ResearchRequest, ModuleResult
from src.research.shared_data import SharedData


def _req(risk="moderate", pos=0.05):
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=pos, risk_tolerance=risk,
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


def _prior():
    """Prior module outputs that risk_position consumes."""
    return {
        "valuation": ModuleResult(
            module_name="valuation", persona_used=None, markdown="",
            key_metrics={"current_price": 145.0, "fair_value_low": 150.0,
                         "fair_value_high": 180.0},
        ),
        "technical": ModuleResult(
            module_name="technical", persona_used=None, markdown="",
            key_metrics={"current_price": 145.0, "support": 138.0,
                         "resistance": 160.0, "sma_50": 142.0},
        ),
    }


class TestRiskPositionModule:
    def test_name(self):
        assert RiskPositionModule().name == "risk_position"

    @patch("src.research.modules.risk_position.call_research_llm")
    def test_conservative_tighter_than_aggressive(self, mock_llm):
        from src.research.modules.risk_position import _RiskNarrative
        mock_llm.return_value = _RiskNarrative(narrative="Plan ok.")

        cons = RiskPositionModule().run(_req(risk="conservative"), None, _shared(),
                                         prior_results=_prior())
        aggr = RiskPositionModule().run(_req(risk="aggressive"), None, _shared(),
                                         prior_results=_prior())
        assert cons.key_metrics["stop_price"] > aggr.key_metrics["stop_price"]
        assert cons.key_metrics["target_price"] < aggr.key_metrics["target_price"]

    def test_skipped_when_prior_missing(self):
        out = RiskPositionModule().run(_req(), None, _shared(), prior_results={})
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_risk_position.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/risk_position.py`:

```python
"""Risk-position module — deterministic stop/target ladder from prior
valuation + technical module outputs.

Unlike the other modules, ``run()`` takes a ``prior_results`` kwarg.
The pipeline orchestrator passes the module_results dict so this
module can read ``valuation.key_metrics['fair_value_high']`` and
``technical.key_metrics['support']``. Synthesizer can override the
final TradePlan; this module's output is a *suggestion*.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _RiskNarrative(BaseModel):
    narrative: str = Field(
        description="2-4 sentences justifying the stop/target ladder."
    )


_RISK_PROFILES = {
    "conservative": {"stop_mult": 1.5, "target_mult": 1.5, "sizing_dampener": 0.6},
    "moderate":     {"stop_mult": 2.0, "target_mult": 2.0, "sizing_dampener": 1.0},
    "aggressive":   {"stop_mult": 3.0, "target_mult": 3.0, "sizing_dampener": 1.2},
}


class RiskPositionModule(AnalysisModule):
    name = "risk_position"
    # Phase 2 will add ["druckenmiller", "burry"]
    supports_personas: list[str] = []

    def run(
        self,
        request: ResearchRequest,
        persona: str | None,
        shared_data: SharedData,
        *,
        prior_results: dict[str, ModuleResult] | None = None,
    ) -> ModuleResult:
        persona = self._coerce_persona(persona)
        prior_results = prior_results or {}

        valuation = prior_results.get("valuation")
        technical = prior_results.get("technical")
        if (valuation is None or valuation.skipped
                or technical is None or technical.skipped):
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason="risk_position needs valuation + technical outputs",
            )

        price = float(technical.key_metrics.get("current_price", 0))
        support = float(technical.key_metrics.get("support", 0))
        fv_high = float(valuation.key_metrics.get("fair_value_high", 0))
        if price <= 0 or support <= 0 or fv_high <= 0:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True, skip_reason="Missing price / support / fair_value",
            )

        profile = _RISK_PROFILES[request.risk_tolerance]
        # Stop: scale gap below support by stop_mult
        stop_distance = (price - support) * profile["stop_mult"]
        stop_price = round(price - stop_distance, 2)
        # Target: scale upside to fair_value_high by target_mult, capped at fv_high
        upside = (fv_high - price) * profile["target_mult"]
        target_price = round(min(price + upside, fv_high * 1.10), 2)
        sizing = round(
            request.target_position_pct * profile["sizing_dampener"], 4,
        )
        sizing = min(sizing, request.target_position_pct)

        metrics = {
            "entry_price": round(price, 2),
            "stop_price": stop_price,
            "target_price": target_price,
            "sizing_pct": sizing,
            "risk_reward_ratio": round((target_price - price) / max(price - stop_price, 1e-6), 2),
            "horizon_days": 30.0,
        }
        prompt = (
            f"Suggested trade plan for {request.ticker} "
            f"(risk tolerance: {request.risk_tolerance}):\n"
            f"  Entry: ${price:.2f}\n"
            f"  Stop:  ${stop_price:.2f}\n"
            f"  Target: ${target_price:.2f}\n"
            f"  R:R   : {metrics['risk_reward_ratio']:.2f}\n"
            f"  Sizing: {sizing * 100:.2f}% of portfolio\n"
            f"\nWrite 2-4 sentences justifying this plan given the support\n"
            f"(${support:.2f}) and fair-value upper bound (${fv_high:.2f}).\n"
            f"Note the risk if stopped out."
        )
        narrative = call_research_llm(
            prompt, _RiskNarrative,
            default_factory=lambda: _RiskNarrative(
                narrative=(
                    f"Stop ${stop_price:.2f}, target ${target_price:.2f}, "
                    f"R:R {metrics['risk_reward_ratio']:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

Modify `src/research/modules/__init__.py` — append RiskPositionModule.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_risk_position.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/risk_position.py src/research/modules/__init__.py tests/research/test_module_risk_position.py
git commit -m "feat(research): risk_position module (objective)

Takes prior valuation + technical results, computes stop/target/sizing
per risk_tolerance profile (conservative=tight, aggressive=wide). Run
signature accepts prior_results kwarg — orchestrator passes module_results
dict at sequencing time.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: Detector-replay backtest module (deterministic, no LLM)

**Files:**
- Create: `src/research/modules/detector_backtest.py`
- Create: `tests/research/test_module_detector_backtest.py`
- Modify: `src/research/modules/__init__.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_detector_backtest.py`:

```python
"""Detector backtest: replays a TradePlan over past dates where the same
detector set fired on this ticker. Pure deterministic math; no LLM."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.research.modules.detector_backtest import (
    replay_trade_plan,
    BacktestInputs,
)
from src.research.models import TradePlan, BacktestSummary


def _write_history_csv(path: Path, rows: list[dict]):
    cols = ["scan_date", "ticker", "triggered_detectors", "close_at_scan",
            "ret_5d", "ret_20d", "alpha_5d", "alpha_20d"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _plan(entry=145.0, target=165.0, stop=138.0, horizon=30):
    return TradePlan(
        direction="long", entry_price=entry, target_price=target,
        stop_price=stop, horizon_days=horizon, sizing_pct=0.05,
        confidence=70, rationale="test",
    )


class TestReplay:
    def test_strong_sample(self, tmp_path):
        csv_path = tmp_path / "nvda_history.csv"
        _write_history_csv(csv_path, [
            {"scan_date": "2025-01-15", "ticker": "NVDA",
             "triggered_detectors": "earnings_event|insider_cluster",
             "close_at_scan": 100.0, "ret_20d": 0.15},
            {"scan_date": "2025-03-20", "ticker": "NVDA",
             "triggered_detectors": "earnings_event|insider_cluster",
             "close_at_scan": 110.0, "ret_20d": -0.05},
        ] * 6)  # 12 rows total — strong sample

        summary = replay_trade_plan(BacktestInputs(
            ticker="NVDA",
            triggered_detectors=["earnings_event", "insider_cluster"],
            plan=_plan(),
            history_csv=csv_path,
        ))
        assert isinstance(summary, BacktestSummary)
        assert summary.matches_found == 12
        assert summary.sample_quality == "strong"
        assert summary.win_rate is not None

    def test_insufficient(self, tmp_path):
        csv_path = tmp_path / "nvda_history.csv"
        _write_history_csv(csv_path, [])
        summary = replay_trade_plan(BacktestInputs(
            ticker="NVDA",
            triggered_detectors=["earnings_event"],
            plan=_plan(),
            history_csv=csv_path,
        ))
        assert summary.matches_found == 0
        assert summary.sample_quality == "insufficient"
        assert summary.caveat is not None

    def test_jaccard_overlap_match(self, tmp_path):
        """When today's trigger set has ≥3 detectors, accept past dates
        with Jaccard overlap ≥ 0.6. Today: {a,b,c}; past with {a,b}
        has overlap 2/3 = 0.67 → matches."""
        csv_path = tmp_path / "x.csv"
        _write_history_csv(csv_path, [
            {"scan_date": "2025-01-15", "ticker": "NVDA",
             "triggered_detectors": "a|b",
             "close_at_scan": 100.0, "ret_20d": 0.10},
        ] * 5)
        summary = replay_trade_plan(BacktestInputs(
            ticker="NVDA",
            triggered_detectors=["a", "b", "c"],  # 3 today
            plan=_plan(),
            history_csv=csv_path,
        ))
        assert summary.matches_found == 5
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_detector_backtest.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/detector_backtest.py`:

```python
"""Detector-replay backtest.

NOT an AnalysisModule subclass — runs after the synthesizer produces
the TradePlan, in its own pipeline node. Reads a per-ticker history
CSV of past detector triggers and computes how a hypothetical replay
of the plan would have fared.

Inputs:
  * today's triggered_detectors (from scanner_context)
  * the synthesized TradePlan
  * a history CSV path (one per ticker)

Output: BacktestSummary.

The CSV schema mirrors the existing v2/backtesting outputs:
  scan_date, ticker, triggered_detectors (pipe-separated),
  close_at_scan, ret_5d, ret_20d, alpha_5d, alpha_20d
"""

from __future__ import annotations

import csv
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

from src.research.models import BacktestSummary, SampleQuality, TradePlan

logger = logging.getLogger(__name__)


@dataclass
class BacktestInputs:
    ticker: str
    triggered_detectors: list[str]
    plan: TradePlan
    history_csv: Path


def _quality_for(n: int) -> SampleQuality:
    if n >= 10:
        return "strong"
    if n >= 5:
        return "moderate"
    if n >= 2:
        return "weak"
    return "insufficient"


def _matches(past_triggers: list[str], today_triggers: list[str]) -> bool:
    """Match rule per spec:
      * n ≤ 2 today: require exact set match
      * n ≥ 3 today: Jaccard overlap ≥ 0.6
    """
    if not past_triggers or not today_triggers:
        return False
    past_set = set(past_triggers)
    today_set = set(today_triggers)
    if len(today_set) <= 2:
        return past_set == today_set
    inter = past_set & today_set
    union = past_set | today_set
    return (len(inter) / len(union)) >= 0.6


def _read_history(csv_path: Path, ticker: str) -> list[dict]:
    if not csv_path.exists():
        return []
    out = []
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker") != ticker:
                continue
            row["_detectors"] = [
                d for d in (row.get("triggered_detectors") or "").split("|") if d
            ]
            out.append(row)
    return out


def replay_trade_plan(inputs: BacktestInputs) -> BacktestSummary:
    """Walk the history CSV; for each matching past date, treat the row's
    close as entry and use its forward returns (ret_20d) as the replayed
    outcome. Approximate — not a full day-by-day walk; uses pre-computed
    forward returns to keep the implementation cheap.
    """
    rows = _read_history(inputs.history_csv, inputs.ticker)
    matches = [r for r in rows if _matches(r["_detectors"], inputs.triggered_detectors)]

    if not matches:
        return BacktestSummary(
            matches_found=0, win_rate=None,
            avg_pnl_pct=None, max_drawdown_pct=None,
            avg_holding_days=None, sample_quality="insufficient",
            caveat=(
                f"No historical matches for {inputs.ticker} with detector "
                f"combo {inputs.triggered_detectors}"
            ),
        )

    returns: list[float] = []
    for r in matches:
        try:
            ret = float(r.get("ret_20d") or 0.0)
        except (TypeError, ValueError):
            continue
        returns.append(ret)

    if not returns:
        return BacktestSummary(
            matches_found=len(matches), win_rate=None,
            avg_pnl_pct=None, max_drawdown_pct=None,
            avg_holding_days=None, sample_quality="insufficient",
            caveat="Matches found but forward returns missing",
        )

    direction_sign = 1.0 if inputs.plan.direction == "long" else (
        -1.0 if inputs.plan.direction == "short" else 0.0
    )
    if direction_sign == 0.0:
        # stand_aside has no actionable plan to replay
        return BacktestSummary(
            matches_found=len(matches), win_rate=None,
            avg_pnl_pct=None, max_drawdown_pct=None,
            avg_holding_days=20.0,
            sample_quality=_quality_for(len(matches)),
            caveat="Plan is stand_aside; replay skipped",
        )

    directional = [ret * direction_sign for ret in returns]
    wins = sum(1 for x in directional if x > 0)
    avg = statistics.mean(directional)
    worst = min(directional)
    quality = _quality_for(len(matches))
    caveat = None
    if quality in ("weak", "moderate"):
        caveat = f"Only {len(matches)} historical matches — interpret with caution"

    return BacktestSummary(
        matches_found=len(matches),
        win_rate=round(wins / len(directional), 3),
        avg_pnl_pct=round(avg, 4),
        max_drawdown_pct=round(worst, 4),
        avg_holding_days=20.0,
        sample_quality=quality,
        caveat=caveat,
    )
```

Note: this module is NOT added to `ALL_MODULES` (it's not an `AnalysisModule`). The pipeline orchestrator imports `replay_trade_plan` directly.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_detector_backtest.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/detector_backtest.py tests/research/test_module_detector_backtest.py
git commit -m "feat(research): detector-replay backtest

Deterministic, no LLM. Walks a per-ticker history CSV, finds past dates
where the same detector set fired (exact match for n≤2, Jaccard≥0.6 for
n≥3), uses pre-computed ret_20d as replayed outcome. Emits sample_quality
bucket + caveat for low-n cases.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: Synthesizer

**Files:**
- Create: `src/research/synthesizer.py`
- Create: `tests/research/test_synthesizer.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_synthesizer.py`:

```python
"""Synthesizer: takes ResearchRequest + module_results, calls LLM, returns
(report_markdown, TradePlan)."""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import ModuleResult, ResearchRequest, TradePlan
from src.research.synthesizer import synthesize, _SynthOutput


def _req(goal="new_entry"):
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal=goal, use_personas=False, scanner_context=None,
    )


def _mod(name, markdown, metrics=None):
    return ModuleResult(
        module_name=name, persona_used=None, markdown=markdown,
        key_metrics=metrics or {},
    )


class TestSynthesize:
    @patch("src.research.synthesizer.call_research_llm")
    def test_returns_report_and_plan(self, mock_llm):
        mock_llm.return_value = _SynthOutput(
            report_markdown="# NVDA\n\nGood setup.",
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="Earnings beat + insider buy.",
        )
        report, plan = synthesize(_req(), {
            "macro": _mod("macro", "SPY up 5%"),
            "valuation": _mod("valuation", "Fair value $160",
                              {"fair_value_high": 180.0}),
        })
        assert "NVDA" in report
        assert isinstance(plan, TradePlan)
        assert plan.direction == "long"
        assert plan.entry_price == 145.0

    @patch("src.research.synthesizer.call_research_llm")
    def test_stand_aside_zeros_prices(self, mock_llm):
        mock_llm.return_value = _SynthOutput(
            report_markdown="Skip", direction="stand_aside",
            entry_price=None, target_price=None, stop_price=None,
            horizon_days=0, sizing_pct=0.0, confidence=0,
            rationale="Insufficient data",
        )
        _, plan = synthesize(_req(), {})
        assert plan.direction == "stand_aside"
        assert plan.entry_price is None

    @patch("src.research.synthesizer.call_research_llm")
    def test_skipped_modules_omitted_from_prompt(self, mock_llm):
        """Modules with skipped=True should not appear in the prompt body."""
        captured = {}
        def _capture(prompt, model, **kw):
            captured["prompt"] = prompt
            return _SynthOutput(
                report_markdown="ok", direction="stand_aside",
                entry_price=None, target_price=None, stop_price=None,
                horizon_days=0, sizing_pct=0.0, confidence=0, rationale="x",
            )
        mock_llm.side_effect = _capture
        synthesize(_req(), {
            "macro": _mod("macro", "live", metrics={}),
            "sentiment": ModuleResult(
                module_name="sentiment", persona_used=None, markdown="",
                skipped=True, skip_reason="no news",
            ),
        })
        assert "macro" in captured["prompt"].lower()
        # Skipped module not referenced
        assert "sentiment" not in captured["prompt"].lower() or "no news" not in captured["prompt"].lower()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_synthesizer.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/synthesizer.py`:

```python
"""Synthesizer — compiles module outputs into a coherent report + TradePlan.

One LLM call. Prompt contains the ResearchRequest framing
(holding_status, risk_tolerance, report_goal) plus every non-skipped
module's markdown. LLM returns a structured object with the report
narrative and the TradePlan fields.

The synthesizer does NOT see the BacktestSummary — that's computed
after it. Keeps the LLM from tuning the plan to historical sample
results.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest, TradePlan

logger = logging.getLogger(__name__)


_GOAL_FRAMING = {
    "new_entry": (
        "User is evaluating a NEW position. Emphasize entry rationale, "
        "valuation gap, near-term catalysts. Plan should be actionable now."
    ),
    "hold_review": (
        "User already HOLDS this. Emphasize thesis check, catalysts since "
        "last review, exit signposts. Plan can be hold/trim/add."
    ),
    "exit_decision": (
        "User is considering an EXIT. Emphasize bear case strength, what "
        "would change the mind. Plan can be hold/trim/exit."
    ),
    "general_research": (
        "Balanced research, no specific action bias. Plan should reflect "
        "the strongest evidence direction or stand_aside."
    ),
}


class _SynthOutput(BaseModel):
    """LLM output: report narrative + flat TradePlan fields."""

    report_markdown: str = Field(
        description="800-1500 word markdown report. Use headings for sections."
    )
    direction: Literal["long", "short", "stand_aside"]
    entry_price: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    horizon_days: int = 0
    sizing_pct: float = 0.0
    confidence: int = Field(ge=0, le=100, default=0)
    rationale: str = Field(description="1-2 sentence plan summary.")


def synthesize(
    request: ResearchRequest,
    module_results: dict[str, ModuleResult],
) -> tuple[str, TradePlan]:
    """Run one LLM call to produce report + TradePlan."""
    framing = _GOAL_FRAMING.get(request.report_goal, _GOAL_FRAMING["general_research"])

    sections = []
    for name, result in module_results.items():
        if result.skipped:
            continue
        if not result.markdown.strip():
            continue
        sections.append(f"### {name}\n{result.markdown.strip()}\n")
    sections_block = "\n".join(sections) if sections else "(no module produced content)"

    prompt = (
        f"You are an institutional research analyst writing a single-ticker "
        f"report for {request.ticker}.\n\n"
        f"Position context:\n"
        f"  Holding status: {request.holding_status}\n"
        f"  Target position size: {request.target_position_pct * 100:.2f}% of portfolio\n"
        f"  Risk tolerance: {request.risk_tolerance}\n"
        f"  Report goal: {request.report_goal}\n\n"
        f"Framing instruction: {framing}\n\n"
        f"--- ANALYTICAL MODULE OUTPUTS ---\n\n"
        f"{sections_block}\n\n"
        f"--- YOUR TASK ---\n\n"
        f"Produce TWO things:\n\n"
        f"1. A markdown report (800-1500 words) synthesizing the modules "
        f"into one coherent narrative. Use section headings. Anchor every "
        f"claim on a number from the module outputs.\n\n"
        f"2. A single-shot trade plan: direction (long/short/stand_aside), "
        f"entry_price, target_price, stop_price, horizon_days, sizing_pct "
        f"(<= target_position_size), confidence (0-100), rationale.\n\n"
        f"Choose direction=stand_aside when the bear case dominates and "
        f"the user is not already holding, OR when data is too thin to "
        f"justify a position. In that case set entry/target/stop to null, "
        f"horizon_days=0, sizing_pct=0.\n\n"
        f"Adjust stop tightness and target ambition to the user's risk "
        f"tolerance: conservative=tighter stops + closer targets; aggressive=wider."
    )

    out = call_research_llm(
        prompt, _SynthOutput,
        default_factory=lambda: _SynthOutput(
            report_markdown=f"# {request.ticker}\n\nReport synthesis failed.",
            direction="stand_aside", confidence=0,
            rationale="Synthesizer LLM failed; defaulting to stand_aside.",
        ),
    )

    if out.direction == "stand_aside":
        plan = TradePlan(
            direction="stand_aside", entry_price=None, target_price=None,
            stop_price=None, horizon_days=0, sizing_pct=0.0,
            confidence=out.confidence, rationale=out.rationale,
        )
    else:
        plan = TradePlan(
            direction=out.direction,
            entry_price=out.entry_price,
            target_price=out.target_price,
            stop_price=out.stop_price,
            horizon_days=out.horizon_days,
            sizing_pct=min(out.sizing_pct, request.target_position_pct),
            confidence=out.confidence,
            rationale=out.rationale,
        )
    return out.report_markdown, plan
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_synthesizer.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/synthesizer.py tests/research/test_synthesizer.py
git commit -m "feat(research): synthesizer LLM agent

One LLM call: takes ResearchRequest + module_results, returns
(report_markdown, TradePlan). Goal-specific framing injected into
prompt. Stand_aside path explicit; sizing capped at request's
target_position_pct.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 15: Pipeline orchestration (LangGraph)

**Files:**
- Create: `src/research/pipeline.py`
- Create: `tests/research/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_pipeline.py`:

```python
"""Pipeline: glue everything together. With mocks, run_research(request)
should fetch SharedData, run all registered modules, pass valuation+
technical to risk_position, run synthesizer, run detector_backtest,
return a ResearchState with all fields populated."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from src.research.models import (
    ResearchRequest, ModuleResult, TradePlan, BacktestSummary,
)
from src.research.shared_data import SharedData


def _req(scanner_ctx=None):
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False,
        scanner_context=scanner_ctx,
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


class TestRunResearch:
    @patch("src.research.pipeline.fetch_shared_data")
    @patch("src.research.pipeline.synthesize")
    @patch("src.research.pipeline.replay_trade_plan")
    def test_happy_path(self, mock_replay, mock_synth, mock_fetch):
        from src.research.pipeline import run_research
        from src.research.modules.base import AnalysisModule

        mock_fetch.return_value = _shared()
        mock_synth.return_value = ("# report", TradePlan(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="x",
        ))
        mock_replay.return_value = BacktestSummary(
            matches_found=0, win_rate=None, avg_pnl_pct=None,
            max_drawdown_pct=None, avg_holding_days=None,
            sample_quality="insufficient", caveat="no history",
        )

        # Patch ALL_MODULES with one stub module that always returns a
        # ModuleResult, to keep this test isolated from real modules.
        class _Stub(AnalysisModule):
            name = "stub"
            supports_personas = []
            def run(self, request, persona, shared_data):
                return ModuleResult(
                    module_name="stub", persona_used=None,
                    markdown="stub output",
                )

        with patch("src.research.pipeline.ALL_MODULES", [_Stub]):
            state = run_research(_req())

        assert state["strategy"].direction == "long"
        assert state["backtest_summary"].matches_found == 0
        assert "stub" in state["module_results"]
        assert state["report_markdown"] == "# report"

    @patch("src.research.pipeline.fetch_shared_data")
    def test_no_scanner_context_uses_empty_triggers(self, mock_fetch):
        """When scanner_context is None, backtest is invoked with empty
        triggered_detectors list — replay_trade_plan returns insufficient."""
        from src.research.pipeline import run_research
        mock_fetch.return_value = _shared()
        with patch("src.research.pipeline.ALL_MODULES", []), \
             patch("src.research.pipeline.synthesize",
                   return_value=("r", TradePlan(
                       direction="stand_aside", entry_price=None,
                       target_price=None, stop_price=None,
                       horizon_days=0, sizing_pct=0.0, confidence=0,
                       rationale="x",
                   ))), \
             patch("src.research.pipeline.replay_trade_plan") as mock_replay:
            mock_replay.return_value = BacktestSummary(
                matches_found=0, win_rate=None, avg_pnl_pct=None,
                max_drawdown_pct=None, avg_holding_days=None,
                sample_quality="insufficient", caveat="no triggers",
            )
            state = run_research(_req(scanner_ctx=None))
            args = mock_replay.call_args[0][0]  # BacktestInputs
            assert args.triggered_detectors == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_pipeline.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/pipeline.py`:

```python
"""Pipeline orchestration for the research workflow.

Phase 1: linear orchestration with explicit sequencing — no LangGraph
node DAG yet. (LangGraph wiring lands in Phase 2 when the persona-router
introduces conditional edges and the debate node introduces fan-out.
For Phase 1 the sequence is simple enough that a plain function reads
clearer than a graph.)

Sequence:
  1. fetch_shared_data
  2. Run every module except risk_position
  3. Run risk_position with prior_results = the above
  4. synthesize(request, module_results) → (report, TradePlan)
  5. replay_trade_plan → BacktestSummary
  6. Assemble ResearchState
"""

from __future__ import annotations

import inspect
import logging
from datetime import date
from pathlib import Path

from src.research.models import (
    BacktestSummary, ModuleResult, ResearchRequest, ResearchState, TradePlan,
)
from src.research.modules import ALL_MODULES
from src.research.modules.detector_backtest import (
    BacktestInputs, replay_trade_plan,
)
from src.research.shared_data import fetch_shared_data
from src.research.synthesizer import synthesize

logger = logging.getLogger(__name__)


def _scan_date(request: ResearchRequest) -> str:
    """Today's date for the data fetch. Cron passes scanner_context with
    its own scan_date implicitly; for on-demand calls without scanner
    context we use today."""
    ctx = request.scanner_context or {}
    return ctx.get("scan_date") or date.today().isoformat()


def _history_csv_path(ticker: str) -> Path:
    """Detector trigger history CSV. v1: assume per-ticker file under
    outputs/detector_history/. Missing file → empty history → backtest
    returns 'insufficient'."""
    return Path("outputs/detector_history") / f"{ticker}.csv"


def run_research(request: ResearchRequest) -> ResearchState:
    """End-to-end pipeline. Returns a ResearchState with all fields
    populated (or None where appropriate)."""
    scan_date = _scan_date(request)
    shared = fetch_shared_data(request.ticker, scan_date)

    module_results: dict[str, ModuleResult] = {}

    # Run every module that's not risk_position first
    risk_position_module = None
    for module_cls in ALL_MODULES:
        if module_cls.__name__ == "RiskPositionModule":
            risk_position_module = module_cls
            continue
        module = module_cls()
        try:
            result = module.run(request, persona=None, shared_data=shared)
        except Exception as e:
            logger.exception(
                "module %s raised — should not happen per ABC contract: %s",
                module.name, e,
            )
            result = ModuleResult(
                module_name=module.name, persona_used=None, markdown="",
                skipped=True, skip_reason=f"Unhandled exception: {e}",
            )
        module_results[module.name] = result

    # Now risk_position with prior_results
    if risk_position_module is not None:
        try:
            m = risk_position_module()
            sig = inspect.signature(m.run)
            kwargs = {}
            if "prior_results" in sig.parameters:
                kwargs["prior_results"] = module_results
            result = m.run(request, persona=None, shared_data=shared, **kwargs)
        except Exception as e:
            logger.exception("risk_position raised: %s", e)
            result = ModuleResult(
                module_name="risk_position", persona_used=None, markdown="",
                skipped=True, skip_reason=f"Unhandled exception: {e}",
            )
        module_results["risk_position"] = result

    # Synthesizer
    report_md, plan = synthesize(request, module_results)

    # Backtest
    triggered: list[str] = []
    if request.scanner_context:
        triggered = list(request.scanner_context.get("triggered_detectors") or [])
    backtest = replay_trade_plan(BacktestInputs(
        ticker=request.ticker,
        triggered_detectors=triggered,
        plan=plan,
        history_csv=_history_csv_path(request.ticker),
    ))

    return ResearchState(
        request=request,
        persona_assignments=None,  # Phase 2 populates
        module_results=module_results,
        report_markdown=report_md,
        strategy=plan,
        backtest_summary=backtest,
        rendered_html=None,  # Phase 3 populates
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_pipeline.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/pipeline.py tests/research/test_pipeline.py
git commit -m "feat(research): pipeline orchestration (linear, no LangGraph yet)

Sequence: SharedData fetch -> all modules except risk_position ->
risk_position (with prior_results) -> synthesizer -> detector_backtest.
LangGraph node DAG deferred to Phase 2 where router + debate need
conditional edges; Phase 1 sequence is simple enough that a function
reads clearer.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 16: CLI entrypoint

**Files:**
- Create: `src/research/__main__.py`
- Create: `tests/research/test_cli.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_cli.py`:

```python
"""CLI: python -m src.research --ticker NVDA prints a TradePlan summary."""

from __future__ import annotations

from unittest.mock import patch
from io import StringIO
import sys

from src.research.models import (
    BacktestSummary, ResearchRequest, ResearchState, TradePlan,
)


def _fake_state(direction="long"):
    return ResearchState(
        request=ResearchRequest(
            ticker="NVDA", holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=False, scanner_context=None,
        ),
        persona_assignments=None,
        module_results={},
        report_markdown="# NVDA report",
        strategy=TradePlan(
            direction=direction, entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="test",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html=None,
    )


class TestCLI:
    def test_main_prints_summary(self, capsys):
        from src.research.__main__ import main
        with patch("src.research.__main__.run_research",
                   return_value=_fake_state()):
            exit_code = main(["--ticker", "NVDA"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "NVDA" in captured.out
        assert "long" in captured.out.lower()
        assert "145" in captured.out
        assert "moderate" in captured.out.lower()

    def test_main_with_custom_request(self, capsys):
        from src.research.__main__ import main
        with patch("src.research.__main__.run_research",
                   return_value=_fake_state(direction="stand_aside")):
            exit_code = main([
                "--ticker", "NVDA",
                "--holding-status", "considering_buy",
                "--position-pct", "0.03",
                "--risk", "aggressive",
                "--goal", "new_entry",
            ])
        assert exit_code == 0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_cli.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/__main__.py`:

```python
"""CLI entrypoint: python -m src.research --ticker NVDA.

Phase 1 prints a summary to stdout. Phase 3 will add --output html and
--email flags.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.research.models import ResearchRequest
from src.research.pipeline import run_research


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.research",
                                description="Run per-stock research pipeline.")
    p.add_argument("--ticker", required=True, help="Ticker symbol, e.g. NVDA")
    p.add_argument("--holding-status",
                   choices=["holding", "watching", "considering_buy",
                            "considering_short"],
                   default="watching")
    p.add_argument("--position-pct", type=float, default=0.05,
                   help="Target position size, fraction (default: 0.05)")
    p.add_argument("--risk",
                   choices=["conservative", "moderate", "aggressive"],
                   default="moderate")
    p.add_argument("--goal",
                   choices=["new_entry", "hold_review", "exit_decision",
                            "general_research"],
                   default="general_research")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _print_summary(state) -> None:
    plan = state["strategy"]
    backtest = state["backtest_summary"]
    req = state["request"]

    print()
    print("=" * 72)
    print(f"  {req.ticker} — research report")
    print("=" * 72)
    print(f"  Holding status: {req.holding_status} | "
          f"Risk: {req.risk_tolerance} | Goal: {req.report_goal}")
    print()
    print("-" * 72)
    print(f"  TRADE PLAN: {plan.direction.upper()}")
    print("-" * 72)
    if plan.direction == "stand_aside":
        print(f"  No actionable trade. Confidence: {plan.confidence}/100")
        print(f"  Rationale: {plan.rationale}")
    else:
        print(f"  Entry:  ${plan.entry_price:.2f}")
        print(f"  Target: ${plan.target_price:.2f}")
        print(f"  Stop:   ${plan.stop_price:.2f}")
        print(f"  Horizon: {plan.horizon_days} days")
        print(f"  Sizing: {plan.sizing_pct * 100:.2f}% of portfolio")
        print(f"  Confidence: {plan.confidence}/100")
        print(f"  Rationale: {plan.rationale}")

    print()
    print("-" * 72)
    print(f"  DETECTOR BACKTEST ({backtest.sample_quality})")
    print("-" * 72)
    print(f"  Matches found: {backtest.matches_found}")
    if backtest.win_rate is not None:
        print(f"  Win rate: {backtest.win_rate * 100:.1f}%")
        print(f"  Avg PnL: {(backtest.avg_pnl_pct or 0) * 100:+.2f}%")
        print(f"  Max drawdown: {(backtest.max_drawdown_pct or 0) * 100:+.2f}%")
    if backtest.caveat:
        print(f"  Caveat: {backtest.caveat}")

    print()
    print("-" * 72)
    print("  REPORT")
    print("-" * 72)
    print(state["report_markdown"])
    print()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    request = ResearchRequest(
        ticker=args.ticker.upper(),
        holding_status=args.holding_status,
        target_position_pct=args.position_pct,
        risk_tolerance=args.risk,
        report_goal=args.goal,
        use_personas=False,  # Phase 1 has no router
        scanner_context=None,
    )
    state = run_research(request)
    _print_summary(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_cli.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/__main__.py tests/research/test_cli.py
git commit -m "feat(research): CLI entrypoint

python -m src.research --ticker NVDA --risk moderate --goal new_entry
prints a TradePlan + BacktestSummary + report to stdout. No HTML / no
email in Phase 1 (those land in Phase 3).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 17: End-to-end smoke (real LLM, real data)

**Files:**
- Read-only: invoke the CLI on a real ticker

- [ ] **Step 1: Confirm full test suite is green**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/ -v --tb=short
```
Expected: all tests pass.

- [ ] **Step 2: Confirm no legacy regression**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest -q --tb=no
```
Expected: pre-existing pass count + new `tests/research/*` tests, no previously-passing test failing.

- [ ] **Step 3: Smoke a real ticker**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m src.research --ticker NVDA --risk moderate --goal new_entry
```

Expected within 30-90s:
- TradePlan box prints with non-trivial entry/target/stop/horizon/sizing/confidence/rationale
- BacktestSummary prints (likely `insufficient` since no history CSV exists yet)
- 800-1500 word report follows
- No exceptions in stderr

Manually inspect the report for:
- Specific numbers cited from each module (revenue growth %, P/E, RSI, etc.)
- No section claiming "data not available" when SharedData actually loaded
- Rationale matches the report body's direction

- [ ] **Step 4: Update progress.md**

Add a new dated session block at the top of `progress.md`:
- 17 tasks completed for Phase 1 (objective core)
- ~12 LLM calls per ticker (9 modules + 1 synthesizer; detector_backtest is deterministic)
- Smoke ticker NVDA: result summary
- Phase 2 (personas + router + debate) and Phase 3 (DB + API + cron + HTML) are deferred to separate plans

Commit:
```bash
git add progress.md
git commit -m "docs: log research pipeline Phase 1 landing

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage** (Phase 1 subset):
- `ResearchRequest` schema → Task 1 ✓
- `ResearchState` LangGraph state → Task 1 ✓ (TypedDict defined; LangGraph wiring deferred per Task 15 note)
- `SharedData` fetcher with cache → Task 2 ✓
- `AnalysisModule` ABC → Task 4 ✓
- 8 objective modules → Tasks 5-12 ✓
- `detector_backtest` → Task 13 ✓
- Synthesizer → Task 14 ✓
- Pipeline orchestration → Task 15 ✓
- CLI → Task 16 ✓
- Smoke test → Task 17 ✓

**Spec sections deferred to Phase 2/3** (intentional, noted in plan header):
- persona-router → Phase 2
- 8 persona files → Phase 2
- debate module → Phase 2
- DB models + Alembic migration → Phase 3
- API routes → Phase 3
- HTML template → Phase 3
- Email render → Phase 3
- Scheduler integration → Phase 3
- A/B comparison persistence → Phase 3

**Placeholder scan**: no TBD / TODO / "fill in later" / "implement appropriate". Task 13 references `outputs/detector_history/<ticker>.csv` which may not exist at smoke time — that's by design (backtest emits `insufficient` and a caveat), not a placeholder.

**Type consistency**:
- `ResearchRequest` field names used identically across all tasks (`ticker`, `holding_status`, `target_position_pct`, `risk_tolerance`, `report_goal`, `use_personas`, `scanner_context`)
- `ModuleResult` `module_name`, `persona_used`, `markdown`, `key_metrics`, `chart_data`, `skipped`, `skip_reason` consistent everywhere
- `TradePlan` field set used identically by synthesizer (Task 14), risk_position (Task 12), CLI printer (Task 16), backtest (Task 13)
- `BacktestSummary` `sample_quality` Literal matches across detector_backtest + CLI
- `AnalysisModule.run()` signature `(request, persona, shared_data)` consistent across Tasks 5-12, with Task 12 (risk_position) extending with `prior_results` kwarg — pipeline handles via `inspect.signature` check
- `call_research_llm(prompt, pydantic_model, *, max_retries, default_factory)` signature stable across all module + synthesizer callers

**Risks acknowledged**:
- Phase 1 risk_position is the only module with a different `run()` signature (extra `prior_results` kwarg). Pipeline detects this via `inspect.signature`. If Phase 2 adds another module needing prior_results, refactor needed; for v1 it's an isolated special case.
- Detector backtest assumes a per-ticker CSV at `outputs/detector_history/<ticker>.csv`. v1 has no automation to generate these — they will be missing for every ticker on first run, producing `sample_quality="insufficient"` everywhere. That's documented behavior; a follow-up task (after Phase 1) backfills these CSVs from existing `backtest_ndx100_30d_*.csv` data.
