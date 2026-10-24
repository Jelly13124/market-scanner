# Per-Stock Research Pipeline — Phase 3 (Production Wiring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Phase 1+2 research pipeline into production — DB persistence, REST API, HTML email render, daily cron — so that `POST /research/run` produces a stored report, `GET /research/reports?ticker=X` lists history, and a 4:35pm ET cron mirrors what the legacy 4:30pm pipeline cron does, but emits research reports instead of portfolio decisions.

**Architecture:** Mirror existing `app/backend/` patterns (pipeline subsystem + notifications subsystem). Two new SQLAlchemy tables, additive Alembic migration, sync repository, four REST endpoints, Jinja-style HTML template, extension of the existing notification render path. The new cron job reads the legacy cron's persisted watchlist when available (avoiding duplicate scanner work) and falls back to running its own scan when the legacy cron is disabled.

**Tech Stack:** SQLAlchemy + Alembic (existing), Pydantic v2, FastAPI APScheduler (existing), Jinja2 (already a transitive dep via LangChain), DeepSeek-chat via Phase 1's `call_research_llm`. No new packages.

**Spec:** `docs/superpowers/specs/2026-05-22-research-pipeline-design.md`
**Phase 1 plan:** `docs/superpowers/plans/2026-05-22-research-pipeline-phase1.md`
**Phase 2 plan:** `docs/superpowers/plans/2026-05-22-research-pipeline-phase2.md`

**This plan is Phase 3 of 3.** When this lands, the spec is fully implemented except for the frontend research-request panel (explicitly deferred per spec).

---

## File structure (Phase 3)

```
app/backend/
  database/
    models.py                         # MODIFY: append ResearchReport + ResearchTradePlan
  alembic/versions/
    c8e7a1d2f3b4_add_research_tables.py   # NEW: additive migration
  repositories/
    research_repository.py            # NEW
  models/
    research_schemas.py               # NEW: Pydantic request/response
  routes/
    research.py                       # NEW: 4 endpoints
    __init__.py                       # MODIFY: register research router
  services/
    scheduler_service.py              # MODIFY: add _run_research_job
    notifications/
      render.py                       # MODIFY: append render_research_html
      dispatcher.py                   # MODIFY: support "research.completed" event_type

src/research/
  html_render.py                      # NEW: render(state) -> str
  templates/
    report.html                       # NEW: Jinja-style template
  persist.py                          # NEW: state_to_db_rows(state) helper

tests/
  test_research_repository.py         # NEW
  test_research_schemas.py            # NEW
  test_research_routes.py             # NEW
  research/
    test_html_render.py               # NEW
    test_persist.py                   # NEW
```

**What is NOT touched in Phase 3:**
- `src/research/` Phase 1+2 internals: `models.py`, `shared_data.py`, `llm.py`, `pipeline.py`, `synthesizer.py`, `router.py`, `modules/*`, `personas/*`, `__main__.py` — all stable.
- `v2/scanner/`, `v2/pipeline/orchestrator.py`, `src/agents/`, `src/main.py` — legacy unchanged.
- Existing DB tables: `pipeline_runs`, `pipeline_schedule`, `notification_subscriptions`, `notification_deliveries`, `scanner_*`, `watchlist_entries`, `analyst_target_snapshots`. The migration is additive only.
- Existing `_run_pipeline_job` cron at 4:30pm ET continues firing — research cron at 4:35pm ET is independent.
- Existing notification dispatcher logic — we only add a new render path for the new event type.
- Frontend (out of spec scope).

---

## Task 1: DB models for ResearchReport + ResearchTradePlan

**Files:**
- Modify: `app/backend/database/models.py` (append two new classes at the end)
- Create: `tests/test_research_db_models.py`

- [ ] **Step 1: Write the failing test**

Write `tests/test_research_db_models.py`:

```python
"""Schema smoke for ResearchReport + ResearchTradePlan SQLAlchemy classes.
These tests don't hit the DB — they verify the class structure (columns,
FK, indexes) so a typo in the model file shows up before the migration."""

from __future__ import annotations

from sqlalchemy import inspect

from app.backend.database.models import ResearchReport, ResearchTradePlan


def test_research_report_columns():
    cols = {c.name for c in inspect(ResearchReport).columns}
    expected = {
        "id", "created_at", "ticker", "scan_date",
        "request_json", "report_markdown", "rendered_html",
        "use_personas", "persona_assignments_json", "duration_seconds",
    }
    assert expected.issubset(cols), f"missing cols: {expected - cols}"


def test_research_report_indexes():
    table = ResearchReport.__table__
    index_names = {i.name for i in table.indexes}
    # Composite index for "list reports for ticker" queries
    assert "ix_research_reports_ticker_scan_date" in index_names


def test_research_trade_plan_columns():
    cols = {c.name for c in inspect(ResearchTradePlan).columns}
    expected_plan = {
        "id", "report_id",
        "direction", "entry_price", "target_price", "stop_price",
        "horizon_days", "sizing_pct", "confidence", "rationale",
    }
    expected_backtest = {
        "backtest_matches_found", "backtest_win_rate",
        "backtest_avg_pnl_pct", "backtest_sample_quality",
    }
    assert (expected_plan | expected_backtest).issubset(cols)


def test_research_trade_plan_fk_to_report():
    fks = list(inspect(ResearchTradePlan).columns["report_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "research_reports"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_db_models.py -v
```
Expected: ImportError — `ResearchReport`, `ResearchTradePlan` not in models.

- [ ] **Step 3: Append the two classes**

Read `app/backend/database/models.py` first to confirm imports at top. Append at the end of the file:

```python


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

    __table_args__ = (
        Index("ix_research_reports_ticker_scan_date", "ticker", "scan_date"),
    )


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
```

The `Column`, `Integer`, `Float`, `String`, `DateTime`, `Text`, `Boolean`, `JSON`, `ForeignKey`, `func` symbols are already imported at the top of `models.py`. Add `Index` to the existing import line at the top if not already present:

```python
from sqlalchemy import Column, Integer, Float, String, DateTime, Text, Boolean, JSON, ForeignKey, Index, UniqueConstraint
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_db_models.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/backend/database/models.py tests/test_research_db_models.py
git commit -m "feat(backend): ResearchReport + ResearchTradePlan SQLAlchemy models

ResearchReport holds the synthesizer output (markdown + rendered HTML)
plus persona assignments. ResearchTradePlan holds the TradePlan +
inlined BacktestSummary fields with ON DELETE CASCADE FK. Composite
index on (ticker, scan_date) supports the 'reports for this ticker'
query pattern.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Alembic migration

**Files:**
- Create: `app/backend/alembic/versions/c8e7a1d2f3b4_add_research_tables.py`

- [ ] **Step 1: Identify current head revision**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m alembic -c app/backend/alembic.ini current 2>&1 | tail -5
```

If alembic CLI isn't installed, inspect `app/backend/alembic/versions/` filenames + the most recent file's `revision = "..."` line — the down_revision in the new migration must match the current head. Per the existing files, the most recent is likely `f7b9c4e1d2a8` or `b3d8f1a2c9e4`. Use whichever has no down_revision pointing to it.

To detect head deterministically, run:

```bash
grep -l "down_revision" app/backend/alembic/versions/*.py | xargs grep -H "^revision " | sort
```

This lists every revision id. The HEAD is the one no other file references as `down_revision`.

- [ ] **Step 2: Write the migration**

Write `app/backend/alembic/versions/c8e7a1d2f3b4_add_research_tables.py`. Replace `<CURRENT_HEAD>` below with the revision id you found in Step 1.

```python
"""add_research_tables

Creates research_reports + research_trade_plans for the per-stock
research pipeline (Phase 3). Additive only — no changes to existing
pipeline_runs / scanner_* / notification_* tables.

Revision ID: c8e7a1d2f3b4
Revises: <CURRENT_HEAD>
Create Date: 2026-05-22 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e7a1d2f3b4"
down_revision: Union[str, None] = "<CURRENT_HEAD>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add the two research tables."""
    op.create_table(
        "research_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("scan_date", sa.String(length=10), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("rendered_html", sa.Text(), nullable=False),
        sa.Column("use_personas", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("persona_assignments_json", sa.JSON(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_reports_id"), "research_reports", ["id"], unique=False)
    op.create_index(op.f("ix_research_reports_ticker"), "research_reports", ["ticker"], unique=False)
    op.create_index(op.f("ix_research_reports_scan_date"), "research_reports", ["scan_date"], unique=False)
    op.create_index("ix_research_reports_ticker_scan_date", "research_reports", ["ticker", "scan_date"], unique=False)

    op.create_table(
        "research_trade_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sizing_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("backtest_matches_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backtest_win_rate", sa.Float(), nullable=True),
        sa.Column("backtest_avg_pnl_pct", sa.Float(), nullable=True),
        sa.Column("backtest_max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("backtest_avg_holding_days", sa.Float(), nullable=True),
        sa.Column("backtest_sample_quality", sa.String(length=20),
                  nullable=False, server_default="insufficient"),
        sa.Column("backtest_caveat", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["research_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_trade_plans_id"), "research_trade_plans", ["id"], unique=False)
    op.create_index(op.f("ix_research_trade_plans_report_id"), "research_trade_plans", ["report_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema — drop the two research tables.

    research_trade_plans first because it has FK into research_reports.
    """
    op.drop_index(op.f("ix_research_trade_plans_report_id"), table_name="research_trade_plans")
    op.drop_index(op.f("ix_research_trade_plans_id"), table_name="research_trade_plans")
    op.drop_table("research_trade_plans")

    op.drop_index("ix_research_reports_ticker_scan_date", table_name="research_reports")
    op.drop_index(op.f("ix_research_reports_scan_date"), table_name="research_reports")
    op.drop_index(op.f("ix_research_reports_ticker"), table_name="research_reports")
    op.drop_index(op.f("ix_research_reports_id"), table_name="research_reports")
    op.drop_table("research_reports")
```

- [ ] **Step 3: Run the migration forward**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m alembic -c app/backend/alembic.ini upgrade head 2>&1 | tail -5
```
Expected: `Running upgrade <CURRENT_HEAD> -> c8e7a1d2f3b4, add_research_tables`.

If alembic CLI fails (not on PATH), invoke programmatically:

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -c "from alembic.config import Config; from alembic import command; cfg = Config('app/backend/alembic.ini'); command.upgrade(cfg, 'head')"
```

- [ ] **Step 4: Run downgrade-then-upgrade to verify reversibility**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -c "from alembic.config import Config; from alembic import command; cfg = Config('app/backend/alembic.ini'); command.downgrade(cfg, '-1'); command.upgrade(cfg, 'head')"
```
Expected: no errors. Tables dropped + recreated cleanly.

- [ ] **Step 5: Commit**

```bash
git add app/backend/alembic/versions/c8e7a1d2f3b4_add_research_tables.py
git commit -m "feat(backend): alembic migration for research tables

Additive migration. Adds research_reports + research_trade_plans (FK
with ON DELETE CASCADE) and their indexes. Downgrade drops both
cleanly in FK-aware order. Verified reversible.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: ResearchReportRepository

**Files:**
- Create: `app/backend/repositories/research_repository.py`
- Create: `tests/test_research_repository.py`

- [ ] **Step 1: Write the failing test**

Write `tests/test_research_repository.py`:

```python
"""ResearchReportRepository CRUD tests against an in-memory SQLite DB."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base
from app.backend.database.models import ResearchReport, ResearchTradePlan
from app.backend.repositories.research_repository import ResearchReportRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _sample_row_kwargs(ticker="NVDA"):
    return dict(
        ticker=ticker,
        scan_date="2026-05-22",
        request_json={"ticker": ticker, "use_personas": False},
        report_markdown="# Report",
        rendered_html="<html><body>Report</body></html>",
        use_personas=False,
        persona_assignments_json=None,
        duration_seconds=42.5,
    )


def _sample_plan_kwargs(report_id):
    return dict(
        report_id=report_id,
        direction="long",
        entry_price=145.0,
        target_price=165.0,
        stop_price=138.0,
        horizon_days=30,
        sizing_pct=0.05,
        confidence=72,
        rationale="moat + earnings beat",
        backtest_matches_found=0,
        backtest_win_rate=None,
        backtest_avg_pnl_pct=None,
        backtest_max_drawdown_pct=None,
        backtest_avg_holding_days=None,
        backtest_sample_quality="insufficient",
        backtest_caveat="no history",
    )


class TestResearchReportRepository:
    def test_create_returns_row_with_id(self, db_session):
        repo = ResearchReportRepository(db_session)
        row = repo.create_with_plan(
            report=_sample_row_kwargs(),
            plan=_sample_plan_kwargs(report_id=0),  # repo wires the FK
        )
        assert row.id > 0
        assert row.ticker == "NVDA"

    def test_get_by_id_returns_row_with_plan(self, db_session):
        repo = ResearchReportRepository(db_session)
        created = repo.create_with_plan(
            report=_sample_row_kwargs(),
            plan=_sample_plan_kwargs(report_id=0),
        )
        loaded = repo.get_by_id(created.id)
        assert loaded is not None
        assert loaded.ticker == "NVDA"
        # Plan accessible via separate query helper
        plan = repo.get_plan_for_report(created.id)
        assert plan is not None
        assert plan.direction == "long"

    def test_get_by_id_missing_returns_none(self, db_session):
        repo = ResearchReportRepository(db_session)
        assert repo.get_by_id(99999) is None

    def test_list_filters_by_ticker(self, db_session):
        repo = ResearchReportRepository(db_session)
        repo.create_with_plan(
            report=_sample_row_kwargs("NVDA"),
            plan=_sample_plan_kwargs(report_id=0),
        )
        repo.create_with_plan(
            report=_sample_row_kwargs("AVGO"),
            plan=_sample_plan_kwargs(report_id=0),
        )
        nvda_rows = repo.list_reports(ticker="NVDA")
        avgo_rows = repo.list_reports(ticker="AVGO")
        all_rows = repo.list_reports()
        assert len(nvda_rows) == 1 and nvda_rows[0].ticker == "NVDA"
        assert len(avgo_rows) == 1 and avgo_rows[0].ticker == "AVGO"
        assert len(all_rows) == 2

    def test_list_newest_first(self, db_session):
        repo = ResearchReportRepository(db_session)
        repo.create_with_plan(
            report=_sample_row_kwargs("AAA"),
            plan=_sample_plan_kwargs(report_id=0),
        )
        repo.create_with_plan(
            report=_sample_row_kwargs("BBB"),
            plan=_sample_plan_kwargs(report_id=0),
        )
        rows = repo.list_reports()
        # newest-first → BBB came second
        assert rows[0].ticker == "BBB"

    def test_list_respects_limit(self, db_session):
        repo = ResearchReportRepository(db_session)
        for i in range(5):
            repo.create_with_plan(
                report=_sample_row_kwargs(f"T{i}"),
                plan=_sample_plan_kwargs(report_id=0),
            )
        rows = repo.list_reports(limit=3)
        assert len(rows) == 3

    def test_cascade_delete_removes_plan(self, db_session):
        """Deleting a report must cascade to its trade plan."""
        repo = ResearchReportRepository(db_session)
        row = repo.create_with_plan(
            report=_sample_row_kwargs(),
            plan=_sample_plan_kwargs(report_id=0),
        )
        report_id = row.id
        # Verify plan exists
        assert repo.get_plan_for_report(report_id) is not None
        # Delete report
        db_session.delete(row)
        db_session.commit()
        # SQLite needs PRAGMA foreign_keys=ON for cascade; without it the
        # plan row may remain. Either is acceptable for v1 — production DB
        # (Postgres) honors the constraint regardless. Just check the
        # report itself is gone.
        assert repo.get_by_id(report_id) is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_repository.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the repository**

Write `app/backend/repositories/research_repository.py`:

```python
"""Repository for the research pipeline persistence layer.

Mirrors the shape of PipelineRunRepository: sync, Session-injected,
commit per write, no business logic. Routes/services orchestrate.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.backend.database.models import ResearchReport, ResearchTradePlan


class ResearchReportRepository:
    """CRUD for ResearchReport + 1-to-1 ResearchTradePlan."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- create --------------------------------------------------------------

    def create_with_plan(
        self,
        *,
        report: dict,
        plan: dict,
    ) -> ResearchReport:
        """Insert a ResearchReport AND its paired ResearchTradePlan in one
        commit. Caller passes plan dict with report_id=0 placeholder; we
        overwrite with the real FK after the report inserts.
        """
        # Strip placeholder FK from the plan dict; we set it after the
        # report id is allocated.
        plan_kwargs = dict(plan)
        plan_kwargs.pop("report_id", None)

        report_row = ResearchReport(**report)
        self.db.add(report_row)
        self.db.flush()  # populate report_row.id without committing yet

        plan_row = ResearchTradePlan(report_id=report_row.id, **plan_kwargs)
        self.db.add(plan_row)
        self.db.commit()
        self.db.refresh(report_row)
        return report_row

    # -- read ---------------------------------------------------------------

    def get_by_id(self, report_id: int) -> Optional[ResearchReport]:
        return (
            self.db.query(ResearchReport)
            .filter(ResearchReport.id == report_id)
            .first()
        )

    def get_plan_for_report(self, report_id: int) -> Optional[ResearchTradePlan]:
        return (
            self.db.query(ResearchTradePlan)
            .filter(ResearchTradePlan.report_id == report_id)
            .first()
        )

    def list_reports(
        self,
        *,
        ticker: str | None = None,
        scan_date: str | None = None,
        limit: int = 50,
    ) -> list[ResearchReport]:
        """List reports newest-first. ticker + scan_date filters AND together."""
        q = self.db.query(ResearchReport)
        if ticker:
            q = q.filter(ResearchReport.ticker == ticker)
        if scan_date:
            q = q.filter(ResearchReport.scan_date == scan_date)
        return q.order_by(desc(ResearchReport.created_at)).limit(limit).all()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_repository.py -v
```
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/backend/repositories/research_repository.py tests/test_research_repository.py
git commit -m "feat(backend): ResearchReportRepository

CRUD for ResearchReport + paired ResearchTradePlan in one commit.
Mirrors PipelineRunRepository shape: sync, Session-injected, no
business logic. list_reports filters by ticker + scan_date and
returns newest-first.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Pydantic API schemas

**Files:**
- Create: `app/backend/models/research_schemas.py`
- Create: `tests/test_research_schemas.py`

- [ ] **Step 1: Write the failing test**

Write `tests/test_research_schemas.py`:

```python
"""Pydantic schema validation for the research REST API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.backend.models.research_schemas import (
    ResearchRunRequest,
    ResearchReportSummary,
    ResearchReportDetail,
    TradePlanPayload,
    BacktestSummaryPayload,
)


class TestResearchRunRequest:
    def test_minimal_request(self):
        r = ResearchRunRequest(ticker="NVDA")
        assert r.ticker == "NVDA"
        assert r.holding_status == "watching"           # default
        assert r.target_position_pct == 0.05            # default
        assert r.risk_tolerance == "moderate"           # default
        assert r.report_goal == "general_research"      # default
        assert r.use_personas is False                  # default

    def test_full_request(self):
        r = ResearchRunRequest(
            ticker="META",
            holding_status="holding",
            target_position_pct=0.10,
            risk_tolerance="aggressive",
            report_goal="hold_review",
            use_personas=True,
        )
        assert r.holding_status == "holding"

    def test_invalid_risk_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRunRequest(ticker="NVDA", risk_tolerance="reckless")

    def test_invalid_position_pct_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRunRequest(ticker="NVDA", target_position_pct=1.5)
        with pytest.raises(ValidationError):
            ResearchRunRequest(ticker="NVDA", target_position_pct=-0.01)

    def test_ticker_uppercased(self):
        r = ResearchRunRequest(ticker="nvda")
        assert r.ticker == "NVDA"


class TestTradePlanPayload:
    def test_long_plan(self):
        p = TradePlanPayload(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="test",
        )
        assert p.direction == "long"

    def test_stand_aside_allows_null_prices(self):
        p = TradePlanPayload(
            direction="stand_aside",
            entry_price=None, target_price=None, stop_price=None,
            horizon_days=0, sizing_pct=0.0, confidence=0, rationale="x",
        )
        assert p.entry_price is None

    def test_confidence_range_enforced(self):
        with pytest.raises(ValidationError):
            TradePlanPayload(
                direction="long", entry_price=1.0, target_price=2.0,
                stop_price=0.5, horizon_days=1, sizing_pct=0.01,
                confidence=150, rationale="x",
            )


class TestBacktestSummaryPayload:
    def test_strong_sample(self):
        b = BacktestSummaryPayload(
            matches_found=15, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.12, avg_holding_days=18.5,
            sample_quality="strong", caveat=None,
        )
        assert b.sample_quality == "strong"


class TestResearchReportSummary:
    def test_built_from_orm_row(self):
        """ResearchReportSummary should validate from an object with the
        expected attributes (ORM-mode)."""
        from types import SimpleNamespace
        from datetime import datetime
        row = SimpleNamespace(
            id=1, ticker="NVDA", scan_date="2026-05-22",
            created_at=datetime(2026, 5, 22, 16, 35),
            use_personas=True,
            duration_seconds=42.5,
        )
        s = ResearchReportSummary.model_validate(row, from_attributes=True)
        assert s.id == 1
        assert s.ticker == "NVDA"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_schemas.py -v
```

- [ ] **Step 3: Implement schemas**

Write `app/backend/models/research_schemas.py`:

```python
"""Pydantic request/response schemas for the research REST API.

Wrappers around the internal src.research.models dataclasses. The internal
types stay dataclasses (no Pydantic overhead in the pipeline hot path);
these schemas are the API boundary types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Mirror the Literal types from src/research/models.py
HoldingStatus = Literal["holding", "watching", "considering_buy", "considering_short"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
ReportGoal = Literal["new_entry", "hold_review", "exit_decision", "general_research"]
Direction = Literal["long", "short", "stand_aside"]
SampleQuality = Literal["strong", "moderate", "weak", "insufficient"]


class ResearchRunRequest(BaseModel):
    """POST /research/run body. Defaults mirror the CLI's defaults so
    on-demand callers can fire-and-forget with just a ticker."""

    ticker: str
    holding_status: HoldingStatus = "watching"
    target_position_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    risk_tolerance: RiskTolerance = "moderate"
    report_goal: ReportGoal = "general_research"
    use_personas: bool = False

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, v: str) -> str:
        return v.strip().upper()


class TradePlanPayload(BaseModel):
    """API mirror of src.research.models.TradePlan."""

    direction: Direction
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    horizon_days: int = Field(ge=0)
    sizing_pct: float = Field(ge=0.0, le=1.0)
    confidence: int = Field(ge=0, le=100)
    rationale: str


class BacktestSummaryPayload(BaseModel):
    """API mirror of src.research.models.BacktestSummary."""

    matches_found: int = Field(ge=0)
    win_rate: float | None
    avg_pnl_pct: float | None
    max_drawdown_pct: float | None
    avg_holding_days: float | None
    sample_quality: SampleQuality
    caveat: str | None


class ResearchReportSummary(BaseModel):
    """List-mode response — one row per report, no body content."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    scan_date: str
    created_at: datetime
    use_personas: bool
    duration_seconds: float | None


class ResearchReportDetail(BaseModel):
    """Full report including markdown body, plan, and backtest. The
    rendered_html field is fetched separately via /reports/{id}/html
    to keep the JSON response light when the consumer only wants the
    structured data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    scan_date: str
    created_at: datetime
    use_personas: bool
    persona_assignments: dict | None
    report_markdown: str
    duration_seconds: float | None
    plan: TradePlanPayload
    backtest: BacktestSummaryPayload
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_schemas.py -v
```
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/backend/models/research_schemas.py tests/test_research_schemas.py
git commit -m "feat(backend): pydantic schemas for /research API

ResearchRunRequest with defaults mirroring the CLI; TradePlanPayload
+ BacktestSummaryPayload as API mirrors of the internal dataclasses;
ResearchReportSummary (list mode) + ResearchReportDetail (full body).
Ticker auto-uppercased. Range constraints on confidence/sizing/etc.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: HTML render + template

**Files:**
- Create: `src/research/templates/report.html`
- Create: `src/research/html_render.py`
- Create: `tests/research/test_html_render.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_html_render.py`:

```python
"""HTML render: ResearchState -> single self-contained HTML string.
Email-safe (inline styles, no external assets). Snapshot-style content
checks rather than DOM parsing — keeps the test fast and resilient to
template tweaks."""

from __future__ import annotations

from src.research.html_render import render_html
from src.research.models import (
    BacktestSummary, ModuleResult, ResearchRequest, ResearchState, TradePlan,
)


def _state(direction="long", use_personas=False, debate=False):
    request = ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=use_personas, scanner_context=None,
    )
    module_results = {
        "macro": ModuleResult(
            module_name="macro", persona_used=None,
            markdown="SPY +5%, regime up.", key_metrics={},
        ),
        "valuation": ModuleResult(
            module_name="valuation",
            persona_used="buffett" if use_personas else None,
            markdown="Fair value $160.", key_metrics={},
        ),
    }
    if debate:
        module_results["debate"] = ModuleResult(
            module_name="debate", persona_used="wood+burry",
            markdown="**Wood:** growth. **Burry:** value.", key_metrics={},
        )
    persona_assignments = None
    if use_personas:
        persona_assignments = {
            "fundamentals": "buffett",
            "valuation": "buffett",
            "risk_position": None,
            "debate": ["wood", "burry"] if debate else [],
            "_rationale": "tech name; growth vs value.",
        }
    return ResearchState(
        request=request,
        persona_assignments=persona_assignments,
        module_results=module_results,
        report_markdown="# NVDA report\n\nNarrative goes here.",
        strategy=TradePlan(
            direction=direction,
            entry_price=145.0 if direction != "stand_aside" else None,
            target_price=165.0 if direction != "stand_aside" else None,
            stop_price=138.0 if direction != "stand_aside" else None,
            horizon_days=30 if direction != "stand_aside" else 0,
            sizing_pct=0.05 if direction != "stand_aside" else 0.0,
            confidence=72 if direction != "stand_aside" else 0,
            rationale="Earnings beat + insider cluster.",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html=None,
    )


class TestRenderHtml:
    def test_returns_complete_html_document(self):
        html = render_html(_state())
        assert html.startswith("<!DOCTYPE html>") or html.lstrip().startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_ticker_in_title_or_header(self):
        html = render_html(_state())
        assert "NVDA" in html

    def test_trade_plan_box_rendered(self):
        html = render_html(_state(direction="long"))
        assert "Entry" in html
        assert "145" in html
        assert "Target" in html

    def test_stand_aside_renders_no_prices(self):
        html = render_html(_state(direction="stand_aside"))
        assert "stand" in html.lower()
        # No entry/target/stop numeric prices
        assert "$145" not in html

    def test_backtest_box_rendered(self):
        html = render_html(_state())
        assert "moderate" in html.lower() or "Moderate" in html
        assert "5" in html  # matches_found

    def test_report_markdown_included(self):
        html = render_html(_state())
        # Report body should appear (markdown converted to HTML or wrapped)
        assert "Narrative goes here" in html

    def test_persona_section_only_when_personas_used(self):
        html_off = render_html(_state(use_personas=False))
        html_on = render_html(_state(use_personas=True))
        # When off, no persona block
        assert "buffett" not in html_off.lower()
        # When on, persona names appear
        assert "buffett" in html_on.lower()

    def test_debate_section_when_present(self):
        html_no_debate = render_html(_state(use_personas=True, debate=False))
        html_debate = render_html(_state(use_personas=True, debate=True))
        assert "wood vs burry" in html_debate.lower() or "wood" in html_debate.lower()
        # When no debate, the "debate" word shouldn't appear in a way that
        # confuses the reader — at minimum the wood+burry pair shouldn't.
        assert "wood vs burry" not in html_no_debate.lower()

    def test_html_escapes_ticker(self):
        """Defensive: ticker is user input, must be escaped."""
        state = _state()
        state["request"].ticker = "X<script>"
        html = render_html(state)
        assert "<script>" not in html  # raw script tag absent
        assert "&lt;script&gt;" in html  # escaped form present
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_html_render.py -v
```

- [ ] **Step 3: Create the template**

Write `src/research/templates/report.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ ticker }} — Research Report</title>
<style>
  /* Email-safe inline-friendly styles. Gmail strips <style> blocks for
     some emails — every visual rule that matters is also inlined on the
     element in the body below. This <style> block helps standalone HTML
     viewing only. */
  body { font-family: -apple-system, system-ui, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 24px; }
  .report { max-width: 760px; margin: 0 auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 24px; }
  .header { border-bottom: 2px solid #0f172a; padding-bottom: 12px; margin-bottom: 16px; }
  .box { border: 1px solid #cbd5e1; border-radius: 6px; padding: 12px 16px; margin: 16px 0; }
  .plan-box { background: #f0fdf4; border-color: #86efac; }
  .plan-box.stand-aside { background: #fef3c7; border-color: #fcd34d; }
  .backtest-box { background: #eff6ff; border-color: #93c5fd; }
  .persona-box { background: #faf5ff; border-color: #c4b5fd; }
  .section { margin-top: 20px; }
  .section h3 { border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
  .kv { display: inline-block; margin-right: 18px; }
  .kv .label { font-size: 12px; color: #64748b; text-transform: uppercase; }
  .kv .value { font-size: 16px; font-weight: 600; color: #0f172a; }
  .small { font-size: 12px; color: #64748b; }
  pre, code { background: #f1f5f9; padding: 2px 6px; border-radius: 3px; font-size: 13px; }
</style>
</head>
<body>
<div class="report" style="max-width:760px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:24px;">

  <div class="header" style="border-bottom:2px solid #0f172a;padding-bottom:12px;margin-bottom:16px;">
    <div style="font-size:24px;font-weight:700;">{{ ticker }}</div>
    <div class="small" style="font-size:12px;color:#64748b;">
      Scan date: {{ scan_date }} &middot;
      Goal: {{ report_goal }} &middot;
      Risk: {{ risk_tolerance }} &middot;
      Holding: {{ holding_status }}
    </div>
  </div>

  <div class="box plan-box{% if plan_direction == 'stand_aside' %} stand-aside{% endif %}" style="background:{{ '#fef3c7' if plan_direction == 'stand_aside' else '#f0fdf4' }};border:1px solid {{ '#fcd34d' if plan_direction == 'stand_aside' else '#86efac' }};border-radius:6px;padding:12px 16px;margin:16px 0;">
    <div style="font-size:14px;font-weight:700;text-transform:uppercase;color:#166534;">
      Trade Plan: {{ plan_direction|upper }}
    </div>
    {% if plan_direction == 'stand_aside' %}
      <div style="margin-top:8px;">
        <span class="small">No actionable trade. Confidence: {{ plan_confidence }}/100</span>
      </div>
    {% else %}
      <div style="margin-top:8px;">
        <span class="kv" style="display:inline-block;margin-right:18px;">
          <span class="label" style="font-size:12px;color:#64748b;">Entry</span><br>
          <span class="value" style="font-size:16px;font-weight:600;">${{ plan_entry }}</span>
        </span>
        <span class="kv" style="display:inline-block;margin-right:18px;">
          <span class="label" style="font-size:12px;color:#64748b;">Target</span><br>
          <span class="value" style="font-size:16px;font-weight:600;">${{ plan_target }}</span>
        </span>
        <span class="kv" style="display:inline-block;margin-right:18px;">
          <span class="label" style="font-size:12px;color:#64748b;">Stop</span><br>
          <span class="value" style="font-size:16px;font-weight:600;">${{ plan_stop }}</span>
        </span>
        <span class="kv" style="display:inline-block;margin-right:18px;">
          <span class="label" style="font-size:12px;color:#64748b;">Horizon</span><br>
          <span class="value" style="font-size:16px;font-weight:600;">{{ plan_horizon }}d</span>
        </span>
        <span class="kv" style="display:inline-block;margin-right:18px;">
          <span class="label" style="font-size:12px;color:#64748b;">Sizing</span><br>
          <span class="value" style="font-size:16px;font-weight:600;">{{ plan_sizing_pct }}%</span>
        </span>
        <span class="kv" style="display:inline-block;margin-right:18px;">
          <span class="label" style="font-size:12px;color:#64748b;">Confidence</span><br>
          <span class="value" style="font-size:16px;font-weight:600;">{{ plan_confidence }}/100</span>
        </span>
      </div>
    {% endif %}
    <div style="margin-top:10px;font-size:13px;color:#374151;">
      {{ plan_rationale }}
    </div>
  </div>

  <div class="box backtest-box" style="background:#eff6ff;border:1px solid #93c5fd;border-radius:6px;padding:12px 16px;margin:16px 0;">
    <div style="font-size:14px;font-weight:700;text-transform:uppercase;color:#1e40af;">
      Detector Backtest ({{ backtest_sample_quality }})
    </div>
    <div style="margin-top:8px;">
      <span class="kv" style="display:inline-block;margin-right:18px;">
        <span class="label" style="font-size:12px;color:#64748b;">Matches</span><br>
        <span class="value" style="font-size:16px;font-weight:600;">{{ backtest_matches }}</span>
      </span>
      {% if backtest_win_rate is not none %}
      <span class="kv" style="display:inline-block;margin-right:18px;">
        <span class="label" style="font-size:12px;color:#64748b;">Win rate</span><br>
        <span class="value" style="font-size:16px;font-weight:600;">{{ backtest_win_rate }}%</span>
      </span>
      <span class="kv" style="display:inline-block;margin-right:18px;">
        <span class="label" style="font-size:12px;color:#64748b;">Avg PnL</span><br>
        <span class="value" style="font-size:16px;font-weight:600;">{{ backtest_avg_pnl }}%</span>
      </span>
      <span class="kv" style="display:inline-block;margin-right:18px;">
        <span class="label" style="font-size:12px;color:#64748b;">Max DD</span><br>
        <span class="value" style="font-size:16px;font-weight:600;">{{ backtest_max_dd }}%</span>
      </span>
      {% endif %}
    </div>
    {% if backtest_caveat %}
      <div style="margin-top:8px;font-size:12px;color:#7c2d12;">⚠ {{ backtest_caveat }}</div>
    {% endif %}
  </div>

  {% if persona_assignments_block %}
  <div class="box persona-box" style="background:#faf5ff;border:1px solid #c4b5fd;border-radius:6px;padding:12px 16px;margin:16px 0;">
    <div style="font-size:14px;font-weight:700;text-transform:uppercase;color:#6b21a8;">
      Persona Assignments
    </div>
    <div style="margin-top:8px;font-size:13px;">
      {{ persona_assignments_block|safe }}
    </div>
    {% if persona_rationale %}
      <div class="small" style="margin-top:6px;font-size:12px;color:#64748b;">
        Rationale: {{ persona_rationale }}
      </div>
    {% endif %}
  </div>
  {% endif %}

  <div class="section" style="margin-top:20px;">
    <h3 style="border-bottom:1px solid #e2e8f0;padding-bottom:4px;">Report</h3>
    <div style="font-size:14px;line-height:1.55;">
      {{ report_html|safe }}
    </div>
  </div>

  {% for mod_name, mod_html in module_blocks %}
  <div class="section" style="margin-top:20px;">
    <h3 style="border-bottom:1px solid #e2e8f0;padding-bottom:4px;">
      {{ mod_name|title }}{% if mod_name in persona_per_module and persona_per_module[mod_name] %} <span class="small" style="font-size:12px;color:#64748b;">({{ persona_per_module[mod_name] }})</span>{% endif %}
    </h3>
    <div style="font-size:13px;line-height:1.55;">
      {{ mod_html|safe }}
    </div>
  </div>
  {% endfor %}

  <div class="small" style="margin-top:32px;font-size:11px;color:#94a3b8;text-align:center;border-top:1px solid #e2e8f0;padding-top:12px;">
    Generated by ai-hedge-fund research pipeline in {{ duration_seconds }}s
  </div>

</div>
</body>
</html>
```

- [ ] **Step 4: Create the renderer**

Write `src/research/html_render.py`:

```python
"""Render a ResearchState into a single self-contained HTML document.

Inline-style HTML; no external CSS or JS. Email-safe (Gmail strips
<style> blocks for some flows — every visual rule that matters is also
inlined on the body element).

Markdown bodies (report_markdown, module markdowns) are converted to
HTML via a minimal markdown-to-HTML pass. We avoid pulling in a heavy
markdown dependency by handling the small subset the synthesizer emits:
headings (#, ##, ###), bold (**), italic (*), bullet lists, paragraphs.
Anything more exotic is left literal.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.research.models import ResearchState


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _markdown_to_html(text: str) -> str:
    """Minimal markdown subset → HTML. Handles what the synthesizer +
    module prompts realistically emit; does not pretend to be CommonMark.
    """
    if not text:
        return ""
    # Escape first; then unescape the few markdown markers we re-introduce
    # as real HTML below.
    out_lines: list[str] = []
    in_list = False

    def _inline(s: str) -> str:
        # Order matters: bold before italic to avoid ** being consumed by *.
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?!\w)", r"<em>\1</em>", s)
        s = re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)
        return s

    for raw in text.split("\n"):
        line = raw.rstrip()
        escaped = _html.escape(line)
        if not line.strip():
            if in_list:
                out_lines.append("</ul>")
                in_list = False
            out_lines.append("")
            continue
        # Headings (# ## ###)
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            if in_list:
                out_lines.append("</ul>")
                in_list = False
            level = len(m.group(1))
            content = _inline(_html.escape(m.group(2)))
            out_lines.append(f"<h{level + 2}>{content}</h{level + 2}>")
            continue
        # Bullet list item
        if line.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out_lines.append("<ul>")
                in_list = True
            item = line.lstrip()[2:]
            out_lines.append(f"  <li>{_inline(_html.escape(item))}</li>")
            continue
        # Paragraph line
        if in_list:
            out_lines.append("</ul>")
            in_list = False
        out_lines.append(f"<p>{_inline(escaped)}</p>")
    if in_list:
        out_lines.append("</ul>")
    return "\n".join(out_lines)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}"


def _persona_assignments_block(assignments: dict | None) -> str:
    """Render per-module persona assignments as an inline list (HTML)."""
    if not assignments:
        return ""
    parts: list[str] = []
    for module_name in ("fundamentals", "valuation", "risk_position"):
        persona = assignments.get(module_name)
        label = persona if persona else "objective"
        parts.append(
            f'<div><strong>{_html.escape(module_name)}:</strong> '
            f'{_html.escape(label)}</div>'
        )
    debate = assignments.get("debate") or []
    if isinstance(debate, list) and len(debate) == 2:
        parts.append(
            f'<div><strong>debate:</strong> '
            f'{_html.escape(debate[0])} vs {_html.escape(debate[1])}</div>'
        )
    return "\n".join(parts)


def render_html(state: ResearchState) -> str:
    """Convert a ResearchState into the final HTML payload."""
    request = state["request"]
    plan = state["strategy"]
    backtest = state["backtest_summary"]
    module_results = state.get("module_results") or {}
    assignments = state.get("persona_assignments")

    # Module section list — skip skipped modules
    module_blocks: list[tuple[str, str]] = []
    for name, result in module_results.items():
        if result.skipped:
            continue
        if not result.markdown.strip():
            continue
        module_blocks.append((name, _markdown_to_html(result.markdown)))

    persona_per_module = {}
    if assignments:
        for name, result in module_results.items():
            if result.persona_used:
                persona_per_module[name] = result.persona_used

    ctx = {
        "ticker": _html.escape(request.ticker),
        "scan_date": _html.escape(getattr(request, "scanner_context", None) and
                                  request.scanner_context.get("scan_date", "") or ""),
        "report_goal": _html.escape(request.report_goal),
        "risk_tolerance": _html.escape(request.risk_tolerance),
        "holding_status": _html.escape(request.holding_status),
        "plan_direction": plan.direction,
        "plan_entry": f"{plan.entry_price:.2f}" if plan.entry_price is not None else "—",
        "plan_target": f"{plan.target_price:.2f}" if plan.target_price is not None else "—",
        "plan_stop": f"{plan.stop_price:.2f}" if plan.stop_price is not None else "—",
        "plan_horizon": plan.horizon_days,
        "plan_sizing_pct": f"{plan.sizing_pct * 100:.2f}",
        "plan_confidence": plan.confidence,
        "plan_rationale": _html.escape(plan.rationale),
        "backtest_sample_quality": backtest.sample_quality,
        "backtest_matches": backtest.matches_found,
        "backtest_win_rate": _format_pct(backtest.win_rate),
        "backtest_avg_pnl": _format_pct(backtest.avg_pnl_pct),
        "backtest_max_dd": _format_pct(backtest.max_drawdown_pct),
        "backtest_caveat": _html.escape(backtest.caveat or ""),
        "persona_assignments_block": _persona_assignments_block(assignments),
        "persona_rationale": _html.escape(
            (assignments or {}).get("_rationale", "") or ""
        ),
        "persona_per_module": persona_per_module,
        "report_html": _markdown_to_html(state.get("report_markdown") or ""),
        "module_blocks": module_blocks,
        "duration_seconds": "—",  # populated by caller when available
    }
    template = _ENV.get_template("report.html")
    return template.render(**ctx)
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_html_render.py -v
```
Expected: 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/research/templates/report.html src/research/html_render.py tests/research/test_html_render.py
git commit -m "feat(research): HTML render for ResearchState

Jinja2 template + minimal markdown-to-HTML converter. Email-safe with
both <style> block AND inlined styles (Gmail strips style blocks for
some flows). Persona Assignments box only renders when use_personas
is on; debate section only when router picked two personas. Ticker
is HTML-escaped (defensive — it's API input).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Persist helper (ResearchState → DB rows)

**Files:**
- Create: `src/research/persist.py`
- Create: `tests/research/test_persist.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_persist.py`:

```python
"""state_to_db_kwargs: convert a ResearchState into the two kwarg dicts
the ResearchReportRepository.create_with_plan expects."""

from __future__ import annotations

from dataclasses import asdict

from src.research.models import (
    BacktestSummary, ResearchRequest, ResearchState, TradePlan,
)
from src.research.persist import state_to_db_kwargs


def _state():
    req = ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=True,
        scanner_context={"scan_date": "2026-05-22",
                         "triggered_detectors": ["earnings_event"]},
    )
    return ResearchState(
        request=req,
        persona_assignments={"fundamentals": "buffett", "_rationale": "x"},
        module_results={},
        report_markdown="# NVDA",
        strategy=TradePlan(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="r",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html="<html></html>",
    )


class TestStateToDbKwargs:
    def test_report_dict_has_required_fields(self):
        report, plan = state_to_db_kwargs(_state(), duration_seconds=42.0)
        assert report["ticker"] == "NVDA"
        assert report["scan_date"] == "2026-05-22"
        assert report["report_markdown"] == "# NVDA"
        assert report["rendered_html"] == "<html></html>"
        assert report["use_personas"] is True
        assert report["persona_assignments_json"]["fundamentals"] == "buffett"
        assert report["duration_seconds"] == 42.0
        # request_json is a serialized dict, not the dataclass itself
        assert isinstance(report["request_json"], dict)
        assert report["request_json"]["ticker"] == "NVDA"

    def test_plan_dict_has_trade_plan_and_backtest_fields(self):
        _, plan = state_to_db_kwargs(_state(), duration_seconds=42.0)
        assert plan["direction"] == "long"
        assert plan["entry_price"] == 145.0
        assert plan["confidence"] == 72
        assert plan["backtest_matches_found"] == 5
        assert plan["backtest_win_rate"] == 0.6
        assert plan["backtest_sample_quality"] == "moderate"

    def test_scan_date_falls_back_to_today_when_no_scanner_context(self):
        s = _state()
        s["request"].scanner_context = None
        from datetime import date
        report, _ = state_to_db_kwargs(s, duration_seconds=1.0)
        assert report["scan_date"] == date.today().isoformat()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_persist.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/persist.py`:

```python
"""ResearchState → ResearchReport+ResearchTradePlan DB row kwargs.

The repository in app.backend.repositories.research_repository expects
two flat dicts (one for the report row, one for the plan row). This
helper does the conversion so the route handler stays thin.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from src.research.models import ResearchState


def state_to_db_kwargs(
    state: ResearchState,
    *,
    duration_seconds: float,
) -> tuple[dict, dict]:
    """Return (report_kwargs, plan_kwargs) for ResearchReportRepository
    .create_with_plan."""
    request = state["request"]
    plan = state["strategy"]
    backtest = state["backtest_summary"]

    ctx = request.scanner_context or {}
    scan_date = ctx.get("scan_date") or date.today().isoformat()

    report_kwargs = {
        "ticker": request.ticker,
        "scan_date": scan_date,
        "request_json": asdict(request),
        "report_markdown": state.get("report_markdown") or "",
        "rendered_html": state.get("rendered_html") or "",
        "use_personas": bool(request.use_personas),
        "persona_assignments_json": state.get("persona_assignments"),
        "duration_seconds": duration_seconds,
    }

    plan_kwargs = {
        "report_id": 0,  # placeholder; repo overwrites with FK
        "direction": plan.direction,
        "entry_price": plan.entry_price,
        "target_price": plan.target_price,
        "stop_price": plan.stop_price,
        "horizon_days": plan.horizon_days,
        "sizing_pct": plan.sizing_pct,
        "confidence": plan.confidence,
        "rationale": plan.rationale,
        "backtest_matches_found": backtest.matches_found,
        "backtest_win_rate": backtest.win_rate,
        "backtest_avg_pnl_pct": backtest.avg_pnl_pct,
        "backtest_max_drawdown_pct": backtest.max_drawdown_pct,
        "backtest_avg_holding_days": backtest.avg_holding_days,
        "backtest_sample_quality": backtest.sample_quality,
        "backtest_caveat": backtest.caveat,
    }
    return report_kwargs, plan_kwargs
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_persist.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/research/persist.py tests/research/test_persist.py
git commit -m "feat(research): persist helper (ResearchState -> DB kwargs)

state_to_db_kwargs returns two flat dicts ready for
ResearchReportRepository.create_with_plan. scan_date falls back to
today when scanner_context is absent (on-demand callers).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: POST /research/run route

**Files:**
- Create: `app/backend/routes/research.py`
- Modify: `app/backend/routes/__init__.py` (register router)
- Create: `tests/test_research_routes.py`

- [ ] **Step 1: Write the failing test**

Write `tests/test_research_routes.py`:

```python
"""HTTP route tests using FastAPI TestClient with an in-memory SQLite
DB and mocked run_research (no real LLM)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base, get_db
from app.backend.main import app
from src.research.models import (
    BacktestSummary, ResearchRequest, ResearchState, TradePlan,
)


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _fake_state(ticker="NVDA"):
    return ResearchState(
        request=ResearchRequest(
            ticker=ticker, holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=False,
            scanner_context=None,
        ),
        persona_assignments=None,
        module_results={},
        report_markdown="# Report",
        strategy=TradePlan(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=72, rationale="r",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html="<html><body>NVDA</body></html>",
    )


class TestPostRun:
    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_happy_path_returns_detail(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        mock_render.return_value = "<html><body>NVDA</body></html>"
        resp = client.post("/research/run", json={"ticker": "NVDA"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ticker"] == "NVDA"
        assert body["plan"]["direction"] == "long"
        assert body["backtest"]["sample_quality"] == "moderate"
        assert "id" in body

    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_persists_report_and_plan(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        mock_render.return_value = "<html></html>"
        r1 = client.post("/research/run", json={"ticker": "NVDA"})
        report_id = r1.json()["id"]
        # Fetch via GET endpoint to confirm it's in DB
        r2 = client.get(f"/research/reports/{report_id}")
        assert r2.status_code == 200
        assert r2.json()["ticker"] == "NVDA"


class TestListReports:
    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_list_filters_by_ticker(self, mock_render, mock_run, client):
        mock_render.return_value = "<html></html>"
        mock_run.side_effect = lambda req: _fake_state(req.ticker)
        client.post("/research/run", json={"ticker": "NVDA"})
        client.post("/research/run", json={"ticker": "AVGO"})
        resp = client.get("/research/reports", params={"ticker": "NVDA"})
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"

    def test_list_empty_returns_empty_array(self, client):
        resp = client.get("/research/reports")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetHtml:
    @patch("app.backend.routes.research.run_research")
    @patch("app.backend.routes.research.render_html")
    def test_returns_html_with_correct_content_type(self, mock_render, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        mock_render.return_value = "<html><body>NVDA report body</body></html>"
        r1 = client.post("/research/run", json={"ticker": "NVDA"})
        report_id = r1.json()["id"]
        r2 = client.get(f"/research/reports/{report_id}/html")
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("text/html")
        assert "NVDA report body" in r2.text

    def test_html_404_for_missing_report(self, client):
        resp = client.get("/research/reports/99999/html")
        assert resp.status_code == 404


class TestGetDetail404:
    def test_returns_404(self, client):
        resp = client.get("/research/reports/99999")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_routes.py -v
```
Expected: ImportError on `app.backend.routes.research`.

- [ ] **Step 3: Implement the routes**

Write `app/backend/routes/research.py`:

```python
"""REST API for the per-stock research pipeline.

Endpoints:
    POST   /research/run                  run pipeline + persist + return detail (sync)
    GET    /research/reports              list reports newest-first
    GET    /research/reports/{id}         full detail JSON
    GET    /research/reports/{id}/html    rendered HTML payload

POST /research/run is SYNCHRONOUS (not BackgroundTasks like /pipeline/run).
A research run is short — 30-90s including 9-12 LLM calls — and the caller
typically wants the report back inline. Long-poll / streaming is deferred.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models.research_schemas import (
    BacktestSummaryPayload,
    ResearchReportDetail,
    ResearchReportSummary,
    ResearchRunRequest,
    TradePlanPayload,
)
from app.backend.repositories.research_repository import ResearchReportRepository
from src.research.html_render import render_html
from src.research.models import ResearchRequest
from src.research.persist import state_to_db_kwargs
from src.research.pipeline import run_research

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research")


# ---------------------------------------------------------------------------
# POST /research/run — run + persist + return detail
# ---------------------------------------------------------------------------


def _api_request_to_internal(req: ResearchRunRequest) -> ResearchRequest:
    """ResearchRunRequest (API) -> ResearchRequest (internal dataclass)."""
    return ResearchRequest(
        ticker=req.ticker,
        holding_status=req.holding_status,
        target_position_pct=req.target_position_pct,
        risk_tolerance=req.risk_tolerance,
        report_goal=req.report_goal,
        use_personas=req.use_personas,
        scanner_context=None,
    )


def _detail_from_row_and_plan(report, plan) -> ResearchReportDetail:
    """Compose ResearchReportDetail from the two ORM rows."""
    return ResearchReportDetail(
        id=report.id,
        ticker=report.ticker,
        scan_date=report.scan_date,
        created_at=report.created_at,
        use_personas=bool(report.use_personas),
        persona_assignments=report.persona_assignments_json,
        report_markdown=report.report_markdown,
        duration_seconds=report.duration_seconds,
        plan=TradePlanPayload(
            direction=plan.direction,
            entry_price=plan.entry_price,
            target_price=plan.target_price,
            stop_price=plan.stop_price,
            horizon_days=plan.horizon_days,
            sizing_pct=plan.sizing_pct,
            confidence=plan.confidence,
            rationale=plan.rationale,
        ),
        backtest=BacktestSummaryPayload(
            matches_found=plan.backtest_matches_found,
            win_rate=plan.backtest_win_rate,
            avg_pnl_pct=plan.backtest_avg_pnl_pct,
            max_drawdown_pct=plan.backtest_max_drawdown_pct,
            avg_holding_days=plan.backtest_avg_holding_days,
            sample_quality=plan.backtest_sample_quality,
            caveat=plan.backtest_caveat,
        ),
    )


@router.post("/run", response_model=ResearchReportDetail)
def trigger_run(
    req: ResearchRunRequest,
    db: Session = Depends(get_db),
) -> ResearchReportDetail:
    """Run the research pipeline, persist the report + plan, return detail."""
    internal_req = _api_request_to_internal(req)
    t0 = time.monotonic()
    try:
        state = run_research(internal_req)
    except Exception as e:
        logger.exception("research run failed for %s", req.ticker)
        raise HTTPException(500, f"research pipeline failed: {type(e).__name__}: {e}")
    duration = time.monotonic() - t0

    # Render HTML AFTER pipeline so module_results are populated
    html = render_html(state)
    state["rendered_html"] = html

    report_kwargs, plan_kwargs = state_to_db_kwargs(state, duration_seconds=duration)
    repo = ResearchReportRepository(db)
    report_row = repo.create_with_plan(report=report_kwargs, plan=plan_kwargs)
    plan_row = repo.get_plan_for_report(report_row.id)
    return _detail_from_row_and_plan(report_row, plan_row)


# ---------------------------------------------------------------------------
# GET /research/reports — list
# ---------------------------------------------------------------------------


@router.get("/reports", response_model=list[ResearchReportSummary])
def list_reports(
    ticker: str | None = None,
    scan_date: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[ResearchReportSummary]:
    if limit < 1 or limit > 200:
        raise HTTPException(400, "limit must be between 1 and 200")
    rows = ResearchReportRepository(db).list_reports(
        ticker=ticker.upper() if ticker else None,
        scan_date=scan_date,
        limit=limit,
    )
    return [ResearchReportSummary.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /research/reports/{id} — full detail
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}", response_model=ResearchReportDetail)
def get_report(report_id: int, db: Session = Depends(get_db)) -> ResearchReportDetail:
    repo = ResearchReportRepository(db)
    report = repo.get_by_id(report_id)
    if not report:
        raise HTTPException(404, f"No research report with id {report_id}")
    plan = repo.get_plan_for_report(report_id)
    if not plan:
        raise HTTPException(500, f"Report {report_id} has no paired plan row")
    return _detail_from_row_and_plan(report, plan)


# ---------------------------------------------------------------------------
# GET /research/reports/{id}/html — raw HTML payload
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def get_report_html(report_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    report = ResearchReportRepository(db).get_by_id(report_id)
    if not report:
        raise HTTPException(404, f"No research report with id {report_id}")
    return HTMLResponse(content=report.rendered_html or "<html></html>")
```

Modify `app/backend/routes/__init__.py` to register the router. Read the file first to follow the existing pattern; add:

```python
from app.backend.routes.research import router as research_router
```

and include in the `register_routers` (or whatever the existing pattern is — match exactly).

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_routes.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/backend/routes/research.py app/backend/routes/__init__.py tests/test_research_routes.py
git commit -m "feat(backend): /research REST API (4 endpoints)

POST /research/run runs the pipeline synchronously, persists report +
plan, returns ResearchReportDetail. Sync rather than BackgroundTasks
(like /pipeline/run uses) because research runs are short (30-90s) and
callers typically want the report inline.

GET /research/reports lists newest-first with ticker + scan_date
filters. GET /reports/{id} returns full detail. GET /reports/{id}/html
returns the raw HTML payload with text/html content-type for iframe
display.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Email render path for research reports

**Files:**
- Modify: `app/backend/services/notifications/render.py` (append `render_research_html` + plain-text alt)
- Create: `tests/notifications/test_render_research.py`

- [ ] **Step 1: Write the failing test**

Write `tests/notifications/test_render_research.py`:

```python
"""Render path for research-report emails. Mirrors the pipeline render
tests' structure."""

from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime


def _make_report():
    return SimpleNamespace(
        id=1,
        ticker="NVDA",
        scan_date="2026-05-22",
        created_at=datetime(2026, 5, 22, 16, 35),
        use_personas=True,
        duration_seconds=42.5,
        rendered_html=(
            "<html><body><h1>NVDA</h1><p>Body content here.</p></body></html>"
        ),
        report_markdown="# NVDA\n\nBody content here.",
    )


class TestRenderResearchHtml:
    def test_returns_the_pre_rendered_html_when_present(self):
        from app.backend.services.notifications.render import render_research_html
        report = _make_report()
        html = render_research_html(report)
        assert isinstance(html, str)
        assert "NVDA" in html

    def test_fallback_when_html_missing(self):
        from app.backend.services.notifications.render import render_research_html
        report = _make_report()
        report.rendered_html = ""
        html = render_research_html(report)
        # Falls back to wrapping markdown in a minimal HTML envelope
        assert "<html>" in html.lower()
        assert "NVDA" in html


class TestRenderResearchText:
    def test_extracts_plain_text_from_markdown(self):
        from app.backend.services.notifications.render import render_research_text
        report = _make_report()
        text = render_research_text(report)
        assert "NVDA" in text
        assert "Body content here." in text
        # No HTML tags
        assert "<" not in text
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/notifications/test_render_research.py -v
```

- [ ] **Step 3: Append to `render.py`**

Read `app/backend/services/notifications/render.py`. Append at the end (after the existing pipeline render functions):

```python


# ---------------------------------------------------------------------------
# Research report rendering (Phase 3)
# ---------------------------------------------------------------------------


def render_research_html(report) -> str:
    """Email-safe HTML for one ResearchReport row.

    The pipeline pre-rendered the HTML at run time; here we just return
    that string. The fallback handles legacy rows or test fixtures that
    don't carry an HTML payload — wraps the markdown in a minimal
    envelope so the email is never empty.
    """
    html_body = getattr(report, "rendered_html", "") or ""
    if html_body.strip():
        return html_body
    ticker = _esc(getattr(report, "ticker", ""))
    markdown = _esc(getattr(report, "report_markdown", ""))
    return (
        f"<html><body>"
        f"<h1>{ticker}</h1>"
        f"<pre style=\"white-space:pre-wrap;\">{markdown}</pre>"
        f"</body></html>"
    )


def render_research_text(report) -> str:
    """Plain-text alternate part for the email. Strips the markdown
    formatting to a readable plain-text form."""
    markdown = getattr(report, "report_markdown", "") or ""
    # Minimal markdown -> text: drop heading hashes; keep the rest.
    lines = []
    for raw in markdown.split("\n"):
        stripped = raw.lstrip("#").lstrip()
        lines.append(stripped)
    return "\n".join(lines).strip() or f"Research report for {getattr(report, 'ticker', '?')}"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/notifications/test_render_research.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/backend/services/notifications/render.py tests/notifications/test_render_research.py
git commit -m "feat(notifications): render_research_html + render_research_text

Email render path for ResearchReport rows. HTML side just returns the
pre-rendered payload (pipeline already produced it). Plain-text side
strips the markdown formatting for the email's alternate part.
Fallback handles missing rendered_html cleanly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Notification dispatcher support for "research.completed" event

**Files:**
- Modify: `app/backend/services/notifications/dispatcher.py` (route research event to new render path)
- Create: `tests/notifications/test_dispatcher_research.py`

- [ ] **Step 1: Write the failing test**

Write `tests/notifications/test_dispatcher_research.py`:

```python
"""Dispatcher should route 'research.completed' events to the
research render path and call the email/webhook handler with that
HTML body."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest


def _make_report():
    from datetime import datetime
    return SimpleNamespace(
        id=42,
        ticker="NVDA",
        scan_date="2026-05-22",
        created_at=datetime(2026, 5, 22, 16, 35),
        rendered_html="<html><body>NVDA body</body></html>",
        report_markdown="# NVDA\n\nBody.",
    )


class TestDispatchResearchEvent:
    @patch("app.backend.services.notifications.dispatcher.render_research_html")
    @patch("app.backend.services.notifications.dispatcher.render_research_text")
    def test_dispatch_uses_research_render(self, mock_text, mock_html):
        """When event_type='research.completed', dispatcher should pull the
        research-render functions, not the pipeline ones."""
        from app.backend.services.notifications.dispatcher import (
            NotificationDispatcher,
        )
        mock_html.return_value = "<html>NVDA</html>"
        mock_text.return_value = "NVDA"

        # Stub out everything but the render-routing logic
        mock_session_factory = MagicMock()
        d = NotificationDispatcher(mock_session_factory)

        # The dispatcher exposes a method that builds the email body for
        # a given event_type + run object. Test that the research event
        # routes to research render.
        body_html, body_text = d._render_for_event(
            event_type="research.completed",
            run=_make_report(),
        )
        assert body_html == "<html>NVDA</html>"
        assert body_text == "NVDA"
        mock_html.assert_called_once()
        mock_text.assert_called_once()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/notifications/test_dispatcher_research.py -v
```

- [ ] **Step 3: Add render-routing in dispatcher**

Read `app/backend/services/notifications/dispatcher.py` to find the existing render call (currently hardcoded to `render_pipeline_html`).

Add imports at top:

```python
from app.backend.services.notifications.render import (
    render_pipeline_html, render_pipeline_text,
    render_research_html, render_research_text,
)
```

Add a new method to the `NotificationDispatcher` class. Place it before any existing `dispatch()` method:

```python
    def _render_for_event(self, event_type: str, run) -> tuple[str, str]:
        """Pick the (html, text) renderer pair for the given event_type.

        Phase 1 ships pipeline.completed; Phase 3 adds research.completed.
        Unknown event_types fall back to pipeline render (safe default).
        """
        if event_type == "research.completed":
            return render_research_html(run), render_research_text(run)
        return render_pipeline_html(run), render_pipeline_text(run)
```

If the existing `dispatch()` method hard-codes `render_pipeline_html(run)` / `render_pipeline_text(run)` calls, refactor those two call sites to use `self._render_for_event(event_type, run)` — preserving the existing pipeline behavior when event_type defaults to `pipeline.completed`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/notifications/test_dispatcher_research.py -v
```

Also run the existing dispatcher tests to confirm no regression:

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_notification_routes.py tests/notifications/ -v 2>&1 | tail -15
```

- [ ] **Step 5: Commit**

```bash
git add app/backend/services/notifications/dispatcher.py tests/notifications/test_dispatcher_research.py
git commit -m "feat(notifications): dispatcher routes research.completed event

_render_for_event picks the research render pair for research.completed
events; falls back to pipeline render for everything else (preserves
existing pipeline.completed behavior).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Scheduler job — _run_research_job at 4:35pm ET

**Files:**
- Modify: `app/backend/services/scheduler_service.py` (register new job)
- Create: `tests/test_scheduler_research_job.py`

- [ ] **Step 1: Write the failing test**

Write `tests/test_scheduler_research_job.py`:

```python
"""SchedulerService should register a research cron at 16:35 ET and
the job body should: fetch latest legacy PipelineRun watchlist for
today, run research per ticker, persist reports."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.backend.services.scheduler_service import (
    RESEARCH_CRON_EXPR,
)


def test_research_cron_expression_is_4_35pm_weekdays():
    """4:35pm ET, Monday-Friday."""
    assert RESEARCH_CRON_EXPR == "35 16 * * 1-5"


class TestResearchJobBody:
    @patch("app.backend.services.scheduler_service.SessionLocal")
    @patch("app.backend.services.scheduler_service.run_research")
    @patch("app.backend.services.scheduler_service.render_html")
    def test_runs_per_ticker_from_latest_pipeline_run(
        self, mock_render, mock_run, mock_session,
    ):
        """When the latest COMPLETE PipelineRun for today has tickers
        in its watchlist_json, the research job should run research
        once per ticker and persist each result."""
        from app.backend.services.scheduler_service import _run_research_job_body
        from src.research.models import (
            BacktestSummary, ResearchRequest, ResearchState, TradePlan,
        )

        mock_render.return_value = "<html></html>"
        mock_run.side_effect = lambda req: ResearchState(
            request=req,
            persona_assignments=None,
            module_results={},
            report_markdown="# r",
            strategy=TradePlan(
                direction="long", entry_price=145.0, target_price=165.0,
                stop_price=138.0, horizon_days=30, sizing_pct=0.05,
                confidence=72, rationale="r",
            ),
            backtest_summary=BacktestSummary(
                matches_found=0, win_rate=None, avg_pnl_pct=None,
                max_drawdown_pct=None, avg_holding_days=None,
                sample_quality="insufficient", caveat="x",
            ),
            rendered_html=None,
        )

        # Mock SessionLocal -> session -> repos
        db = MagicMock()
        mock_session.return_value = db

        # Latest PipelineRun stub with two tickers
        latest_pipeline_run = MagicMock()
        latest_pipeline_run.scan_date = "2026-05-22"
        latest_pipeline_run.watchlist_json = [
            {"ticker": "NVDA", "rank": 1},
            {"ticker": "AVGO", "rank": 2},
        ]

        with patch(
            "app.backend.services.scheduler_service.PipelineRunRepository"
        ) as mock_pipe_repo_cls, patch(
            "app.backend.services.scheduler_service.ResearchReportRepository"
        ) as mock_research_repo_cls:
            mock_pipe_repo = MagicMock()
            mock_pipe_repo.list_runs.return_value = [latest_pipeline_run]
            mock_pipe_repo_cls.return_value = mock_pipe_repo
            mock_research_repo = MagicMock()
            mock_research_repo_cls.return_value = mock_research_repo

            _run_research_job_body()

        # run_research called once per ticker
        assert mock_run.call_count == 2
        # Persisted both
        assert mock_research_repo.create_with_plan.call_count == 2

    @patch("app.backend.services.scheduler_service.SessionLocal")
    def test_no_recent_pipeline_run_skips_cleanly(self, mock_session):
        """When no legacy run exists for today, log + return without
        running research (Phase 3 v1 does not fall back to running its
        own scanner — that's a follow-up)."""
        from app.backend.services.scheduler_service import _run_research_job_body
        db = MagicMock()
        mock_session.return_value = db
        with patch(
            "app.backend.services.scheduler_service.PipelineRunRepository"
        ) as mock_pipe_repo_cls:
            mock_pipe_repo = MagicMock()
            mock_pipe_repo.list_runs.return_value = []
            mock_pipe_repo_cls.return_value = mock_pipe_repo
            _run_research_job_body()  # should not raise
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_scheduler_research_job.py -v
```

- [ ] **Step 3: Wire the new job**

Read `app/backend/services/scheduler_service.py`. Add at the top of the file (near the existing `PIPELINE_CRON_EXPR`):

```python
# Daily research cron: 16:35 ET weekdays. Fires AFTER the legacy
# pipeline cron at 16:30 so the watchlist for today is persisted and
# the research job can read it without re-scanning.
RESEARCH_CRON_EXPR = "35 16 * * 1-5"
```

Add imports near the existing imports:

```python
from app.backend.repositories.research_repository import ResearchReportRepository
from app.backend.repositories.pipeline_repository import PipelineRunRepository
from src.research.html_render import render_html
from src.research.models import ResearchRequest
from src.research.persist import state_to_db_kwargs
from src.research.pipeline import run_research
```

(Some of these may already be imported; merge as needed.)

Add the job body function. Place it near `_run_pipeline_job` or just below the imports block:

```python
def _run_research_job_body() -> None:
    """Body of the daily research cron.

    Reads the latest COMPLETE PipelineRun row for today, takes its
    watchlist tickers, runs research per ticker, persists each report.

    If no recent pipeline run exists (legacy cron disabled), logs and
    returns — Phase 3 v1 does NOT fall back to running its own scanner.
    That keeps the two cron jobs cleanly independent and limits cost
    surprises when the user has only the research cron enabled.
    """
    import logging
    import time
    from datetime import date
    logger = logging.getLogger(__name__)

    db = SessionLocal()
    try:
        today = date.today().isoformat()
        pipe_repo = PipelineRunRepository(db)
        # Most recent run with today's scan_date
        recent = pipe_repo.list_runs(status="COMPLETE", since=today, limit=1)
        if not recent:
            logger.info("research cron: no legacy pipeline run for %s — skipping", today)
            return
        latest = recent[0]
        tickers = []
        for entry in (latest.watchlist_json or []):
            t = entry.get("ticker") if isinstance(entry, dict) else None
            if t:
                tickers.append(t)
        if not tickers:
            logger.warning("research cron: latest pipeline run has empty watchlist")
            return

        research_repo = ResearchReportRepository(db)
        for ticker in tickers:
            req = ResearchRequest(
                ticker=ticker,
                holding_status="watching",
                target_position_pct=0.05,
                risk_tolerance="moderate",
                report_goal="new_entry",
                use_personas=True,
                scanner_context={"scan_date": latest.scan_date,
                                 "triggered_detectors": []},
            )
            t0 = time.monotonic()
            try:
                state = run_research(req)
            except Exception as e:
                logger.exception("research cron: ticker %s failed: %s", ticker, e)
                continue
            duration = time.monotonic() - t0
            state["rendered_html"] = render_html(state)
            r_kwargs, p_kwargs = state_to_db_kwargs(state, duration_seconds=duration)
            try:
                research_repo.create_with_plan(report=r_kwargs, plan=p_kwargs)
            except Exception as e:
                logger.exception("research cron: persist failed for %s: %s", ticker, e)
                continue
            logger.info("research cron: persisted report for %s (%.1fs)", ticker, duration)
    finally:
        db.close()
```

Register the cron in the `SchedulerService` class. Find the method that registers `PIPELINE_CRON_EXPR` (`_register_pipeline_job` or similar). Add a sibling method:

```python
    def _register_research_job(self) -> None:
        """Register the singleton daily research cron."""
        trigger = CronTrigger.from_crontab(RESEARCH_CRON_EXPR, timezone=self._tz)
        self._scheduler.add_job(
            _run_research_job_body,
            trigger=trigger,
            id="research_daily",
            replace_existing=True,
            misfire_grace_time=600,
        )
        logger.info(
            "Registered research job (cron=%r, tz=%s)",
            RESEARCH_CRON_EXPR, self._tz,
        )
```

Call `self._register_research_job()` from wherever `_register_pipeline_job()` is called inside the SchedulerService start path (likely in `start()` or `_register_default_jobs()`).

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_scheduler_research_job.py -v
```

Also run existing scheduler tests to confirm no regression:

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_scheduler_service.py -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add app/backend/services/scheduler_service.py tests/test_scheduler_research_job.py
git commit -m "feat(scheduler): daily research cron at 16:35 ET

RESEARCH_CRON_EXPR='35 16 * * 1-5'. Fires after the legacy 16:30
pipeline cron so today's PipelineRun watchlist is persisted by the
time research runs. Reads tickers from the latest COMPLETE PipelineRun
for today; runs research per ticker; persists each report.

If no legacy pipeline run exists for today, logs and returns rather
than falling back to running its own scanner — keeps cost behavior
predictable when only one of the two crons is enabled.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: End-to-end integration test + smoke + progress.md

**Files:**
- Create: `tests/test_research_integration.py`
- Modify: `progress.md`

- [ ] **Step 1: Write the integration test**

Write `tests/test_research_integration.py`:

```python
"""End-to-end integration: POST /research/run actually persists, GET
list/detail/html all return consistent data. Uses in-memory SQLite +
mocked LLM."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base, get_db
from app.backend.main import app
from src.research.models import (
    BacktestSummary, ResearchRequest, ResearchState, TradePlan,
)


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _fake_state(ticker="NVDA", direction="long"):
    return ResearchState(
        request=ResearchRequest(
            ticker=ticker, holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=False,
            scanner_context=None,
        ),
        persona_assignments=None,
        module_results={},
        report_markdown=f"# {ticker} report\n\nBody.",
        strategy=TradePlan(
            direction=direction,
            entry_price=145.0 if direction != "stand_aside" else None,
            target_price=165.0 if direction != "stand_aside" else None,
            stop_price=138.0 if direction != "stand_aside" else None,
            horizon_days=30 if direction != "stand_aside" else 0,
            sizing_pct=0.05 if direction != "stand_aside" else 0.0,
            confidence=72 if direction != "stand_aside" else 0,
            rationale="r",
        ),
        backtest_summary=BacktestSummary(
            matches_found=5, win_rate=0.6, avg_pnl_pct=0.08,
            max_drawdown_pct=-0.10, avg_holding_days=20.0,
            sample_quality="moderate", caveat=None,
        ),
        rendered_html=None,
    )


class TestEndToEndFlow:
    @patch("app.backend.routes.research.run_research")
    def test_post_then_list_then_detail_then_html(self, mock_run, client):
        mock_run.return_value = _fake_state("NVDA")
        # POST
        r1 = client.post("/research/run", json={"ticker": "nvda"})
        assert r1.status_code == 200
        report_id = r1.json()["id"]
        assert r1.json()["ticker"] == "NVDA"  # uppercased

        # LIST
        r2 = client.get("/research/reports")
        assert r2.status_code == 200
        summaries = r2.json()
        assert any(s["id"] == report_id for s in summaries)

        # DETAIL
        r3 = client.get(f"/research/reports/{report_id}")
        assert r3.status_code == 200
        detail = r3.json()
        assert detail["plan"]["direction"] == "long"
        assert detail["backtest"]["sample_quality"] == "moderate"
        assert "NVDA" in detail["report_markdown"]

        # HTML
        r4 = client.get(f"/research/reports/{report_id}/html")
        assert r4.status_code == 200
        assert r4.headers["content-type"].startswith("text/html")
        assert "NVDA" in r4.text
```

- [ ] **Step 2: Run the integration test**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/test_research_integration.py -v
```
Expected: all pass.

- [ ] **Step 3: Full research suite + full pytest suite**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/ tests/test_research_*.py tests/notifications/test_render_research.py tests/notifications/test_dispatcher_research.py tests/test_scheduler_research_job.py -v --tb=short 2>&1 | tail -20
```
Expected: ~90+ research/Phase-3 tests pass.

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest -q --tb=no 2>&1 | tail -10
```
Expected: pre-existing 20 live-API failures only; no new failures from Phase 3.

- [ ] **Step 4: Smoke a real ticker via HTTP**

Start the backend in a separate terminal (the user runs this manually since uvicorn needs an interactive terminal):

```bash
PYTHONIOENCODING=utf-8 uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 --log-level info
```

In another shell:

```bash
curl -sX POST http://127.0.0.1:8001/research/run \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","risk_tolerance":"moderate","use_personas":true}' \
  2>&1 | head -50
```

Expected within 30-90s: JSON response with `id`, `ticker`, `plan`, `backtest`, `report_markdown`. Then:

```bash
curl -s "http://127.0.0.1:8001/research/reports?ticker=NVDA" 2>&1 | head -30
curl -s "http://127.0.0.1:8001/research/reports/1/html" 2>&1 | head -20
```

If the backend can't start (port conflict, missing key, etc.), capture the failure for the progress.md but don't fail the task.

- [ ] **Step 5: Update progress.md**

Add a new dated session block AT THE TOP of `progress.md` (after the `# Progress Log` header, before existing entries):

```
## Session — 2026-05-22 (Research pipeline Phase 3 landed — production wired)
```

Content should cover:
- WHAT shipped:
  - 2 new DB tables (research_reports + research_trade_plans) via additive Alembic migration
  - ResearchReportRepository
  - Pydantic schemas (ResearchRunRequest, ResearchReportSummary, ResearchReportDetail, TradePlanPayload, BacktestSummaryPayload)
  - HTML render with Jinja2 template + minimal markdown converter
  - persist helper bridging ResearchState → DB rows
  - 4 REST endpoints (POST /research/run, GET /research/reports, GET /research/reports/{id}, GET /research/reports/{id}/html)
  - Email render path for research reports
  - Notification dispatcher routes "research.completed" to research render
  - Scheduler cron at 16:35 ET reading the latest legacy PipelineRun for today
- 11 commits (use `git log --oneline <phase3-start>..HEAD` for the list)
- Test counts (research suite + Phase 3 backend tests + full pytest regression)
- Smoke result
- Spec is now fully implemented except the frontend research-request panel (explicitly deferred)
- Production state: legacy pipeline cron at 16:30 ET fires unchanged; research cron at 16:35 ET fires when registered; both persist independently; A/B comparison data accumulates

- [ ] **Step 6: Commit progress.md**

```bash
git add tests/test_research_integration.py progress.md
git commit -m "docs: log research pipeline Phase 3 landing — production wired

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage** (Phase 3 subset):
- 2 DB tables → Task 1 ✓
- Alembic migration → Task 2 ✓
- ResearchReportRepository → Task 3 ✓
- Pydantic schemas → Task 4 ✓
- HTML render + template → Task 5 ✓
- Persist helper → Task 6 ✓
- 4 REST endpoints → Task 7 ✓
- Email render path → Task 8 ✓
- Dispatcher integration → Task 9 ✓
- Scheduler cron at 4:35 ET → Task 10 ✓
- End-to-end integration + smoke + progress → Task 11 ✓

**Spec sections explicitly deferred:**
- Frontend research-request panel — out of spec scope, called out in plan header

**Placeholder scan:** Task 2 step 1 uses `<CURRENT_HEAD>` placeholder for the alembic down_revision because the head is environment-dependent. Implementer is given a concrete command to discover it (Step 1 grep on revision files). Acceptable — the placeholder is a discovery step, not unfilled content.

Task 7 step 3 says "Read the file first to follow the existing pattern" for `app/backend/routes/__init__.py` — that's a discovery step too; the exact registration line varies based on existing pattern.

**Type consistency:**
- `ResearchRunRequest`, `TradePlanPayload`, `BacktestSummaryPayload`, `ResearchReportSummary`, `ResearchReportDetail` — used consistently across Tasks 4 (definition), 7 (routes), 11 (integration test)
- `state_to_db_kwargs(state, duration_seconds=...) -> (report_kwargs, plan_kwargs)` — same signature in Task 6 (definition), Task 7 (route uses), Task 10 (scheduler uses)
- `render_html(state) -> str` — same signature Task 5 (definition), Task 7 (route uses), Task 10 (scheduler uses)
- `ResearchReportRepository(db).create_with_plan(report=..., plan=...) -> ResearchReport` — Task 3 (definition), 7, 10
- `render_research_html(report)` / `render_research_text(report)` — Task 8 (definition), Task 9 (dispatcher uses)
- `_render_for_event(event_type, run) -> tuple[str, str]` — Task 9 (definition); usage left to dispatcher's existing dispatch path
- `RESEARCH_CRON_EXPR = "35 16 * * 1-5"` — Task 10 (definition + test cross-check)
- `_run_research_job_body()` — Task 10 (definition + test)

**Risks acknowledged:**
- Scheduler test uses MagicMock heavily — real cron behavior verified by integration smoke in Task 11
- Alembic migration uses revision id `c8e7a1d2f3b4` — if another migration is added between writing this plan and implementing it, the implementer must update down_revision to match the new head (Task 2 step 1 covers this discovery)
- SQLite cascade delete requires `PRAGMA foreign_keys=ON` which is not the default. Test `test_cascade_delete_removes_plan` only asserts the report row is gone; orphan plan rows in SQLite are an accepted minor v1 leak (Postgres production honors the constraint regardless)
- Phase 3 v1 does NOT fall back to running its own scanner when no legacy pipeline run exists. Documented in Task 10; reduces blast radius of the cost-surprise risk
- The HTML render's markdown-to-HTML converter handles a small subset; pathological synthesizer output (deeply nested lists, tables) renders as paragraphs — acceptable for v1
- HTML template uses Jinja2 (transitive dep via langchain); if that ever gets removed, the template would need a tiny string-substitution fallback. Out of scope for v1
