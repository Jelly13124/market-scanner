# Per-Stock Research Pipeline — Phase 4 (SOP-Driven Analyze) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the user's `stock-analyze-skills` SOP into our pipeline as Phase 4 — produce institutional-grade HTML reports with 15 SOP sections, replace the detector-replay backtest with a technical-signal backtest, and surface it all behind a new "Analyze" frontend tab with a flow-style module picker.

**Architecture:** Replace the single-call synthesizer with a multi-call section-by-section orchestrator that produces a structured `SectionPayload` per SOP section. Port the skill's HTML template (CSS vars + dark mode + bull/bear pills + score badge) as our Jinja template. Skill prompt files are checked into the repo (vendored) under `src/research/prompts/` and loaded at runtime. New `AnalyzePanel` in the frontend mounts as its own top-level tab independent of Scanner.

**Tech Stack:** Python 3.13, Pydantic v2, DeepSeek-chat via Phase 1's `call_research_llm`, Jinja2 (existing transitive dep), SQLAlchemy + Alembic, FastAPI, React + shadcn (existing frontend). No new dependencies.

**Source skill:** https://github.com/Jelly13124/stock-analyze-skills
**Spec files in skill (vendor these):** `stock-analysis/SKILL.md`, `stock-analysis/references/report-template.md`, `stock-analysis/references/report-template.html`, `stock-analysis/modules/*.md` (9 analytical + 1 backtest), `stock-analysis/modules/investors/*.md` (8 personas).

**This plan is Phase 4.** Phase 1-3 (`docs/superpowers/plans/2026-05-22-research-pipeline-phase{1,2,3}.md`) shipped; Phase 4 evolves the internals + frontend while keeping the existing DB + REST API + scheduler infrastructure.

---

## File structure (Phase 4)

```
src/research/
  prompts/                              # NEW — vendored skill markdown files
    README.md                           # provenance + how-to-refresh from upstream
    sop.md                              # vendored from skill SKILL.md (orchestrator rules)
    report_template.md                  # vendored section schema
    modules/
      macro.md sector.md company_fundamentals.md financial_statements.md
      valuation.md technical.md sentiment.md risk_position.md debate.md
    investors/
      buffett.md munger.md graham.md fisher.md lynch.md wood.md burry.md druckenmiller.md
  sections/                             # NEW — one module per SOP section
    __init__.py                         # SECTION_REGISTRY: dict[str, Section]
    base.py                             # Section ABC + SectionPayload + SECTION_ORDER
    data_health.py executive_summary.py evidence_ledger.py
    macro.py sector.py company_fundamentals.py financial_statements.py
    valuation.py technical.py risk_position.py scenarios.py
    conviction.py event_risk.py debate.py final_strategy.py missing_data.py
  backtest_signal.py                    # NEW — technical-signal backtest (KDJ/RSI/MACD)
  sop_orchestrator.py                   # NEW — top-level entry: runs sections in order
  models.py                             # MODIFY: add AnalyzeRequest + AnalyzeReport TypedDict
  html_render.py                        # REWRITE: render new SOP structure
  templates/
    report.html                         # REPLACE with vendored skill HTML
  __main__.py                           # MODIFY: CLI uses sop_orchestrator

app/backend/
  database/models.py                    # MODIFY: add sections_json + analyze_request_json
  alembic/versions/
    d9f1c5b8e2a6_add_analyze_columns.py # NEW — additive columns on research_reports
  models/research_schemas.py            # MODIFY: AnalyzeRunRequest + AnalyzeReportDetail
  routes/research.py                    # MODIFY: /research/run accepts AnalyzeRunRequest

app/frontend/src/
  types/analyze.ts                      # NEW
  services/analyze-service.ts           # NEW (or extend research-service.ts)
  components/panels/analyze/
    analyze-panel.tsx                   # NEW — main tab content
    analyze-form.tsx                    # NEW — gate form (ticker, objective, budget, ...)
    module-picker.tsx                   # NEW — flow-style module toggles
    report-list.tsx                     # NEW — recent reports list
  components/panels/left/
    analyze-action.tsx                  # NEW — left sidebar button
    left-sidebar.tsx                    # MODIFY — mount AnalyzeAction
  services/tab-service.ts               # MODIFY — register 'analyze' TabType
  contexts/tabs-context.tsx             # MODIFY — add 'analyze' to TabType union

tests/research/
  test_sop_orchestrator.py test_section_macro.py test_section_executive_summary.py
  test_section_evidence_ledger.py test_section_scenarios.py test_section_conviction.py
  test_backtest_signal.py test_html_render_sop.py
tests/test_analyze_routes.py
```

## What stays unchanged
- `src/research/{shared_data,llm,router}.py` and `src/research/personas/` Phase 2 wrappers (the persona _Python_ wrapper stays; only the prompt text in `system_addition()` swaps to read from `prompts/investors/{name}.md`).
- DB tables: `research_reports` keeps its existing columns; we ADD two new nullable JSON columns.
- All Phase 3 backend infrastructure: repositories, scheduler, notifications dispatcher, REST API surface (route signature evolves but path stays `/research/run`).
- `v2/`, `src/agents/`, `src/main.py` — never touched.

## Concept: Section vs Module

Phase 1-2 used "module" loosely to mean both prompt-bearing analytical units AND the synthesizer output container. Phase 4 separates:
- **Section** = one SOP output block (Data Health, Executive Summary, ...). Each Section subclass owns its prompt + output schema + render-to-markdown logic. 15 sections + the technical backtest sub-section.
- **Persona** = unchanged from Phase 2 — a system-prompt fragment a Section can prepend.
- **Module picker** in the UI toggles which sections to include. Default = all on (= full SOP).

---

## Task 1: Vendor the skill prompts

**Files:**
- Create: `src/research/prompts/README.md`
- Create: `src/research/prompts/sop.md`
- Create: `src/research/prompts/report_template.md`
- Create: `src/research/prompts/modules/{macro,sector,company_fundamentals,financial_statements,valuation,technical,sentiment,risk_position,debate}.md`
- Create: `src/research/prompts/investors/{buffett,munger,graham,fisher,lynch,wood,burry,druckenmiller}.md`

- [ ] **Step 1: Fetch all prompt files into the repo**

```bash
ROOT=src/research/prompts
mkdir -p $ROOT/modules $ROOT/investors
BASE=https://raw.githubusercontent.com/Jelly13124/stock-analyze-skills/main/stock-analysis

curl -sL $BASE/SKILL.md                       -o $ROOT/sop.md
curl -sL $BASE/references/report-template.md  -o $ROOT/report_template.md

for f in macro sector company-fundamentals financial-statements valuation technical sentiment risk-position debate-panel backtest; do
  target=$(echo "$f" | tr - _)
  case "$f" in
    company-fundamentals) target=company_fundamentals ;;
    financial-statements) target=financial_statements ;;
    risk-position)        target=risk_position ;;
    debate-panel)         target=debate ;;
    backtest)             target=backtest ;;
  esac
  curl -sL $BASE/modules/$f.md -o $ROOT/modules/$target.md
done

for p in buffett munger graham fisher lynch wood burry druckenmiller; do
  curl -sL $BASE/modules/investors/$p.md -o $ROOT/investors/$p.md
done
```

- [ ] **Step 2: Write README documenting provenance**

`src/research/prompts/README.md`:

```markdown
# Vendored Prompts

These markdown files are vendored verbatim from
https://github.com/Jelly13124/stock-analyze-skills (commit at time of vendor).

Refresh by re-running the fetch script in Phase 4 plan Task 1 Step 1.

Loaded at runtime by `src/research/sections/*.py` and
`src/research/personas/*.py` via `Path(__file__).parent.parent / "prompts"`.

Do NOT edit in place — edit upstream and re-vendor. If our use diverges
from upstream intent, fork by renaming the file (e.g. `technical_ours.md`)
to make the divergence explicit.
```

- [ ] **Step 3: Verify the fetch landed**

```bash
ls src/research/prompts/modules/ src/research/prompts/investors/
wc -l src/research/prompts/*.md src/research/prompts/modules/*.md src/research/prompts/investors/*.md | tail -5
```
Expected: 2 root files, 10 modules, 8 investors, ~2800 lines total.

- [ ] **Step 4: Commit**

```bash
git add src/research/prompts/
git commit -m "feat(research): vendor stock-analyze-skills prompts into repo

Phase 4 source corpus. Files copied verbatim from
github.com/Jelly13124/stock-analyze-skills/stock-analysis/. Refresh
procedure in src/research/prompts/README.md.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Vendor the HTML template

**Files:**
- Replace: `src/research/templates/report.html`

- [ ] **Step 1: Fetch and stage**

```bash
curl -sL https://raw.githubusercontent.com/Jelly13124/stock-analyze-skills/main/stock-analysis/references/report-template.html \
  -o src/research/templates/report.html
```

- [ ] **Step 2: Audit placeholders**

```bash
grep -oE '\{\{[A-Z_]+\}\}' src/research/templates/report.html | sort -u
```
Expected: list of `{{TICKER}}`, `{{REPORT_DATETIME}}`, `{{QUOTE_TIMESTAMP}}`, `{{FILING_DATE}}`, `{{CHART_WINDOW}}`, `{{DEPTH}}`, `{{OBJECTIVE}}`, `{{POSITION_BUDGET_OR_NA}}`, `{{SCORE}}`, etc. Copy this list — Task 11 (html_render) needs it.

- [ ] **Step 3: Convert placeholders to Jinja syntax**

The skill uses `{{PLACEHOLDER}}`; Jinja uses `{{ placeholder }}`. Replace:

```bash
python -c "
import re
from pathlib import Path
p = Path('src/research/templates/report.html')
src = p.read_text(encoding='utf-8')
out = re.sub(r'\{\{([A-Z_]+)\}\}', lambda m: '{{ ' + m.group(1).lower() + ' }}', src)
p.write_text(out, encoding='utf-8')
print('placeholders converted to jinja lowercase')
"
```

Also any `{{PLACEHOLDER_HTML_BLOCK}}` (HTML payloads that must NOT be auto-escaped) needs `|safe` filter added by hand after this pass. Section blocks like the Evidence Ledger table body, scenarios table body, etc., are HTML strings produced by the renderer — they get `|safe`. Identify them by grep and edit:

```bash
grep -n '{{ [a-z_]*_html\|{{ [a-z_]*_table\|{{ [a-z_]*_block' src/research/templates/report.html
```
For each match, change `{{ x }}` to `{{ x|safe }}`.

- [ ] **Step 4: Sanity-load with Jinja**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -c "
from jinja2 import Environment, FileSystemLoader, select_autoescape
env = Environment(loader=FileSystemLoader('src/research/templates'), autoescape=select_autoescape(['html']))
t = env.get_template('report.html')
print('OK — template parsed; vars:', sorted(t.module.__dict__))
"
```
Expected: no Jinja syntax error.

- [ ] **Step 5: Commit**

```bash
git add src/research/templates/report.html
git commit -m "feat(research): vendor skill HTML template

Replaces the minimal Phase 3 template with the full SOP layout:
inline CSS vars, dark-mode via prefers-color-scheme, bull/bear/neutral
pills, score badge, callout, collapsible details, print stylesheet.
Placeholders converted from {{UPPER}} to Jinja {{ lower }}; HTML-
payload placeholders marked |safe.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: AnalyzeRequest + AnalyzeReport dataclasses

**Files:**
- Modify: `src/research/models.py` (append new types; keep Phase 1-2 types)
- Create: `tests/research/test_models_phase4.py`

- [ ] **Step 1: Write failing test**

`tests/research/test_models_phase4.py`:

```python
from src.research.models import (
    AnalyzeRequest, AnalyzeReport, SectionPayload, BacktestVerdict,
    SECTION_ORDER,
)


def test_analyze_request_has_required_fields():
    req = AnalyzeRequest(
        ticker="NVDA",
        objective="medium_term",
        position_budget_usd=10000,
        already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced",
        use_personas=True,
        included_sections=set(SECTION_ORDER),
    )
    assert req.ticker == "NVDA"
    assert "executive_summary" in req.included_sections


def test_section_order_has_15_canonical_sections():
    expected = {
        "data_health", "executive_summary", "evidence_ledger",
        "macro", "sector", "company_fundamentals", "financial_statements",
        "valuation", "technical", "risk_position", "scenarios",
        "conviction", "event_risk", "debate", "final_strategy",
        "missing_data",
    }
    assert set(SECTION_ORDER) == expected
    # order matters — data_health first, missing_data last
    assert SECTION_ORDER[0] == "data_health"
    assert SECTION_ORDER[-1] == "missing_data"


def test_section_payload_shape():
    p = SectionPayload(
        name="macro",
        markdown="# Macro\n\nUp regime.",
        structured=None,
        skipped=False,
        persona_used=None,
    )
    assert p.name == "macro"
    assert p.skipped is False


def test_analyze_report_assembles_sections():
    sections = {
        "data_health": SectionPayload(name="data_health", markdown="ok", structured=None, skipped=False, persona_used=None),
    }
    rep = AnalyzeReport(
        request=AnalyzeRequest(
            ticker="X", objective="general_research",
            position_budget_usd=None, already_holds=False, cost_basis_usd=None,
            risk_tolerance="balanced", use_personas=False,
            included_sections={"data_health"},
        ),
        sections=sections,
        persona_assignments=None,
        backtest=None,
        rendered_html=None,
    )
    assert rep["sections"]["data_health"].name == "data_health"


def test_backtest_verdict_shape():
    v = BacktestVerdict(
        signal="rsi_oversold",
        window_start="2020-01-01", window_end="2026-05-22",
        n_signals=42, win_rate_20d=0.55, avg_return_20d=0.018,
        t_stat=1.7, significant=False,
        verdict="weak edge; not significant at p<0.05",
    )
    assert v.signal == "rsi_oversold"
```

- [ ] **Step 2: Run, expect ImportError**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_models_phase4.py -v
```

- [ ] **Step 3: Append to `src/research/models.py`**

Read the file first (Phase 1 dataclasses live there). Add at the END:

```python


# ===========================================================================
# Phase 4 — SOP-driven analyze pipeline
# ===========================================================================

from dataclasses import dataclass, field
from typing import Literal, Any, TypedDict

Objective = Literal[
    "target_price", "short_term", "medium_term", "long_term",
    "earnings_review", "general_research",
]
RiskBand = Literal["conservative", "balanced", "aggressive"]


# Canonical SOP section order. Section runners are dispatched in this
# order so that downstream sections can read upstream payloads (e.g.
# Executive Summary reads Evidence Ledger; Scenarios reads Valuation).
SECTION_ORDER: list[str] = [
    "data_health",
    "executive_summary",
    "evidence_ledger",
    "macro",
    "sector",
    "company_fundamentals",
    "financial_statements",
    "valuation",
    "technical",
    "risk_position",
    "scenarios",
    "conviction",
    "event_risk",
    "debate",
    "final_strategy",
    "missing_data",
]


@dataclass
class AnalyzeRequest:
    """User-supplied parameters for a full SOP run.

    Mirrors the skill's combined-question gate. ``included_sections``
    drives the flow-style module picker; sections not listed are
    rendered as 'n/a — user excluded'.
    """
    ticker: str
    objective: Objective
    position_budget_usd: float | None
    already_holds: bool
    cost_basis_usd: float | None
    risk_tolerance: RiskBand
    use_personas: bool
    included_sections: set[str] = field(default_factory=lambda: set(SECTION_ORDER))


@dataclass
class SectionPayload:
    """One SOP section's output. ``structured`` is section-specific
    (e.g. Evidence Ledger emits a list[dict]; Scenarios emits a dict
    with bear/base/bull; most prose sections leave it None)."""
    name: str
    markdown: str
    structured: Any | None
    skipped: bool
    persona_used: str | None
    skip_reason: str | None = None


@dataclass
class BacktestVerdict:
    """Output of the technical-signal backtest, embedded inside the
    Technical Analysis section under 'Backtest Validation'."""
    signal: str
    window_start: str
    window_end: str
    n_signals: int
    win_rate_20d: float | None
    avg_return_20d: float | None
    t_stat: float | None
    significant: bool
    verdict: str


class AnalyzeReport(TypedDict, total=False):
    """End-to-end output of sop_orchestrator.run_sop."""
    request: AnalyzeRequest
    sections: dict[str, SectionPayload]
    persona_assignments: dict | None
    backtest: BacktestVerdict | None
    rendered_html: str | None
```

- [ ] **Step 4: Run, expect 5/5 pass**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_models_phase4.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/models.py tests/research/test_models_phase4.py
git commit -m "feat(research): AnalyzeRequest + AnalyzeReport + SectionPayload

Phase 4 data shape. SECTION_ORDER pins the 16 SOP slots (15 sections
+ technical backtest is a sub-section). AnalyzeRequest captures the
combined-question gate; included_sections drives the module picker.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Section ABC + registry

**Files:**
- Create: `src/research/sections/__init__.py`
- Create: `src/research/sections/base.py`
- Create: `tests/research/test_section_base.py`

- [ ] **Step 1: Write failing test**

```python
"""Section ABC + SECTION_REGISTRY contract."""

from __future__ import annotations

import pytest

from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext


class TestSectionBase:
    def test_section_is_abstract(self):
        with pytest.raises(TypeError):
            Section()  # type: ignore[abstract]

    def test_registry_starts_empty(self):
        # Phase 4 Task 4 creates the registry; individual sections
        # register themselves in later tasks. Empty here is correct.
        assert isinstance(SECTION_REGISTRY, dict)

    def test_section_context_holds_what_runner_passes(self):
        from src.research.models import AnalyzeRequest
        from src.research.shared_data import SharedData

        req = AnalyzeRequest(
            ticker="X", objective="general_research",
            position_budget_usd=None, already_holds=False, cost_basis_usd=None,
            risk_tolerance="balanced", use_personas=False,
        )
        shared = SharedData(
            ticker="X", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        ctx = SectionContext(
            request=req, shared=shared, persona=None, prior={},
        )
        assert ctx.request.ticker == "X"
        assert ctx.shared.ticker == "X"
```

- [ ] **Step 2: Run, expect ImportError**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_section_base.py -v
```

- [ ] **Step 3: Implement**

`src/research/sections/base.py`:

```python
"""SOP Section abstract base + execution context.

Each Section is a self-contained LLM runner: it builds its own prompt
from the SectionContext (request + shared data + earlier sections'
outputs), calls call_research_llm, and emits a SectionPayload. The
orchestrator iterates SECTION_ORDER and calls each registered Section.

Sections downstream of upstream ones can read prior outputs via
SectionContext.prior — e.g. ExecutiveSummary reads EvidenceLedger's
structured list before writing its bullet decision-summary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from src.research.models import AnalyzeRequest, SectionPayload
from src.research.shared_data import SharedData


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(relative: str) -> str:
    """Read one of the vendored skill prompt files. Returns the
    markdown text; raises FileNotFoundError if missing (forces a clear
    error rather than a silently empty prompt)."""
    return (_PROMPTS_DIR / relative).read_text(encoding="utf-8")


@dataclass
class SectionContext:
    """Everything a Section runner needs to produce its payload."""
    request: AnalyzeRequest
    shared: SharedData
    persona: str | None
    prior: dict[str, SectionPayload]


class Section(ABC):
    """Abstract SOP section runner.

    Subclasses override:
      * ``name`` — matches SECTION_ORDER entries
      * ``supports_personas`` — list of persona names that can shade
        this section (most sections empty; fundamentals/valuation/
        risk_position support personas, matching Phase 2)
      * ``run(ctx)`` — produce SectionPayload
    """
    name: str = "base"
    supports_personas: list[str] = []

    @abstractmethod
    def run(self, ctx: SectionContext) -> SectionPayload:
        ...
```

`src/research/sections/__init__.py`:

```python
"""SOP section registry. Each concrete Section subclass registers
itself by adding to SECTION_REGISTRY at import time.

The orchestrator imports this module and dispatches in SECTION_ORDER
(from src.research.models), looking up each name in SECTION_REGISTRY.
Missing entries → 'n/a — not implemented' SectionPayload, so partial
delivery is acceptable during the Phase 4 rollout.
"""

from __future__ import annotations

from src.research.sections.base import Section

SECTION_REGISTRY: dict[str, Section] = {}

__all__ = ["SECTION_REGISTRY", "Section"]
```

- [ ] **Step 4: Run, expect 3/3 pass**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_section_base.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/sections/ tests/research/test_section_base.py
git commit -m "feat(research): Section ABC + SECTION_REGISTRY + SectionContext

Phase 4 plumbing. load_prompt() reads vendored markdown from
src/research/prompts/. SectionContext carries request + shared data
+ prior section outputs so downstream sections can read upstream.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: DataHealthSection (Section #1 — exemplar)

**Files:**
- Create: `src/research/sections/data_health.py`
- Create: `tests/research/test_section_data_health.py`

DataHealth is deterministic — it inspects `SharedData` to report which inputs are present, fresh, or missing. No LLM call. Ships first as the canonical example of a Section subclass.

- [ ] **Step 1: Write failing test**

```python
from unittest.mock import patch
from src.research.models import AnalyzeRequest
from src.research.sections.base import SectionContext
from src.research.sections.data_health import DataHealthSection
from src.research.shared_data import SharedData


def _req():
    return AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=False,
    )


def _shared(**overrides):
    base = dict(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[1, 2, 3], financials=[1], insider_trades=[1],
        news=[1], analyst_actions=[1], analyst_targets={"target": 200},
        earnings_history=[1], company_facts={"sector": "Tech"},
        sector_etf_prices=[1, 2], spy_prices=[1, 2],
    )
    base.update(overrides)
    return SharedData(**base)


def test_emits_data_health_section():
    ctx = SectionContext(request=_req(), shared=_shared(), persona=None, prior={})
    out = DataHealthSection().run(ctx)
    assert out.name == "data_health"
    assert out.skipped is False
    # Table-style markdown with every required row
    for row in ("Quote", "Daily chart", "Financials", "Macro", "Sector", "News"):
        assert row in out.markdown


def test_marks_missing_inputs():
    ctx = SectionContext(request=_req(), shared=_shared(prices=[], news=[]), persona=None, prior={})
    out = DataHealthSection().run(ctx)
    # missing prices/news should be flagged
    assert "missing" in out.markdown.lower() or "unavailable" in out.markdown.lower()
```

- [ ] **Step 2: Run, expect ImportError**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_section_data_health.py -v
```

- [ ] **Step 3: Implement**

`src/research/sections/data_health.py`:

```python
"""DataHealth — deterministic section that inspects SharedData and
reports which inputs are present/fresh/missing. No LLM call.

Output: markdown table with rows matching the SOP Data Health spec
(Quote, Daily/Weekly chart, Financials, Macro, Sector, News).
"""

from __future__ import annotations

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext


def _row(item: str, present: bool, source: str, notes: str = "") -> str:
    status = "OK" if present else "missing"
    return f"| {item} | {status} | {source} | {notes} |"


class DataHealthSection(Section):
    name = "data_health"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        s = ctx.shared
        rows = [
            "| Item | Status | Source | Notes |",
            "|---|---|---|---|",
            _row("Quote", bool(s.prices), "v2/data", f"{len(s.prices)} bars"),
            _row("Daily chart / indicators", len(s.prices) >= 50, "v2/data",
                 f"{len(s.prices)} daily bars"),
            _row("Weekly chart / indicators", len(s.prices) >= 250, "v2/data (resampled)",
                 ""),
            _row("Financials / filings", bool(s.financials), "v2/data",
                 f"{len(s.financials)} periods"),
            _row("Earnings release / transcript", bool(s.earnings_history), "v2/data",
                 f"{len(s.earnings_history)} earnings"),
            _row("Macro data", bool(s.spy_prices), "SPY proxy",
                 f"{len(s.spy_prices)} SPY bars"),
            _row("Sector / peer data", bool(s.sector_etf_prices), "Sector ETF",
                 f"{len(s.sector_etf_prices)} bars"),
            _row("News / catalysts", bool(s.news), "v2/data",
                 f"{len(s.news)} items"),
            _row("Insider trades", bool(s.insider_trades), "v2/data",
                 f"{len(s.insider_trades)} trades"),
            _row("Analyst actions", bool(s.analyst_actions), "v2/data",
                 f"{len(s.analyst_actions)} actions"),
        ]
        md = "## Data Health\n\n" + "\n".join(rows) + "\n"
        return SectionPayload(
            name=self.name, markdown=md, structured=None,
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["data_health"] = DataHealthSection()
```

- [ ] **Step 4: Run, expect 2/2 pass**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_section_data_health.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/sections/data_health.py tests/research/test_section_data_health.py
git commit -m "feat(research): DataHealthSection (deterministic, no LLM)

First Section subclass. Inspects SharedData; produces the SOP Data
Health markdown table. Self-registers in SECTION_REGISTRY.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: LLM section runner helper

**Files:** Create `src/research/sections/_llm_runner.py` + `tests/research/test_llm_section_runner.py`

Most prose sections share: load prompt → maybe prepend persona → call LLM → wrap as SectionPayload. Extract once so sections stay small.

- [ ] **Step 1: Test** — `tests/research/test_llm_section_runner.py` with 3 tests: returns SectionPayload with markdown+heading; persona_used recorded when ctx.persona set; returns skipped=True on exception.

- [ ] **Step 2: Implement** `src/research/sections/_llm_runner.py`:

```python
"""Shared LLM dispatch for SOP sections."""

from __future__ import annotations
import logging
from typing import TypeVar
from pydantic import BaseModel

from src.research.llm import call_research_llm
from src.research.models import SectionPayload
from src.research.personas import PERSONA_REGISTRY
from src.research.sections.base import SectionContext

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def run_llm_section(
    *, section_name: str, ctx: SectionContext,
    prompt: str, output_model: type[T], markdown_heading: str,
) -> SectionPayload:
    final = prompt
    persona_used: str | None = None
    if ctx.persona is not None:
        p = PERSONA_REGISTRY.get(ctx.persona)
        if p is not None:
            final = (p.system_addition() + "\n\n"
                     + p.module_lens(section_name) + "\n\n" + prompt)
            persona_used = ctx.persona
    try:
        r = call_research_llm(
            final, output_model,
            default_factory=lambda: output_model(
                narrative=f"LLM call failed for {section_name}."
            ),
        )
        narrative = getattr(r, "narrative", "") or ""
        return SectionPayload(
            name=section_name,
            markdown=f"{markdown_heading}\n\n{narrative}\n",
            structured=r.model_dump(),
            skipped=False, persona_used=persona_used,
        )
    except Exception as e:
        logger.exception("section %s raised: %s", section_name, e)
        return SectionPayload(
            name=section_name,
            markdown=f"{markdown_heading}\n\n_section unavailable: {e}_\n",
            structured=None, skipped=True, persona_used=persona_used,
            skip_reason=str(e),
        )
```

- [ ] **Step 3: Run + commit** — `feat(research): shared LLM section runner helper`

---

## Tasks 7-11: Prose sections (Macro, Sector, CompanyFundamentals, FinancialStatements, Valuation+Technical+RiskPosition)

Each section follows the same template — one file per section, one test per section. Variations captured per-task below.

### Section template (use for all five tasks)

`src/research/sections/<name>.py`:

```python
"""<Name> — runs the skill's <name> module prompt."""

from __future__ import annotations
from pydantic import BaseModel, Field

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(description="markdown section body")


_SYSTEM_PROMPT = load_prompt("modules/<name>.md")


class <Class>Section(Section):
    name = "<name>"
    supports_personas = <PERSONAS_LIST>

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + <PER_SECTION_CONTEXT>
            + "\n\n--- YOUR TASK ---\n<TASK_STRING>"
        )
        return run_llm_section(
            section_name=self.name, ctx=ctx, prompt=user_prompt,
            output_model=_Narrative, markdown_heading="## <Heading>",
        )


SECTION_REGISTRY["<name>"] = <Class>Section()
```

Test template (per section):

```python
from unittest.mock import patch
from src.research.models import AnalyzeRequest
from src.research.sections.<name> import <Class>Section, _Narrative
from src.research.sections.base import SectionContext
from src.research.shared_data import SharedData


def _ctx(persona=None):
    req = AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=bool(persona),
    )
    shared = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={"sector": "Tech"},
        sector_etf_prices=[], spy_prices=[],
    )
    return SectionContext(request=req, shared=shared, persona=persona, prior={})


@patch("src.research.sections._llm_runner.call_research_llm")
def test_emits_section(mock_llm):
    mock_llm.return_value = _Narrative(narrative="body text.")
    out = <Class>Section().run(_ctx())
    assert out.name == "<name>"
    assert "<Heading>" in out.markdown
    assert "body text" in out.markdown
```

### Task 7: MacroSection

- `<name>` = `macro`, `<Class>` = `Macro`, `<Heading>` = `Macro Regime`
- `<PERSONAS_LIST>` = `["druckenmiller"]`
- `<PER_SECTION_CONTEXT>` = `f"SPY bars available: {len(ctx.shared.spy_prices)}\\n"`
- `<TASK_STRING>` = `"Write a 250-400 word Macro Regime section per the spec. Output as 'narrative' field — markdown body without the heading. Reference SPY trend, rate regime, liquidity, and implication for valuation multiple + stop width on this ticker."`
- Commit: `feat(research): MacroSection`

### Task 8: SectorSection

- `<name>` = `sector`, `<Class>` = `Sector`, `<Heading>` = `Sector and Peer Comparison`, `<PERSONAS_LIST>` = `[]`
- `<PER_SECTION_CONTEXT>`:
  ```python
  (f"Sector ETF bars: {len(ctx.shared.sector_etf_prices)}\n"
   f"SPY bars: {len(ctx.shared.spy_prices)}\n"
   f"Sector: {(ctx.shared.company_facts or {}).get('sector', 'Unknown')}\n")
  ```
- `<TASK_STRING>` = `"Write 280-450 words. Cover sector ETF proxy, 20-day relative strength vs SPY and sector, peer growth/margin/valuation, sector catalysts/headwinds, premium/discount."`
- Commit: `feat(research): SectorSection`

### Task 9: CompanyFundamentalsSection (DEEPEST — 700-1100 words)

- `<name>` = `company_fundamentals`, `<Class>` = `CompanyFundamentals`, `<Heading>` = `Company Fundamentals`
- `<PERSONAS_LIST>` = `["buffett", "munger", "fisher"]`
- `<PER_SECTION_CONTEXT>`: serialize metrics from `ctx.shared.financials[0]`:
  ```python
  _metrics_block(ctx)  # helper at module top:
  def _metrics_block(ctx):
      if not ctx.shared.financials:
          return "No financial metrics available.\n"
      latest = ctx.shared.financials[0]
      keys = ("revenue_growth", "gross_margin", "operating_margin",
              "net_margin", "return_on_invested_capital",
              "free_cash_flow_yield", "debt_to_equity")
      lines = []
      for k in keys:
          v = getattr(latest, k, None)
          if v is not None:
              lines.append(f"  {k}: {float(v):.4f}")
      return "Latest metrics:\n" + ("\n".join(lines) or "  (none)") + "\n"
  ```
- `<TASK_STRING>` = `"Write the DEEPEST section (700-1100 words). Use markdown subsections (### Core investment question, ### Business and segment map, ### Revenue model and unit economics, ### Industry structure, ### Customer/segment exposure, ### Moat and competitors, ### Strategic catalysts, ### Management and capital allocation, ### Financial translation, ### Thesis breakers, ### Evidence gaps). Anchor every claim on metrics above."`
- Commit: `feat(research): CompanyFundamentalsSection (deepest section)`

### Task 10: FinancialStatementsSection (2nd deepest — 600-950 words)

- `<name>` = `financial_statements`, `<Class>` = `FinancialStatements`, `<Heading>` = `Financial Statement Review`, `<PERSONAS_LIST>` = `[]`
- `<PER_SECTION_CONTEXT>`: serialize last 4 quarters from `ctx.shared.earnings_history` (steal from `src/research/modules/financials.py`):
  ```python
  _earnings_block(ctx)  # helper:
  def _earnings_block(ctx):
      rows = []
      for er in (ctx.shared.earnings_history or [])[:4]:
          q = getattr(er, "quarterly", None)
          if q is None:
              continue
          rows.append(
              f"  {getattr(er, 'period', '?')}: "
              f"rev={getattr(q, 'revenue', None)}, "
              f"ni={getattr(q, 'net_income', None)}, "
              f"fcf={getattr(q, 'free_cash_flow', None)}"
          )
      return "Earnings history (newest first):\n" + ("\n".join(rows) or "  (none)") + "\n"
  ```
- `<TASK_STRING>` = `"Write 600-950 words. Cover: reporting period+sources, revenue/margin/EPS trend, balance sheet, cash-flow quality, dilution/SBC, GAAP vs non-GAAP, guidance tone. Include a markdown trend table when data permits."`
- Commit: `feat(research): FinancialStatementsSection (2nd deepest)`

### Task 11: ValuationSection + TechnicalSection + RiskPositionSection (3-in-1 task)

Three sections sharing the template. Single commit at end.

**ValuationSection**: `<name>` = `valuation`, `<Heading>` = `Valuation Analysis`, `<PERSONAS_LIST>` = `["buffett", "graham", "munger", "fisher"]`. Context: PE/PB/PS/EV-EBITDA from `ctx.shared.financials[0]` — steal field names from `src/research/modules/valuation.py`. Task string: `"450-700 words covering current market inputs, relative valuation, intrinsic/scenario math, bear/base/bull assumptions, sensitivity, margin of safety, target range + confidence."`

**TechnicalSection**: `<name>` = `technical`, `<Heading>` = `Technical Analysis`, `<PERSONAS_LIST>` = `[]`. Context: pre-compute RSI(14), SMA50, SMA200, last close, support/resistance from `ctx.shared.prices` — steal from `src/research/modules/technical.py`. Task: `"350-550 words covering daily+weekly trend tables, support/resistance, breakout trigger, stop/invalidation, ATR risk band. The orchestrator appends a Backtest Validation sub-section after your output — leave a placeholder paragraph at the end like 'Backtest validation: see sub-section below.'"`

**RiskPositionSection**: `<name>` = `risk_position`, `<Heading>` = `Risk and Position Sizing`, `<PERSONAS_LIST>` = `["druckenmiller", "burry"]`. Context: pack request fields + prior technical levels:
```python
(f"Position budget: ${ctx.request.position_budget_usd or 'not specified'}\n"
 f"Already holds: {ctx.request.already_holds}\n"
 f"Cost basis: ${ctx.request.cost_basis_usd or 'n/a'}\n"
 f"Risk tolerance: {ctx.request.risk_tolerance}\n"
 f"Technical stop/target: see prior['technical'] when present\n")
```
Task: `"350-550 words per spec. Compute concrete dollar sizing if budget given. Frame as hold/add/trim/exit if already_holds. Map stop logic to risk_tolerance: conservative ~≤10% drawdown, balanced ~10-20%, aggressive ~25%+."`

Single commit:
```bash
git add src/research/sections/{valuation,technical,risk_position}.py \
        tests/research/test_section_{valuation,technical,risk_position}.py
git commit -m "feat(research): Valuation+Technical+RiskPosition sections

Three prose sections sharing the LLM runner template. Persona-aware
per Phase 2 mapping. Technical reserves a Backtest Validation
sub-section that the orchestrator fills.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: Structured-output sections (EvidenceLedger, Scenarios, Conviction)

These three sections produce structured data (lists/dicts) AND markdown. They differ from prose sections in their pydantic output model — fields beyond `narrative`.

### EvidenceLedgerSection

- File: `src/research/sections/evidence_ledger.py`
- Pydantic model:
  ```python
  class _Evidence(BaseModel):
      claim: str; evidence: str; source: str; date: str
      direction: Literal["bullish", "bearish", "neutral", "missing"]
      confidence: Literal["high", "medium", "low"]

  class _LedgerOut(BaseModel):
      narrative: str = ""  # ledger has no prose body, just the table
      items: list[_Evidence] = Field(min_length=10,
          description="At least 10 items per SOP minimum gate")
  ```
- Override `_llm_runner` because the markdown is a TABLE not prose. Implementation does its own try/except + builds the markdown table from `items`:
  ```python
  def run(self, ctx):
      prompt = (...assemble from ctx.prior...)
      try:
          out = call_research_llm(prompt, _LedgerOut,
              default_factory=lambda: _LedgerOut(items=[]))
      except Exception as e:
          return SectionPayload(name=self.name, markdown="## Evidence Ledger\n\n_unavailable_",
              structured=None, skipped=True, persona_used=None, skip_reason=str(e))
      rows = ["| Claim | Evidence | Source | Date | Direction | Confidence |",
              "|---|---|---|---|---|---|"]
      for it in out.items:
          rows.append(f"| {it.claim} | {it.evidence} | {it.source} | {it.date} | {it.direction} | {it.confidence} |")
      return SectionPayload(
          name=self.name, markdown="## Evidence Ledger\n\n" + "\n".join(rows),
          structured=[i.model_dump() for i in out.items],
          skipped=False, persona_used=None,
      )
  ```
- Test: mock LLM returning 10 evidence items; assert markdown has table header + 10 rows; assert `structured` is list of dicts.

### ScenariosSection

- File: `src/research/sections/scenarios.py`
- Pydantic:
  ```python
  class _Scenario(BaseModel):
      target_range: str  # e.g. "$140-160"
      time_horizon: str  # "3-6 months"
      key_assumptions: str
      confidence: Literal["high", "medium", "low"]
      invalidation: str

  class _ScenariosOut(BaseModel):
      narrative: str = ""
      bear: _Scenario; base: _Scenario; bull: _Scenario
  ```
- Markdown is a 3-row table with bear/base/bull rows.
- Reads `ctx.prior["valuation"].structured["narrative"]` to base scenarios on the valuation work.

### ConvictionSection

- File: `src/research/sections/conviction.py`
- Pydantic:
  ```python
  class _CategoryScore(BaseModel):
      name: str; weight: int; score: int = Field(ge=0, le=100); rationale: str

  class _ConvictionOut(BaseModel):
      narrative: str = ""  # 120-220 word rationale
      categories: list[_CategoryScore] = Field(min_length=6, max_length=6)
      total_score: int = Field(ge=0, le=100)
  ```
- Six categories per SOP: macro+sector, fundamentals, valuation, technical, risk+event, catalyst+news.
- Weight column uses Phase 4 ScoringFramework: Conservative = (15, 25, 25, 10, 15, 10); Balanced = (15, 25, 20, 15, 15, 10); Aggressive = (10, 20, 20, 25, 15, 10). Select by `ctx.request.risk_tolerance`.
- Markdown: 6-row table + 120-220 word rationale paragraph + `**Score: <total>/100**` (this is the fix for the "always 75" bug — score is computed deterministically from weights × per-category LLM scores, not a single LLM number).

Single commit:
```bash
git add src/research/sections/{evidence_ledger,scenarios,conviction}.py \
        tests/research/test_section_{evidence_ledger,scenarios,conviction}.py
git commit -m "feat(research): structured EvidenceLedger+Scenarios+Conviction sections

Each emits structured pydantic data + a derived markdown table.
ConvictionSection's total_score is computed as sum(weight*score/100)
across 6 categories — fixes the 'always 75' bug from Phase 1-3 where
a single LLM int was the score.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: ExecutiveSummary + EventRisk + Debate + FinalStrategy + MissingData sections

Five thinner sections, one task. ExecutiveSummary + FinalStrategy read prior sections; EventRisk + MissingData are mostly LLM prose; Debate is the Phase 2 debate module wrapped as a Section.

### ExecutiveSummarySection
- Reads `ctx.prior` for: evidence_ledger.structured, scenarios.structured, conviction.structured.
- Pydantic: `_ExecSummaryOut(BaseModel)` with fields: overall_view, main_bullish, main_bearish, target_range, strategy_type, confidence_qualitative ("high"/"medium"/"low"), key_invalidation, narrative.
- Markdown: bullet list per SOP template. `Score: <conviction.total_score>/100` pulled from prior conviction section, NOT re-asked. This is the second fix for the "always 75" bug.

### EventRiskSection
- Pydantic with `narrative` only. Task: `"150-300 words covering upcoming earnings date, macro events in trading window, company-specific events, options IV / gap-risk, effect on confidence."`
- Context: pack next earnings date from `ctx.shared.earnings_history` if present, plus risk_tolerance.

### DebateSection
- Only runs when `ctx.request.use_personas` AND persona-router (Phase 2) picked 2 debate personas. Otherwise emits `SectionPayload(skipped=True, skip_reason="debate disabled")`.
- Uses Phase 2's `src/research/modules/debate.py:run_debate` — that already exists, just wrap as a Section. The wrapper reads `ctx.prior["_persona_assignments"]["debate"]` (assignments stored under a magic key by the orchestrator).
- Markdown: heading + transcript + verdict, identical to Phase 2 debate output.

### FinalStrategySection
- Reads `ctx.prior` for: evidence_ledger, scenarios, conviction, risk_position.
- Pydantic with `narrative` only. Task: `"280-450 words. Split into ### Short-term, ### Medium-term, ### Long-term sub-sections. List watch levels, stop/invalidation logic, what would change the view, and 3-5 monitoring items."`

### MissingDataSection
- Deterministic. Walks `ctx.prior` for any `SectionPayload(skipped=True)` and lists each in a table: section name, skip_reason, impact (qualitative), fallback used.
- No LLM call (mirrors DataHealth's pattern from Task 5).

Commit:
```bash
git add src/research/sections/{executive_summary,event_risk,debate,final_strategy,missing_data}.py \
        tests/research/test_section_{executive_summary,event_risk,debate,final_strategy,missing_data}.py
git commit -m "feat(research): 5 closing sections (ExecutiveSummary/EventRisk/Debate/FinalStrategy/MissingData)

ExecutiveSummary + FinalStrategy read prior sections for coherence;
the score is pulled from ConvictionSection, not re-asked — fixes the
'always 75' bug. Debate wraps Phase 2's run_debate. MissingData is
deterministic — walks prior payloads for skipped=True.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: Technical-signal backtest (replaces detector-replay)

**Files:** Create `src/research/backtest_signal.py` + `tests/research/test_backtest_signal.py`

Replaces Phase 1's `src/research/modules/detector_backtest.py`. Computes 2-3 simple technical signals on the daily price history, measures forward 20-day returns + win rate + t-stat, returns a `BacktestVerdict` (Task 3).

- [ ] **Step 1: Failing test**

```python
import numpy as np
from src.research.backtest_signal import run_signal_backtest
from src.research.shared_data import SharedData


def _shared(n=500):
    # synthetic random-walk price series
    rng = np.random.default_rng(42)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return SharedData(
        ticker="X", scan_date="2026-05-22",
        prices=[{"open": p, "close": p, "high": p, "low": p, "volume": 1e6, "time": str(i)}
                for i, p in enumerate(px)],
        financials=[], insider_trades=[], news=[], analyst_actions=[],
        analyst_targets=None, earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


def test_returns_backtest_verdict_for_rsi_oversold():
    out = run_signal_backtest(_shared(), signal="rsi_oversold")
    assert out.signal == "rsi_oversold"
    assert out.n_signals >= 0
    assert out.window_start and out.window_end


def test_insufficient_data_returns_zero_signals():
    out = run_signal_backtest(_shared(n=20), signal="rsi_oversold")
    assert out.n_signals == 0
    assert "insufficient" in out.verdict.lower() or out.n_signals == 0


def test_picks_best_signal_when_signal_arg_is_auto():
    out = run_signal_backtest(_shared(), signal="auto")
    assert out.signal in {"rsi_oversold", "sma50_cross_up", "macd_bullish_cross"}
```

- [ ] **Step 2: Implement** `src/research/backtest_signal.py`:

```python
"""Technical-signal backtest. Three built-in signals:
  - rsi_oversold: RSI(14) crossed up from <30
  - sma50_cross_up: close crossed above SMA(50)
  - macd_bullish_cross: MACD line crossed above signal line

For each signal occurrence at day t, measure return = close[t+20]/close[t] - 1.
Aggregate: n_signals, win_rate (% of forward returns > 0), avg_return, t-stat
against zero-mean null. Verdict text per overfit/insufficient/significant rules.
"""

from __future__ import annotations
import math
from datetime import date

from src.research.models import BacktestVerdict
from src.research.shared_data import SharedData


def _closes(shared):
    out = []
    for p in shared.prices or []:
        c = p.get("close") if isinstance(p, dict) else getattr(p, "close", None)
        if c is not None:
            out.append(float(c))
    return out


def _rsi(closes, period=14):
    """Wilder's RSI, returns list aligned with closes (NaN for first period)."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    out = [None] * period
    for i in range(period, len(closes)):
        if i > period:
            avg_g = (avg_g * (period - 1) + gains[i-1]) / period
            avg_l = (avg_l * (period - 1) + losses[i-1]) / period
        rs = avg_g / avg_l if avg_l > 0 else float("inf")
        rsi = 100 - 100 / (1 + rs)
        out.append(rsi)
    out.append(out[-1] if out else None)  # align length
    return out[:len(closes)]


def _sma(closes, n):
    out = [None] * len(closes)
    if len(closes) >= n:
        for i in range(n - 1, len(closes)):
            out[i] = sum(closes[i - n + 1: i + 1]) / n
    return out


def _ema(closes, n):
    if len(closes) < n:
        return [None] * len(closes)
    k = 2 / (n + 1)
    out = [None] * (n - 1)
    sma = sum(closes[:n]) / n
    out.append(sma)
    prev = sma
    for c in closes[n:]:
        prev = c * k + prev * (1 - k)
        out.append(prev)
    return out


def _signal_indices(closes, signal):
    n = len(closes)
    idx = []
    if signal == "rsi_oversold":
        r = _rsi(closes)
        for i in range(1, n):
            if r[i-1] is not None and r[i] is not None and r[i-1] < 30 <= r[i]:
                idx.append(i)
    elif signal == "sma50_cross_up":
        s = _sma(closes, 50)
        for i in range(1, n):
            if s[i-1] is not None and s[i] is not None:
                if closes[i-1] < s[i-1] and closes[i] >= s[i]:
                    idx.append(i)
    elif signal == "macd_bullish_cross":
        e12 = _ema(closes, 12); e26 = _ema(closes, 26)
        if not e12 or not e26:
            return []
        macd = [(a - b) if (a is not None and b is not None) else None
                for a, b in zip(e12, e26)]
        sig = _ema([m for m in macd if m is not None], 9)
        # align sig back to full length
        offset = next((i for i, v in enumerate(macd) if v is not None), 0)
        sig_full = [None] * offset + sig
        for i in range(1, n):
            if i >= len(sig_full): break
            if (macd[i-1] is not None and sig_full[i-1] is not None
                    and macd[i] is not None and sig_full[i] is not None):
                if macd[i-1] < sig_full[i-1] and macd[i] >= sig_full[i]:
                    idx.append(i)
    return idx


def _forward_returns(closes, idx, horizon=20):
    out = []
    for i in idx:
        if i + horizon < len(closes):
            out.append(closes[i + horizon] / closes[i] - 1)
    return out


def _t_stat(returns):
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else None
    return mean / se if se else None


_AVAILABLE = ("rsi_oversold", "sma50_cross_up", "macd_bullish_cross")


def run_signal_backtest(shared: SharedData, signal: str = "auto",
                         horizon: int = 20) -> BacktestVerdict:
    closes = _closes(shared)
    if not closes:
        return BacktestVerdict(
            signal=signal, window_start=shared.scan_date, window_end=shared.scan_date,
            n_signals=0, win_rate_20d=None, avg_return_20d=None, t_stat=None,
            significant=False,
            verdict="insufficient data — no price history",
        )

    candidates = _AVAILABLE if signal == "auto" else (signal,)
    best = None
    for sig in candidates:
        idx = _signal_indices(closes, sig)
        rets = _forward_returns(closes, idx, horizon)
        if not rets:
            continue
        wr = sum(1 for r in rets if r > 0) / len(rets)
        avg = sum(rets) / len(rets)
        t = _t_stat(rets)
        score = (t or 0) * math.sqrt(len(rets))
        if best is None or score > best[0]:
            best = (score, sig, len(rets), wr, avg, t)

    if best is None:
        return BacktestVerdict(
            signal=signal if signal != "auto" else "rsi_oversold",
            window_start=shared.scan_date, window_end=shared.scan_date,
            n_signals=0, win_rate_20d=None, avg_return_20d=None, t_stat=None,
            significant=False,
            verdict=f"no signal occurrences for {signal} in available history",
        )

    _, sig, n, wr, avg, t = best
    significant = (t is not None and abs(t) >= 1.96)
    verdict = (f"signal '{sig}' fired {n} times; "
               f"avg {horizon}d return {avg*100:+.2f}%, win rate {wr*100:.0f}%, "
               f"t={t:.2f}; "
               + ("significant at p<0.05" if significant
                  else "NOT significant at p<0.05 — weak edge"))

    return BacktestVerdict(
        signal=sig,
        window_start=str(date.today().replace(year=date.today().year - 5)),
        window_end=shared.scan_date,
        n_signals=n, win_rate_20d=wr, avg_return_20d=avg,
        t_stat=t, significant=significant, verdict=verdict,
    )
```

- [ ] **Step 3: Run + commit**

```bash
git add src/research/backtest_signal.py tests/research/test_backtest_signal.py
git commit -m "feat(research): technical-signal backtest

Replaces detector-replay. Three built-in signals (RSI oversold,
SMA50 cross-up, MACD bullish cross). For each occurrence, measures
forward 20-day return; aggregates win-rate + avg + t-stat against
zero mean. 'auto' picks the signal with highest |t|*sqrt(n).
Verdict honors p<0.05 significance gate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 15: SOP orchestrator (replaces synthesizer)

**Files:** Create `src/research/sop_orchestrator.py` + `tests/research/test_sop_orchestrator.py`

Dispatches sections in SECTION_ORDER. Runs router first when `use_personas=True`. Runs backtest before Technical section so Technical can reference it. Appends Backtest Validation sub-section to Technical's markdown before final assembly.

- [ ] **Step 1: Test**

```python
"""End-to-end orchestrator with stubbed sections + LLM."""

from unittest.mock import patch, MagicMock
from src.research.models import (
    AnalyzeRequest, AnalyzeReport, SectionPayload, BacktestVerdict,
    SECTION_ORDER,
)
from src.research.sop_orchestrator import run_sop


def _req(use_personas=False, included=None):
    return AnalyzeRequest(
        ticker="NVDA", objective="medium_term",
        position_budget_usd=10000, already_holds=False, cost_basis_usd=None,
        risk_tolerance="balanced", use_personas=use_personas,
        included_sections=included or set(SECTION_ORDER),
    )


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_runs_all_sections_in_order(mock_bt, mock_registry, mock_fetch):
    from src.research.shared_data import SharedData
    mock_fetch.return_value = SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    mock_bt.return_value = BacktestVerdict(
        signal="rsi_oversold", window_start="2020-01-01",
        window_end="2026-05-22", n_signals=10, win_rate_20d=0.6,
        avg_return_20d=0.02, t_stat=2.1, significant=True,
        verdict="significant at p<0.05",
    )

    call_log = []
    class _StubSection:
        def __init__(self, name):
            self.name = name
            self.supports_personas = []
        def run(self, ctx):
            call_log.append(self.name)
            return SectionPayload(
                name=self.name, markdown=f"## {self.name}", structured=None,
                skipped=False, persona_used=None,
            )
    for n in SECTION_ORDER:
        mock_registry[n] = _StubSection(n)

    report = run_sop(_req())
    # Every section ran, in order
    assert call_log == SECTION_ORDER
    assert "data_health" in report["sections"]
    assert report["backtest"].n_signals == 10


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_skips_excluded_sections(mock_bt, mock_registry, mock_fetch):
    from src.research.shared_data import SharedData
    mock_fetch.return_value = SharedData(
        ticker="X", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )
    mock_bt.return_value = BacktestVerdict(
        signal="rsi_oversold", window_start="x", window_end="x",
        n_signals=0, win_rate_20d=None, avg_return_20d=None,
        t_stat=None, significant=False, verdict="x",
    )
    class _Stub:
        def __init__(self, name):
            self.name = name; self.supports_personas = []
        def run(self, ctx):
            return SectionPayload(name=self.name, markdown=f"## {self.name}",
                structured=None, skipped=False, persona_used=None)
    for n in SECTION_ORDER:
        mock_registry[n] = _Stub(n)

    report = run_sop(_req(included={"data_health", "executive_summary"}))
    # Only included sections should have run-output; others get skipped payloads
    assert report["sections"]["macro"].skipped is True
    assert "user excluded" in (report["sections"]["macro"].skip_reason or "").lower()
    assert report["sections"]["data_health"].skipped is False
```

- [ ] **Step 2: Implement** `src/research/sop_orchestrator.py`:

```python
"""Top-level orchestrator for Phase 4 SOP runs."""

from __future__ import annotations

import inspect
import logging

from src.research.backtest_signal import run_signal_backtest
from src.research.models import (
    AnalyzeRequest, AnalyzeReport, SectionPayload, SECTION_ORDER,
)
from src.research.router import route_personas
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import SectionContext
from src.research.shared_data import fetch_shared_data

logger = logging.getLogger(__name__)


def _persona_for(assignments, name):
    if not assignments:
        return None
    v = assignments.get(name)
    return v if isinstance(v, str) else None


def run_sop(request: AnalyzeRequest) -> AnalyzeReport:
    """Run all included sections in SECTION_ORDER. Sections not included
    by the user emit skipped payloads; sections without an implementation
    in SECTION_REGISTRY also emit skipped payloads (graceful Phase 4
    rollout — partial section coverage is OK)."""
    from datetime import date
    scan_date = date.today().isoformat()
    shared = fetch_shared_data(request.ticker, scan_date)

    # Router first when persona-mode is on
    persona_assignments = None
    if request.use_personas:
        try:
            # router.route_personas was built for ResearchRequest; adapt
            from src.research.models import ResearchRequest
            adapter = ResearchRequest(
                ticker=request.ticker, holding_status="watching",
                target_position_pct=0.05, risk_tolerance=request.risk_tolerance,
                report_goal="general_research", use_personas=True,
                scanner_context=None,
            )
            persona_assignments = route_personas(adapter, shared)
        except Exception as e:
            logger.exception("router failed: %s", e)

    # Technical signal backtest — runs once, attached to Technical section
    backtest = None
    try:
        backtest = run_signal_backtest(shared, signal="auto")
    except Exception as e:
        logger.exception("backtest failed: %s", e)

    sections: dict[str, SectionPayload] = {}
    for name in SECTION_ORDER:
        if name not in request.included_sections:
            sections[name] = SectionPayload(
                name=name,
                markdown=f"## {name}\n\n_n/a — user excluded_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason="user excluded this section",
            )
            continue
        runner = SECTION_REGISTRY.get(name)
        if runner is None:
            sections[name] = SectionPayload(
                name=name,
                markdown=f"## {name}\n\n_section not yet implemented_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason="no runner registered",
            )
            continue
        ctx = SectionContext(
            request=request, shared=shared,
            persona=_persona_for(persona_assignments, name),
            prior=dict(sections),
        )
        try:
            payload = runner.run(ctx)
        except Exception as e:
            logger.exception("section %s raised: %s", name, e)
            payload = SectionPayload(
                name=name,
                markdown=f"## {name}\n\n_unavailable: {e}_\n",
                structured=None, skipped=True, persona_used=None,
                skip_reason=f"unhandled exception: {e}",
            )
        sections[name] = payload

    # Attach backtest verdict to Technical section markdown
    if backtest is not None and "technical" in sections and not sections["technical"].skipped:
        tech = sections["technical"]
        bt_md = (
            "\n\n### Backtest Validation\n\n"
            f"Signal tested: **{backtest.signal}**  \n"
            f"Window: {backtest.window_start} → {backtest.window_end}  \n"
            f"Occurrences: {backtest.n_signals}  \n"
        )
        if backtest.win_rate_20d is not None:
            bt_md += (
                f"Win rate (20d): {backtest.win_rate_20d*100:.0f}%  \n"
                f"Avg return (20d): {backtest.avg_return_20d*100:+.2f}%  \n"
                f"t-statistic: {backtest.t_stat:.2f}  \n"
            )
        bt_md += f"\n**Verdict:** {backtest.verdict}\n"
        sections["technical"] = SectionPayload(
            name="technical",
            markdown=tech.markdown + bt_md,
            structured=tech.structured,
            skipped=False, persona_used=tech.persona_used,
        )

    return AnalyzeReport(
        request=request,
        sections=sections,
        persona_assignments=persona_assignments,
        backtest=backtest,
        rendered_html=None,
    )
```

- [ ] **Step 3: Run + commit**

```bash
git add src/research/sop_orchestrator.py tests/research/test_sop_orchestrator.py
git commit -m "feat(research): SOP orchestrator (replaces synthesizer)

run_sop dispatches all SECTION_ORDER sections; user-excluded ones
emit skipped payloads; missing implementations emit skipped (Phase 4
rollout is incremental). Persona router runs first when use_personas.
Technical-signal backtest runs once and is appended as a Backtest
Validation sub-section to Technical's markdown.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 16: HTML render for SOP report

**Files:** Rewrite `src/research/html_render.py` + create `tests/research/test_html_render_sop.py`

Builds the Jinja context from `AnalyzeReport`. Each section's markdown is converted to HTML via the existing `_markdown_to_html` helper from Phase 3. Special handling:
- `evidence_ledger.structured` → renders the `tbody` rows directly into the template's table slot (not via markdown).
- `scenarios.structured` → renders bear/base/bull rows directly.
- `conviction.structured` → renders the 6-row table + total_score directly + drives the `{{ score|safe }}` placeholder in the Executive Summary block.

- [ ] **Step 1: Test** — `tests/research/test_html_render_sop.py` with 4 tests:
  1. `render_sop(AnalyzeReport)` returns a `<!DOCTYPE html>` document.
  2. Ticker appears in title + header.
  3. When a section is skipped, its block renders `n/a — <reason>` (NOT silently omitted).
  4. When conviction structured has total_score=42, the score badge shows `42/100`.

- [ ] **Step 2: Implement** by reusing Phase 3's `_markdown_to_html` + adding `render_sop(report: AnalyzeReport) -> str` function. Pseudo-shape:

```python
def render_sop(report: AnalyzeReport) -> str:
    req = report["request"]
    sections = report["sections"]
    conviction = sections.get("conviction")
    total_score = (conviction.structured or {}).get("total_score", 0) if conviction else 0

    section_blocks = {}
    for name, payload in sections.items():
        section_blocks[name] = _markdown_to_html(payload.markdown)

    # Evidence Ledger table body (special)
    el = sections.get("evidence_ledger")
    ledger_rows_html = ""
    if el and el.structured:
        for item in el.structured:
            ledger_rows_html += (
                f"<tr><td>{_html.escape(item['claim'])}</td>"
                f"<td>{_html.escape(item['evidence'])}</td>"
                f"<td>{_html.escape(item['source'])}</td>"
                f"<td>{_html.escape(item['date'])}</td>"
                f"<td class=\"{item['direction']}\">{_html.escape(item['direction'])}</td>"
                f"<td>{_html.escape(item['confidence'])}</td></tr>"
            )

    # Scenarios table body
    sc = sections.get("scenarios")
    scenarios_rows_html = ""
    if sc and sc.structured:
        for direction in ("bear", "base", "bull"):
            row = sc.structured.get(direction)
            if row:
                cls = direction  # bull/bear/neutral
                scenarios_rows_html += (
                    f"<tr><td class=\"{cls if cls != 'base' else 'neutral'}\">"
                    f"{direction.title()}</td>"
                    f"<td>{_html.escape(row['target_range'])}</td>"
                    f"<td>{_html.escape(row['time_horizon'])}</td>"
                    f"<td>{_html.escape(row['key_assumptions'])}</td>"
                    f"<td>{_html.escape(row['confidence'])}</td>"
                    f"<td>{_html.escape(row['invalidation'])}</td></tr>"
                )

    ctx = {
        "ticker": req.ticker, "objective": req.objective,
        "report_datetime": "...", "quote_timestamp": "...",
        "filing_date": "...", "chart_window": "...",
        "depth": "full SOP",
        "position_budget_or_na": f"${req.position_budget_usd}" if req.position_budget_usd else "n/a",
        "score": str(total_score),
        "data_health_html": section_blocks.get("data_health", ""),
        "executive_summary_html": section_blocks.get("executive_summary", ""),
        "evidence_ledger_rows_html": ledger_rows_html,
        # ... one entry per section
        "scenarios_rows_html": scenarios_rows_html,
        # debate may be skipped (no personas) — that's fine
    }
    return _ENV.get_template("report.html").render(**ctx)
```

The exact set of context keys comes from Task 2 Step 2's placeholder audit. Render the keys that exist; pass empty string for missing.

- [ ] **Step 3: Commit** — `feat(research): HTML render for SOP report`

---

## Task 17: CLI update (sop_orchestrator + render_sop)

**Files:** Modify `src/research/__main__.py`

Replace the Phase 3 CLI to use `run_sop` + `render_sop`. Add CLI args matching `AnalyzeRequest`:

```bash
python -m src.research --ticker NVDA --objective medium_term \
  --budget 10000 --risk balanced --use-personas
```

Args: `--ticker` (required), `--objective` (choices from Objective Literal), `--budget` (float, optional), `--holds` (flag) + `--cost-basis` (float, conditional), `--risk` (conservative/balanced/aggressive), `--use-personas` (flag), `--only` (repeatable, restricts `included_sections`). Print: PERSONA ASSIGNMENTS box, BACKTEST VERDICT box, then `state["rendered_html"]` written to a temp file with path printed (DON'T dump 5000-word HTML to stdout).

Commit: `feat(research): CLI runs SOP orchestrator + writes HTML to temp file`

---

## Task 18: DB schema evolution

**Files:** Modify `app/backend/database/models.py` + create alembic migration `d9f1c5b8e2a6_add_analyze_columns.py`

Add two nullable JSON columns to `research_reports` (additive, won't break Phase 3):
- `analyze_request_json: JSON, nullable=True` — the full AnalyzeRequest serialization (objective, budget, cost_basis, risk_tolerance, included_sections, use_personas)
- `sections_json: JSON, nullable=True` — `dict[str, dict]` where each value is the SectionPayload structured field, for downstream consumers that want structured access without re-parsing the markdown

Migration: `op.add_column('research_reports', sa.Column('analyze_request_json', sa.JSON(), nullable=True))` + same for `sections_json`. Downgrade drops both.

Commit: `feat(backend): additive alembic for AnalyzeRequest + sections_json`

---

## Task 19: REST API + repository wiring

**Files:** Modify `app/backend/models/research_schemas.py` + `app/backend/routes/research.py` + `app/backend/repositories/research_repository.py`

`research_schemas.py`: add `AnalyzeRunRequest(BaseModel)` mirroring `AnalyzeRequest`. Keep existing `ResearchRunRequest` for backwards compat — the route accepts either via discriminator or has two endpoints:
- `POST /research/run` — keep existing (Phase 1-3 behavior)
- `POST /research/analyze` — new, takes `AnalyzeRunRequest`, calls `run_sop` + `render_sop` + persists with new columns populated

Repository: extend `create_with_plan` to accept optional `analyze_request_json` and `sections_json` kwargs.

`AnalyzeReportDetail(BaseModel)`: response model adds `sections: dict[str, dict]` field for the structured payload. Existing `ResearchReportDetail` stays unchanged.

Test coverage: one route test calling `/research/analyze` with mocked `run_sop` and `render_sop`, asserting 200 + persisted row + new JSON columns populated.

Commit: `feat(backend): /research/analyze endpoint + extended schemas`

---

## Task 20: Frontend — Analyze tab type + sidebar action

**Files:**
- Modify `app/frontend/src/contexts/tabs-context.tsx`: extend `TabType` union to `'flow' | 'settings' | 'scanner' | 'analyze'`.
- Modify `app/frontend/src/services/tab-service.ts`: add `case 'analyze'` to the switch; add `createAnalyzeTab()` static method.
- Create `app/frontend/src/components/panels/left/analyze-action.tsx`: copy-paste `scanner-action.tsx` shape, replace `Radar` icon with `Microscope` from lucide-react, open identifier='analyze'.
- Modify `app/frontend/src/components/panels/left/left-sidebar.tsx`: import + mount `<AnalyzeAction />` below `<ScannerAction />`.
- Create stub `app/frontend/src/components/panels/analyze/analyze-panel.tsx` returning `<div>Analyze panel (Task 21)</div>` so the tab renders.

Test: manually open frontend, click new icon, tab opens with stub content.

Commit: `feat(frontend): Analyze tab type + sidebar action + stub panel`

---

## Task 21: AnalyzePanel — form, module picker, results

**Files:** Create:
- `app/frontend/src/types/analyze.ts` — TypeScript types mirroring `AnalyzeRunRequest` + `AnalyzeReportDetail`.
- `app/frontend/src/services/analyze-service.ts` — `runAnalyze(req)`, `listReports(ticker?)`, `getReport(id)`, `reportHtmlUrl(id)`.
- `app/frontend/src/components/panels/analyze/analyze-form.tsx` — gate form: ticker, objective (select), budget (number input), `[ ] I already hold` + cost basis (conditional), risk (select), `[ ] Use personas` (checkbox).
- `app/frontend/src/components/panels/analyze/module-picker.tsx` — vertical list of 15 SECTION_ORDER entries with checkboxes, default all-on. Visually pipeline-styled (cards connected by vertical lines for the "flow-like" feel — use `border-l` accents, not React Flow). Two helper buttons: "All on" / "Required only" (required = data_health, executive_summary, evidence_ledger, conviction, final_strategy).
- Replace `app/frontend/src/components/panels/analyze/analyze-panel.tsx` (stub from Task 20): combines form + picker + run button + iframe for the latest report HTML + history list (recent reports). Loading state for the 60-90s SOP run.

Commit: `feat(frontend): Analyze panel — form + flow-style module picker + iframe`

---

## Task 22: End-to-end smoke + cleanup + progress.md

**Files:**
- Run full test suite: `tests/research/ tests/test_research_*.py tests/test_analyze_*.py` — expect all green.
- Run full pytest one more time for regression: only pre-existing 20 live-API failures should remain.
- Smoke real ticker via HTTP: `curl -sX POST http://127.0.0.1:8001/research/analyze -H "Content-Type: application/json" -d '{"ticker":"NVDA","objective":"medium_term","position_budget_usd":10000,"already_holds":false,"cost_basis_usd":null,"risk_tolerance":"balanced","use_personas":true,"included_sections":[...all 16...]}'` — confirm 60-120s response with rich `sections` + `rendered_html`.
- Smoke the new frontend: visit `http://localhost:5173`, click Microscope icon, fill form, click Run, confirm iframe renders the new SOP HTML with bull/bear pills + score badge.
- Modify `progress.md`: prepend `## Session — 2026-05-22 (Phase 4 landed)` block summarizing the 22 commits, test count, smoke result, the "always-75" fix (ConvictionSection computes score deterministically), backtest replacement (detector-replay → technical signal), frontend "Analyze" tab.

Commit: `docs: log research pipeline Phase 4 landing`

---

## Self-review

**Spec coverage**:
- 15 SOP sections → Tasks 5, 7-13 ✓
- Skill HTML template → Task 2 ✓
- Vendored skill prompts (modules + personas) → Task 1 ✓
- Technical-signal backtest replacing detector-replay → Task 14 ✓
- Multi-call section-by-section synthesizer → Task 15 (orchestrator + the section runner pattern from Task 6 = one LLM call per substantive section) ✓
- DB schema evolution (additive) → Task 18 ✓
- REST API (/research/analyze) → Task 19 ✓
- Frontend Analyze tab + flow-style module picker → Tasks 20-21 ✓
- "always-75" confidence bug → fixed at TWO layers: ConvictionSection computes weighted score deterministically (Task 12) AND ExecutiveSummary reads it from prior instead of re-asking (Task 13) ✓

**Placeholder scan**: Task 16 has shaped pseudo-code for `render_sop` because the full code depends on Task 2's placeholder audit; instructions are concrete (which dict keys to populate, which sections need special non-markdown handling). Implementer has enough to write it.

**Type consistency**:
- `AnalyzeRequest`, `AnalyzeReport`, `SectionPayload`, `BacktestVerdict`, `SECTION_ORDER` defined once in Task 3; referenced consistently across Tasks 4-22.
- `Section.run(ctx: SectionContext) -> SectionPayload` — same signature across every section file.
- `run_llm_section(*, section_name, ctx, prompt, output_model, markdown_heading)` — same kwargs everywhere in Tasks 7-13.
- `run_sop(request) -> AnalyzeReport` — defined Task 15, called by CLI (Task 17) and route (Task 19).
- `render_sop(report) -> str` — defined Task 16, called by route (Task 19) and CLI (Task 17).

**Risks**:
- Section count (16 = 15 SOP + 1 backtest sub-section) means ~14 LLM calls per full SOP run — ~$0.007/run at DeepSeek pricing. Acceptable.
- Wall-clock: ~60-120s per full SOP (each LLM call 5-8s). Frontend needs clear loading state; deferred-streaming via WebSocket is Phase 5 if users complain.
- Vendored prompts mean upstream changes to `stock-analyze-skills` don't auto-flow; refresh procedure documented in `src/research/prompts/README.md`.
- The `included_sections` toggle excluding upstream sections (e.g. EvidenceLedger) leaves downstream sections (ExecutiveSummary, FinalStrategy) with missing prior — handle gracefully via "n/a — upstream excluded" prose, not a crash.

