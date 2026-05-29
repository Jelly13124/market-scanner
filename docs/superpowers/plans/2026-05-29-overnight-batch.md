# Overnight Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Execute waves in STRICT order A → B → C → D; within a wave, tasks in order. "Do as much as fits the night" — whatever completes is shippable.

**Goal:** Overnight unattended batch — Screener Phase 2 (presets + cron + notify), test hardening, new Scanner detectors + A/B eval, Screener Phase 3 polish.

**Architecture:** Reuse established repo patterns — SQLAlchemy+Alembic models, Session-injected repositories, FastAPI routers under `/screener`, APScheduler cron jobs, the notification dispatcher, and the `EventDetector` ABC. Frontend reuses the Screener tab + analyze-bus + shadcn components.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, APScheduler, React/TS/Vite, shadcn/ui, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-overnight-batch-design.md`

---

## Global constraints (every task inherits these)

- **Python:** `C:\Users\Jerry\anaconda3\python.exe`; tests: `C:\Users\Jerry\anaconda3\python.exe -m pytest <paths> -q`. Set `$env:PYTHONIOENCODING="utf-8"` for any CLI with non-ASCII.
- **Frontend typecheck:** from `app/frontend/`: `node node_modules/typescript/bin/tsc --noEmit` (npm is NOT on the non-interactive PATH). Pre-existing errors in `agent-run-detail.tsx` + `lib/utils.ts` are fixed in B2; until then, filter them.
- **Backend run** (only if needed): from repo ROOT, `... -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 --log-level info` — NO `--reload`. Reset Bash cwd to repo root before launching (a leaked `app/frontend` cwd causes `No module named 'app'`).
- **Commits:** one per task; conventional message; **NO `Co-Authored-By:` trailer**; **never `--no-verify`** (the git-guard hook blocks both). The python-format hook runs black on edited `.py` automatically.
- **Migrations:** additive only. `id = BigInteger().with_variant(Integer(), "sqlite")` for new PKs (pure `BigInteger` does NOT autoincrement on SQLite — verified bug this session). Migration `down_revision` chains from the current head (`d4e8a2c1b9f6`); run `alembic heads` from `app/backend/` (cwd=app/backend, `PYTHONPATH`=repo root) to confirm.
- **No destructive ops on user data**: never delete reports/watchlists/scanner configs/DB rows the agent didn't create.
- **Ambiguity rule:** pick the sensible industry-default, proceed, append a one-line entry to `findings.md` (`AMBIGUITY: <what> → chose <X> because <why>`). NEVER block waiting for the user.
- **Per task:** backend → tests green; frontend → tsc clean; then commit; then append a line to `progress.md`.
- **Scanner detector tasks (Wave C):** after the implementer finishes each detector, the controller dispatches the `scanner-invariant-reviewer` subagent to gate it before moving on.

---

## WAVE 0 — baseline (no work)

Already committed at batch start: reports-tab `e785135`, spec `96db890`. Working tree clean. Proceed to Wave A.

---

# WAVE A — Screener Phase 2: presets + cron auto-run + notify-on-match

### Task A1: ScreenerPreset model + migration

**Files:**
- Modify: `app/backend/database/models.py` (append `ScreenerPreset`)
- Create: `app/backend/alembic/versions/e1a7c2f4b9d0_add_screener_presets.py`
- Test: `tests/screener/test_preset_models.py`

- [ ] **Step 1: Write the failing test**

```python
"""ScreenerPreset ORM smoke."""
from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.backend.database.models import Base, ScreenerPreset


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_insert_minimal(session):
    p = ScreenerPreset(name="cheap tech", market="US",
                       filters_json={"pe_max": 20, "sector_in": ["Technology"]})
    session.add(p); session.commit()
    out = session.query(ScreenerPreset).one()
    assert out.name == "cheap tech"
    assert out.filters_json["pe_max"] == 20
    assert out.schedule_enabled is False           # server default
    assert out.sort_by == "market_cap"


def test_full_fields(session):
    p = ScreenerPreset(name="x", market=None, filters_json={},
                       sort_by="pe_ttm", sort_dir="asc",
                       schedule_enabled=True, notify_channels=["email"],
                       last_match_count=5)
    session.add(p); session.commit()
    out = session.query(ScreenerPreset).one()
    assert out.schedule_enabled is True
    assert out.notify_channels == ["email"]
    assert out.last_match_count == 5
```

- [ ] **Step 2: Run → fails** (`ImportError: ScreenerPreset`).
  `C:\Users\Jerry\anaconda3\python.exe -m pytest tests/screener/test_preset_models.py -q`

- [ ] **Step 3: Append the model to `app/backend/database/models.py`**

```python
class ScreenerPreset(Base):
    """A saved Screener filter set, optionally run on a daily cron."""

    __tablename__ = "screener_presets"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"),
                primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    market = Column(String(8))                       # 'US' | 'CN' | None(all)
    filters_json = Column(JSON, nullable=False, default=dict)
    sort_by = Column(String(32), nullable=False, default="market_cap")
    sort_dir = Column(String(4), nullable=False, default="desc")
    schedule_enabled = Column(Boolean, nullable=False, default=False,
                              server_default=text("0"))
    notify_channels = Column(JSON)                   # ["email","webhook"]
    last_run_at = Column(DateTime(timezone=True))
    last_match_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                        nullable=False)
```

Ensure `Boolean`, `JSON`, `text` are imported at the top of `models.py` (add to the existing `from sqlalchemy import ...` line if missing — `text` comes from `sqlalchemy`).

- [ ] **Step 4: Run → 2 pass.**

- [ ] **Step 5: Create the migration.** Confirm head first:
```
cd app/backend ; $env:PYTHONPATH="C:\Users\Jerry\Desktop\ai-hedge-fund" ; C:\Users\Jerry\anaconda3\python.exe -m alembic heads
```
Expected head: `d4e8a2c1b9f6`. Write:

```python
"""add screener_presets table

Revision ID: e1a7c2f4b9d0
Revises: d4e8a2c1b9f6
Create Date: 2026-05-29 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e1a7c2f4b9d0"
down_revision: Union[str, None] = "d4e8a2c1b9f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screener_presets",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=8)),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("sort_by", sa.String(length=32), nullable=False,
                  server_default="market_cap"),
        sa.Column("sort_dir", sa.String(length=4), nullable=False,
                  server_default="desc"),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("notify_channels", sa.JSON()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_match_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("screener_presets")
```

- [ ] **Step 6: Apply + verify** (cd app/backend, PYTHONPATH=repo root):
```
... -m alembic upgrade head ; ... -m alembic downgrade -1 ; ... -m alembic upgrade head
```
Expected: clean. Then re-run the model test (still 2 pass).

- [ ] **Step 7: Commit** `feat(screener): ScreenerPreset model + migration`. Append to `progress.md`.

---

### Task A2: ScreenerPresetRepository

**Files:**
- Create: `app/backend/repositories/screener_preset_repository.py`
- Test: `tests/screener/test_preset_repository.py`

- [ ] **Step 1: Failing test**

```python
from __future__ import annotations
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.backend.database.models import Base, ScreenerPreset
from app.backend.repositories.screener_preset_repository import ScreenerPresetRepository


@pytest.fixture()
def repo():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    yield ScreenerPresetRepository(db)
    db.close()


def test_create_and_get(repo):
    p = repo.create(name="a", market="US", filters={"pe_max": 30},
                    sort_by="market_cap", sort_dir="desc")
    assert p.id is not None
    assert repo.get(p.id).name == "a"


def test_list_and_list_enabled(repo):
    repo.create(name="off", market="US", filters={})
    on = repo.create(name="on", market="US", filters={}, schedule_enabled=True,
                     notify_channels=["email"])
    assert len(repo.list()) == 2
    enabled = repo.list_enabled()
    assert [p.id for p in enabled] == [on.id]


def test_patch(repo):
    p = repo.create(name="a", market="US", filters={})
    repo.patch(p.id, {"name": "b", "schedule_enabled": True})
    out = repo.get(p.id)
    assert out.name == "b" and out.schedule_enabled is True


def test_delete(repo):
    p = repo.create(name="a", market="US", filters={})
    assert repo.delete(p.id) is True
    assert repo.get(p.id) is None
    assert repo.delete(999) is False


def test_mark_run(repo):
    p = repo.create(name="a", market="US", filters={})
    when = datetime.now(timezone.utc)
    repo.mark_run(p.id, match_count=7, when=when)
    out = repo.get(p.id)
    assert out.last_match_count == 7 and out.last_run_at is not None
```

- [ ] **Step 2: Run → fails (ImportError).**

- [ ] **Step 3: Implement**

```python
"""CRUD for screener_presets."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.backend.database.models import ScreenerPreset


class ScreenerPresetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, name: str, market: str | None, filters: dict,
               sort_by: str = "market_cap", sort_dir: str = "desc",
               schedule_enabled: bool = False,
               notify_channels: list[str] | None = None) -> ScreenerPreset:
        row = ScreenerPreset(
            name=name, market=market, filters_json=filters or {},
            sort_by=sort_by, sort_dir=sort_dir,
            schedule_enabled=schedule_enabled, notify_channels=notify_channels,
        )
        self.db.add(row); self.db.commit(); self.db.refresh(row)
        return row

    def get(self, preset_id: int) -> Optional[ScreenerPreset]:
        return self.db.query(ScreenerPreset).filter(
            ScreenerPreset.id == preset_id).first()

    def list(self) -> list[ScreenerPreset]:
        return self.db.query(ScreenerPreset).order_by(
            ScreenerPreset.created_at.desc(), ScreenerPreset.id.desc()).all()

    def list_enabled(self) -> list[ScreenerPreset]:
        return self.db.query(ScreenerPreset).filter(
            ScreenerPreset.schedule_enabled.is_(True)).all()

    def patch(self, preset_id: int, fields: dict[str, Any]) -> Optional[ScreenerPreset]:
        row = self.get(preset_id)
        if row is None:
            return None
        allowed = {"name", "market", "filters_json", "sort_by", "sort_dir",
                   "schedule_enabled", "notify_channels"}
        # Accept both "filters" and "filters_json" keys for convenience.
        if "filters" in fields:
            fields = {**fields, "filters_json": fields.pop("filters")}
        for k, v in fields.items():
            if k in allowed:
                setattr(row, k, v)
        self.db.commit(); self.db.refresh(row)
        return row

    def delete(self, preset_id: int) -> bool:
        row = self.get(preset_id)
        if row is None:
            return False
        self.db.delete(row); self.db.commit()
        return True

    def mark_run(self, preset_id: int, *, match_count: int, when: datetime) -> None:
        row = self.get(preset_id)
        if row is None:
            return
        row.last_match_count = match_count
        row.last_run_at = when
        self.db.commit()
```

- [ ] **Step 4: Run → 5 pass.**
- [ ] **Step 5: Commit** `feat(screener): ScreenerPresetRepository`. Log progress.

---

### Task A3: Preset Pydantic schemas

**Files:**
- Create: `app/backend/models/screener_preset_schemas.py`
- Test: `tests/screener/test_preset_schemas.py`

- [ ] **Step 1: Failing test**

```python
from __future__ import annotations
from app.backend.models.screener_preset_schemas import (
    PresetCreate, PresetPatch, PresetOut,
)


def test_create_defaults():
    c = PresetCreate(name="a", filters={"pe_max": 20})
    assert c.sort_by == "market_cap" and c.market is None


def test_patch_all_optional():
    p = PresetPatch()
    assert p.model_dump(exclude_unset=True) == {}


def test_out_from_attrs():
    class Row:
        id = 1; name = "a"; market = "US"; filters_json = {"pe_max": 20}
        sort_by = "market_cap"; sort_dir = "desc"; schedule_enabled = True
        notify_channels = ["email"]; last_run_at = None; last_match_count = 3
    o = PresetOut.model_validate(Row())
    assert o.id == 1 and o.filters == {"pe_max": 20} and o.last_match_count == 3
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement**

```python
"""Pydantic schemas for /screener/presets."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    market: Literal["US", "CN"] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    sort_by: str = "market_cap"
    sort_dir: Literal["asc", "desc"] = "desc"
    schedule_enabled: bool = False
    notify_channels: list[Literal["email", "webhook"]] | None = None


class PresetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    market: Literal["US", "CN"] | None = None
    filters: dict[str, Any] | None = None
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] | None = None
    schedule_enabled: bool | None = None
    notify_channels: list[Literal["email", "webhook"]] | None = None


class PresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    market: str | None
    filters: dict[str, Any] = Field(validation_alias="filters_json")
    sort_by: str
    sort_dir: str
    schedule_enabled: bool
    notify_channels: list[str] | None
    last_run_at: datetime | None
    last_match_count: int | None
```

Note: `PresetOut.filters` reads the ORM attribute `filters_json` via `validation_alias` + `from_attributes`. Verify in the test that `PresetOut.model_validate(Row())` maps `filters_json` → `filters` (Pydantic v2 honors `validation_alias` with `from_attributes`; if it doesn't in this version, fall back to a `@computed_field` or a `model_validator(mode="before")` that copies `filters_json`→`filters`, and log the choice in findings.md).

- [ ] **Step 4: Run → 3 pass.**
- [ ] **Step 5: Commit** `feat(screener): preset Pydantic schemas`. Log.

---

### Task A4: Preset CRUD routes

**Files:**
- Modify: `app/backend/routes/screener.py`
- Test: `tests/screener/test_preset_routes.py`

- [ ] **Step 1: Failing test** (TestClient + in-memory SQLite via `StaticPool`, same pattern as `tests/screener/test_routes.py`)

```python
from __future__ import annotations
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.backend.database import get_db
from app.backend.database.models import Base
from app.backend.repositories.screener_repository import ScreenerRepository, SnapshotRow
from app.backend.routes.screener import router as screener_router


@pytest.fixture()
def client():
    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    def override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI(); app.include_router(screener_router)
    app.dependency_overrides[get_db] = override
    # seed snapshot for the {id}/run test
    db = TS()
    ScreenerRepository(db).bulk_upsert([
        SnapshotRow(ticker="AAPL", market="US", snapshot_date=date(2026, 5, 28),
                    price=Decimal("210"), market_cap=Decimal("3.2e12"),
                    pe_ttm=Decimal("32"), sector="Technology", data_source="t"),
        SnapshotRow(ticker="JPM", market="US", snapshot_date=date(2026, 5, 28),
                    price=Decimal("180"), market_cap=Decimal("5e11"),
                    pe_ttm=Decimal("11"), sector="Financial Services", data_source="t"),
    ])
    db.close()
    return TestClient(app)


def test_crud_lifecycle(client):
    r = client.post("/screener/presets", json={"name": "cheap", "market": "US",
                    "filters": {"pe_max": 20}})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert client.get("/screener/presets").json()[0]["name"] == "cheap"
    r = client.patch(f"/screener/presets/{pid}", json={"schedule_enabled": True})
    assert r.json()["schedule_enabled"] is True
    # run → applies filters_json to the latest snapshot
    run = client.post(f"/screener/presets/{pid}/run").json()
    assert run["total_count"] == 1 and run["rows"][0]["ticker"] == "JPM"
    assert client.delete(f"/screener/presets/{pid}").status_code == 204
    assert client.get("/screener/presets").json() == []


def test_patch_404(client):
    assert client.patch("/screener/presets/999", json={"name": "x"}).status_code == 404
```

- [ ] **Step 2: Run → fails (routes missing).**

- [ ] **Step 3: Add routes to `app/backend/routes/screener.py`.** Imports at top:

```python
from fastapi import status
from app.backend.models.screener_preset_schemas import (
    PresetCreate, PresetPatch, PresetOut,
)
from app.backend.repositories.screener_preset_repository import ScreenerPresetRepository
```

Append:

```python
@router.get("/presets", response_model=list[PresetOut])
def list_presets(db: Session = Depends(get_db)) -> list[PresetOut]:
    return [PresetOut.model_validate(p) for p in ScreenerPresetRepository(db).list()]


@router.post("/presets", response_model=PresetOut, status_code=status.HTTP_201_CREATED)
def create_preset(body: PresetCreate, db: Session = Depends(get_db)) -> PresetOut:
    p = ScreenerPresetRepository(db).create(
        name=body.name, market=body.market, filters=body.filters,
        sort_by=body.sort_by, sort_dir=body.sort_dir,
        schedule_enabled=body.schedule_enabled, notify_channels=body.notify_channels,
    )
    return PresetOut.model_validate(p)


@router.patch("/presets/{preset_id}", response_model=PresetOut)
def patch_preset(preset_id: int, body: PresetPatch,
                 db: Session = Depends(get_db)) -> PresetOut:
    p = ScreenerPresetRepository(db).patch(
        preset_id, body.model_dump(exclude_unset=True))
    if p is None:
        raise HTTPException(404, f"No preset {preset_id}")
    return PresetOut.model_validate(p)


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(preset_id: int, db: Session = Depends(get_db)) -> Response:
    if not ScreenerPresetRepository(db).delete(preset_id):
        raise HTTPException(404, f"No preset {preset_id}")
    return Response(status_code=204)


@router.post("/presets/{preset_id}/run", response_model=ScreenerSnapshotResponse)
def run_preset(preset_id: int, db: Session = Depends(get_db)) -> ScreenerSnapshotResponse:
    repo = ScreenerPresetRepository(db)
    p = repo.get(preset_id)
    if p is None:
        raise HTTPException(404, f"No preset {preset_id}")
    screener = ScreenerRepository(db)
    market_list = [p.market] if p.market else None
    rows, total = screener.query(
        market=market_list, filters=p.filters_json or {},
        sort_by=p.sort_by, sort_dir=p.sort_dir, limit=200,
    )
    snap_date = rows[0].snapshot_date if rows else (
        screener.latest_snapshot_date() or date.today())
    last_updated = max((r.last_updated for r in rows if r.last_updated),
                       default=datetime.now(timezone.utc))
    return ScreenerSnapshotResponse(
        rows=[SnapshotRowOut.model_validate(r) for r in rows],
        total_count=total, snapshot_date=snap_date, last_updated=last_updated,
    )
```

`HTTPException` is from `fastapi` — add to the existing `from fastapi import ...` line if absent. `datetime`/`timezone` likely already imported (the file uses `datetime.now(timezone.utc)` after this session's fix); add if missing.

- [ ] **Step 4: Run → 2 pass.** Also run full screener suite green.
- [ ] **Step 5: Commit** `feat(screener): preset CRUD + run routes`. Log.

---

### Task A5: `screener.match` notification render + dispatch

**Files:**
- Modify: `app/backend/services/notifications/render.py` (add screener-match renderers)
- Modify: `app/backend/services/notifications/dispatcher.py` (route the new event)
- Test: `tests/notifications/test_screener_match_render.py`

- [ ] **Step 1: Failing test**

```python
from __future__ import annotations
from app.backend.services.notifications.render import (
    render_screener_match_html, render_screener_match_text,
)


def _payload():
    return {
        "preset_name": "cheap tech",
        "match_count": 2,
        "snapshot_date": "2026-05-28",
        "rows": [
            {"ticker": "AAPL", "price": "210", "pe_ttm": "32", "change_pct": "0.01"},
            {"ticker": "JPM", "price": "180", "pe_ttm": "11", "change_pct": "-0.02"},
        ],
    }


def test_html_contains_preset_and_tickers():
    h = render_screener_match_html(_payload())
    assert "cheap tech" in h and "AAPL" in h and "JPM" in h
    assert "<table" in h.lower()


def test_text_plain():
    t = render_screener_match_text(_payload())
    assert "cheap tech" in t and "AAPL" in t and "2" in t


def test_never_raises_on_sparse():
    # missing fields must render as — not crash
    render_screener_match_html({"preset_name": "x", "rows": [{"ticker": "Z"}]})
    render_screener_match_text({"preset_name": "x", "rows": [{"ticker": "Z"}]})
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Add renderers to `render.py`** (reuse the file's `_esc` helper; inline styles only, never raise):

```python
def render_screener_match_html(payload: dict) -> str:
    name = _esc(payload.get("preset_name"))
    count = _esc(payload.get("match_count", len(payload.get("rows") or [])))
    rows = payload.get("rows") or []
    trs = []
    for r in rows[:25]:
        trs.append(
            "<tr>"
            f"<td style='padding:4px 8px;font-family:monospace;font-weight:bold'>{_esc(r.get('ticker'))}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{_esc(r.get('price'))}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{_esc(r.get('pe_ttm'))}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{_esc(r.get('change_pct'))}</td>"
            "</tr>"
        )
    return (
        f"<div style='font-family:system-ui,sans-serif'>"
        f"<h2 style='margin:0 0 8px'>Screener match: {name}</h2>"
        f"<p style='color:#374151;margin:0 0 12px'>{count} ticker(s) matched "
        f"as of {_esc(payload.get('snapshot_date'))}.</p>"
        f"<table style='border-collapse:collapse;font-size:13px'>"
        f"<thead><tr style='background:#f3f4f6'>"
        f"<th style='padding:4px 8px;text-align:left'>Ticker</th>"
        f"<th style='padding:4px 8px;text-align:right'>Price</th>"
        f"<th style='padding:4px 8px;text-align:right'>P/E</th>"
        f"<th style='padding:4px 8px;text-align:right'>Chg</th>"
        f"</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
    )


def render_screener_match_text(payload: dict) -> str:
    name = payload.get("preset_name") or ""
    rows = payload.get("rows") or []
    count = payload.get("match_count", len(rows))
    lines = [f"Screener match: {name}", f"{count} ticker(s) matched", ""]
    for r in rows[:25]:
        lines.append(f"  {r.get('ticker','?'):8} price={r.get('price','—')} "
                     f"pe={r.get('pe_ttm','—')} chg={r.get('change_pct','—')}")
    return "\n".join(lines)
```

- [ ] **Step 4: Route in `dispatcher.py`** — in `_render_for_event`, add ABOVE the final fallback:

```python
        if event_type == "screener.match":
            return (
                render_screener_match_html(run),
                render_screener_match_text(run),
            )
```
And add `render_screener_match_html, render_screener_match_text` to the existing `from app.backend.services.notifications.render import (...)` import. Here `run` is the payload dict (the dispatcher already passes an arbitrary `run` object through to the renderer).

- [ ] **Step 5: Run → 3 pass.** Also run the existing notification tests to confirm pipeline/research events still render: `... -m pytest tests/notifications/ tests/test_notification_routes.py -q`.
- [ ] **Step 6: Commit** `feat(notify): screener.match render + dispatch routing`. Log.

---

### Task A6: Preset cron job

**Files:**
- Modify: `app/backend/services/scheduler_service.py`
- Test: `tests/screener/test_preset_scheduler.py`

- [ ] **Step 1: Failing test**

```python
from __future__ import annotations
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.backend.repositories.screener_repository import SnapshotRow


def test_constants():
    from app.backend.services.scheduler_service import (
        SCREENER_PRESET_CRON_EXPR, SCREENER_PRESET_JOB_ID)
    assert SCREENER_PRESET_CRON_EXPR == "5 22 * * *"
    assert SCREENER_PRESET_JOB_ID == "screener_presets"


def test_enabled_preset_runs_and_notifies():
    from app.backend.services import scheduler_service as ss
    enabled = MagicMock(id=1, name="p", market="US", filters_json={"pe_max": 20},
                        sort_by="market_cap", sort_dir="desc",
                        notify_channels=["email"])
    repo = MagicMock(); repo.list_enabled.return_value = [enabled]
    screener = MagicMock()
    screener.query.return_value = (
        [SnapshotRow(ticker="JPM", market="US", snapshot_date=date(2026, 5, 28),
                     pe_ttm=Decimal("11"))], 1)
    dispatcher = MagicMock()
    with patch.object(ss, "SessionLocal", return_value=MagicMock()), \
         patch.object(ss, "ScreenerPresetRepository", return_value=repo), \
         patch.object(ss, "ScreenerRepository", return_value=screener), \
         patch.object(ss, "NotificationDispatcher", return_value=dispatcher):
        ss._run_preset_job_body()
    repo.mark_run.assert_called_once()
    dispatcher.dispatch.assert_called_once()
    assert dispatcher.dispatch.call_args.kwargs.get("event_type") == "screener.match"


def test_zero_match_does_not_notify():
    from app.backend.services import scheduler_service as ss
    enabled = MagicMock(id=1, name="p", market="US", filters_json={},
                        sort_by="market_cap", sort_dir="desc",
                        notify_channels=["email"])
    repo = MagicMock(); repo.list_enabled.return_value = [enabled]
    screener = MagicMock(); screener.query.return_value = ([], 0)
    dispatcher = MagicMock()
    with patch.object(ss, "SessionLocal", return_value=MagicMock()), \
         patch.object(ss, "ScreenerPresetRepository", return_value=repo), \
         patch.object(ss, "ScreenerRepository", return_value=screener), \
         patch.object(ss, "NotificationDispatcher", return_value=dispatcher):
        ss._run_preset_job_body()
    repo.mark_run.assert_called_once()        # still records the run
    dispatcher.dispatch.assert_not_called()   # but no notification
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Add to `scheduler_service.py`.** Constants near the others:

```python
SCREENER_PRESET_CRON_EXPR = "5 22 * * *"   # 22:05 ET, after the 22:00 snapshot
SCREENER_PRESET_JOB_ID = "screener_presets"
```
Imports near the top (alongside the screener-snapshot imports added this session):

```python
from app.backend.repositories.screener_preset_repository import ScreenerPresetRepository
from app.backend.services.notifications.dispatcher import NotificationDispatcher
```
(If `NotificationDispatcher`'s constructor needs a session factory or args, mirror however the existing pipeline/research jobs build + call it — read `dispatcher.py` and the existing `_run_research_job_body`. If the dispatcher API differs from `dispatch(run=..., event_type=...)`, adapt the job body to the real signature and log the adaptation in findings.md.)

Module-level job body (next to `_run_snapshot_job_body`):

```python
def _run_preset_job_body() -> None:
    """Run every schedule-enabled screener preset against the latest snapshot;
    notify on non-empty matches. Per-preset failures log + continue."""
    from datetime import date as _date, datetime as _dt, timezone as _tz
    db = SessionLocal()
    try:
        presets = ScreenerPresetRepository(db).list_enabled()
        screener = ScreenerRepository(db)
        dispatcher = NotificationDispatcher(SessionLocal)
        for p in presets:
            try:
                market = [p.market] if p.market else None
                rows, total = screener.query(
                    market=market, filters=p.filters_json or {},
                    sort_by=p.sort_by, sort_dir=p.sort_dir, limit=200)
                ScreenerPresetRepository(db).mark_run(
                    p.id, match_count=total, when=_dt.now(_tz.utc))
                if total > 0 and (p.notify_channels or []):
                    payload = {
                        "preset_name": p.name,
                        "match_count": total,
                        "snapshot_date": (rows[0].snapshot_date.isoformat()
                                          if rows else _date.today().isoformat()),
                        "rows": [{"ticker": r.ticker,
                                  "price": str(r.price) if r.price is not None else None,
                                  "pe_ttm": str(r.pe_ttm) if r.pe_ttm is not None else None,
                                  "change_pct": str(r.change_pct) if r.change_pct is not None else None}
                                 for r in rows[:25]],
                    }
                    dispatcher.dispatch(run=payload, event_type="screener.match")
            except Exception as e:
                logger.exception("preset %s failed: %s", getattr(p, "id", "?"), e)
    finally:
        db.close()
```

Register the cron inside `SchedulerService.start()` next to the snapshot job (mirror the snapshot `add_job` block exactly, using `SCREENER_PRESET_CRON_EXPR`/`SCREENER_PRESET_JOB_ID` and `_run_preset_job_body`).

- [ ] **Step 4: Run → 3 pass.** Then the scheduler suite: `... -m pytest tests/test_scheduler_service.py tests/screener/ -q`. **If the lifecycle test asserts an `add_job` count, bump it by 1** (now 4: pipeline + research + snapshot + presets) — same fix as Wave B if not already done; do it here to keep green.
- [ ] **Step 5: Commit** `feat(screener): nightly preset cron at 22:05 ET + notify-on-match`. Log.

---

### Task A7: Frontend preset service + type

**Files:**
- Modify: `app/frontend/src/types/screener.ts` (add `ScreenerPreset`)
- Modify: `app/frontend/src/services/screener-service.ts` (preset CRUD)

- [ ] **Step 1: Add type**

```typescript
export interface ScreenerPreset {
  id: number;
  name: string;
  market: 'US' | 'CN' | null;
  filters: ChipValues;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  schedule_enabled: boolean;
  notify_channels: string[] | null;
  last_run_at: string | null;
  last_match_count: number | null;
}
```

- [ ] **Step 2: Add CRUD client** to `screener-service.ts`:

```typescript
export async function listPresets(): Promise<ScreenerPreset[]> {
  const r = await fetch(`${API_BASE}/screener/presets`);
  if (!r.ok) throw new Error(`listPresets ${r.status}`);
  return r.json();
}
export async function createPreset(body: {
  name: string; market: 'US' | 'CN' | null; filters: ChipValues;
  sort_by: string; sort_dir: 'asc' | 'desc';
  schedule_enabled?: boolean; notify_channels?: string[] | null;
}): Promise<ScreenerPreset> {
  const r = await fetch(`${API_BASE}/screener/presets`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`createPreset ${r.status}`);
  return r.json();
}
export async function patchPreset(id: number, patch: Partial<{
  name: string; schedule_enabled: boolean; notify_channels: string[] | null;
}>): Promise<ScreenerPreset> {
  const r = await fetch(`${API_BASE}/screener/presets/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`patchPreset ${r.status}`);
  return r.json();
}
export async function deletePreset(id: number): Promise<void> {
  const r = await fetch(`${API_BASE}/screener/presets/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`deletePreset ${r.status}`);
}
```
Add `ScreenerPreset` to the type import in `screener-service.ts`.

- [ ] **Step 3: tsc clean.** Commit `feat(screener): frontend preset service + type`. Log.

---

### Task A8: Save/load preset UI in the Screener tab

**Files:**
- Modify: `app/frontend/src/components/panels/screener/screener-tab.tsx`
- Create: `app/frontend/src/components/panels/screener/preset-bar.tsx`

Implement a compact `<PresetBar>` rendered just above the chip bar:
- A `<Select>` listing presets; choosing one calls `setMarket / setSortBy / setSortDir / setFilterValues` from the preset (load).
- A "Save preset" button → small popover with a name `<Input>` → `createPreset({ name, market, filters: filterValues, sort_by, sort_dir })` → refresh list, toast.
- A "Manage" affordance opening the Task A9 manager.

`screener-tab.tsx` already owns `market/sortBy/sortDir/filterValues` state — pass setters + current values to `<PresetBar>`. Follow the existing chip-bar styling. tsc clean. Commit `feat(screener): save/load preset bar`. Log.

(If a layout/UX detail is ambiguous, pick the compact option matching the chip bar and log it.)

---

### Task A9: Presets manager (list / toggle schedule / channels / delete)

**Files:**
- Create: `app/frontend/src/components/panels/screener/preset-manager.tsx`
- Modify: `preset-bar.tsx` (open the manager)

A dialog (shadcn `Dialog`) listing presets: name, match count, a schedule on/off `Switch` (→ `patchPreset(id,{schedule_enabled})`), channel checkboxes email/webhook (→ `patchPreset(id,{notify_channels})`), and a delete button (confirm → `deletePreset`). Reuse `Checkbox`/`Dialog`/`Button`. tsc clean. Commit `feat(screener): presets manager dialog`. Log.

---

### Task A10: i18n for presets

**Files:** Modify `app/frontend/src/i18n/locales/{en,zh}.json` — add a `screener.presets.*` block: `save`, `load`, `manage`, `name`, `schedule`, `channels`, `email`, `webhook`, `delete`, `deleteConfirm`, `saved`, `lastMatch`, `none`. Provide zh translations (e.g. save=保存预设, schedule=定时, lastMatch=上次命中). Use the Python json round-trip method (utf-8, `ensure_ascii=False`, indent=2) — do not hand-edit. Validate both files parse. Commit `feat(screener): i18n for presets (en+zh)`. Log.

---

### Task A11: Wave A verification

- [ ] `... -m pytest tests/ -q --tb=short` → green (pre-existing live-API failures only).
- [ ] `cd app/frontend ; node node_modules/typescript/bin/tsc --noEmit` → no NEW errors (the 2 pre-existing remain until B2).
- [ ] Append a Wave-A summary to `progress.md`. No separate commit needed if nothing changed; otherwise commit the progress note.

---

# WAVE B — test hardening

### Task B1: Fix scanner earnings_event assertion

**Files:** Modify `tests/test_scanner_service.py`.
- [ ] Run `... -m pytest tests/test_scanner_service.py::TestScannerServiceExecute::test_enabled_detectors_filters_run_scan_detectors -q` → see the `earnings_surprise` vs `earnings_event` diff.
- [ ] Confirm the canonical slug: `grep -n "earnings_event\|earnings_surprise" v2/scanner/detectors/__init__.py` — `earnings_event` is registered; `earnings_surprise` is a legacy alias. Update the test's expected detector-name list to use `earnings_event` (match the actual filtered output).
- [ ] Run → pass. Commit `test(scanner): expect earnings_event after detector merge`. Log.

### Task B2: Fix pre-existing frontend tsc errors

**Files:** `app/frontend/src/components/panels/scanner/agent-run-detail.tsx` (remove unused `Badge` import), `app/frontend/src/lib/utils.ts` (the unused `provider` param — remove it or prefix `_provider`; check call sites first with grep, adjust if needed).
- [ ] `cd app/frontend ; node node_modules/typescript/bin/tsc --noEmit` → **zero** errors now.
- [ ] Commit `fix(frontend): clear pre-existing unused-symbol tsc errors`. Log.

### Task B3: Expand coverage (verdict extraction, screener filters, delete)

**Files:** Create `tests/test_research_verdict.py`; extend `tests/test_screener_repository.py`.
- [ ] **Verdict extraction** — unit-test `_report_to_detail` from `app/backend/routes/research.py`. Build a fake `report_dict` whose `sections["executive_summary"].structured` has `{recommendation:"buy", confidence_score:71, overall_view:"x"}` → assert `detail.verdict.recommendation=="buy"` and `confidence_score==71`. Then: invalid recommendation (`"??"`) → `verdict is None`; missing executive_summary → `verdict is None`. (Construct a minimal `report_dict` with a tiny object exposing `.structured`, `.name`, `.markdown`, `.skipped`, `.persona_used`, `.skip_reason`, plus `backtest=None`, and a stub `row` with the needed attrs — mirror the shape `_report_to_detail` reads. If the row shape is fiddly, log the construction choice in findings.md.)
- [ ] **Screener filters** — add to `tests/test_screener_repository.py`: a `perf_1y_min` range filter selects the right rows; `recent_earnings_after` date filter selects rows on/after a date; the `delete`... (ScreenerRepository has no delete — instead cover `cleanup_old_snapshots` edge: keep_days boundary). Add a `recent_earnings_after`/`before` test using `recent_earnings_date` rows.
- [ ] **Report delete path** — extend `tests/test_screener_repository.py`? No — report delete lives in `ResearchReportRepository`. Add `tests/test_research_repository_delete.py`: create a report via `create_analyze`, `delete(id)` → True + `get_by_id` None; `delete(999)` → False. (Use the in-memory-SQLite + `ResearchReportRepository` pattern from `tests/test_research_repository.py`.)
- [ ] Run the new tests → green. Commit `test: verdict extraction + screener filters + report delete`. Log.

### Task B4: Full-suite checkpoint

- [ ] `... -m pytest tests/ v2/ -q --tb=line 2>&1 | tail -30`. Record pass/fail counts. For any FAIL that is genuinely live-API (network/key-dependent) and pre-existing, append a one-line entry to `findings.md` (`PRE-EXISTING LIVE FAIL: <nodeid> — <why>`). Do NOT chase live-API failures.
- [ ] If any failure was introduced by Waves A/B, fix it. End on green-modulo-live.
- [ ] Commit `test: wave-B green checkpoint` (if files changed) + progress note.

---

# WAVE C — Scanner detectors + A/B eval

> Each detector follows the `bollinger_squeeze.py` template: `detect(self, ticker, end_date, fd, *, ctx=None) -> EventTrigger|None`; `prices = fd.get_prices(ticker, start, end_date)`; sort by `p.time[:10]`; `close_of(p)` for adjusted close; `None` on insufficient data; `EventTrigger(triggered=False, ...)` on ran-but-didn't-fire; `triggered=True` with `severity_z`, `direction`, `reason`, `components`, `asof_date` on fire. Register the class in `v2/scanner/detectors/__init__.py` `ALL_DETECTORS` + add a `DETECTOR_METADATA` entry. **Std-floor invariant**: any z-score divisor uses a real floor (e.g. `max(mean*0.10, 1e-6_meaningful)`), with a categorical fallback below it; mark coefficient-only std uses with the `# noqa: std-floor` comment like the template. After each task, the controller runs `scanner-invariant-reviewer`.

### Task C1: 52-week-high breakout detector

**Files:** Create `v2/scanner/detectors/high_breakout.py`; Modify `v2/scanner/detectors/__init__.py`; Modify `v2/scanner/README.md`; Test `v2/scanner/test_detector_high_breakout.py`.

- [ ] **Test** (crafted series): a ~260-bar series rising to a fresh max on the last bar → `triggered True`, `direction "bullish"`; a flat/mid-range series → `triggered False`; `[]`/short series → `None`; degenerate (all same price) → no raise.
- [ ] **Implement** `HighBreakoutDetector(name="high_breakout")`: pull ~`lookback_days≈400` bars; need ≥ `window+2` (window=252). Fire on **first-day** breakout: `close_today >= max(prior `window` closes)` AND `close_yesterday < max(prior window ending yesterday)` (first-day gate, mirror the squeeze). `severity_z` = how far above the prior max in units of trailing daily-return std **with a real floor**: `ret_std = max(returns.std(ddof=1), 0.005)` then `severity_z = (close_today/prior_max - 1)/ret_std`, clamp to e.g. [0, 8]. `direction="bullish"`. Symmetric 52w-low variant is OUT (keep one direction; log the decision). `components`: `prior_max`, `close_today`, `ret_std`.
- [ ] Register + metadata (`{"label":"52w High Breakout","default_mult":1.0,...}`) + README std-floor note.
- [ ] Run test → pass. Commit `feat(scanner): 52-week-high breakout detector`. Log. **Controller: run scanner-invariant-reviewer.**

### Task C2: Gap up/down detector

**Files:** Create `v2/scanner/detectors/gap.py`; Modify `__init__.py`, `README.md`; Test `v2/scanner/test_detector_gap.py`.

- [ ] **Test:** today's open ≫ prior close (e.g. +8%) → `triggered True`, `direction "bullish"`; big gap down → `bearish`; small gap → `False`; missing open or <2 bars → `None`; degenerate → no raise.
- [ ] **Implement** `GapDetector(name="gap")`: needs ≥ ~60 bars to compute the gap-size distribution. `gap = open_today/close_yesterday - 1`. z-score `gap` against the trailing-N (≈60) daily gaps with a **real std floor** (`max(gaps.std(ddof=1), 0.003)`); fire when `abs(z) >= threshold` (e.g. 3.0). `direction` by sign. Requires `p.open` — if Price lacks open for the bars, return `None` (no-data) cleanly. `components`: `gap`, `gap_z`, `open_today`, `close_yesterday`.
- [ ] Register + metadata + README. Test → pass. Commit `feat(scanner): gap up/down detector`. Log. **Controller: invariant review.**

### Task C3: Golden/death cross detector

**Files:** Create `v2/scanner/detectors/ma_cross.py`; Modify `__init__.py`, `README.md`; Test `v2/scanner/test_detector_ma_cross.py`.

- [ ] **Test:** series where SMA50 crosses ABOVE SMA200 on the last bar → `triggered True`, `direction "bullish"` (golden); cross below → `bearish` (death); no cross → `False`; <202 bars → `None`; degenerate → no raise.
- [ ] **Implement** `MaCrossDetector(name="ma_cross")`: need ≥ `slow+2` (slow=200) bars. Compute SMA50 + SMA200 for today and yesterday. Golden = `sma50_yest <= sma200_yest and sma50_today > sma200_today`; death = the mirror. `severity_z` fixed (e.g. 2.0 — a cross is a binary regime event, not a magnitude; mark any std use `# noqa: std-floor` since none divides). `direction` bullish/bearish. `components`: the 4 SMA values.
- [ ] Register + metadata + README. Test → pass. Commit `feat(scanner): golden/death cross detector`. Log. **Controller: invariant review.**

### Task C4: RSI divergence detector

**Files:** Create `v2/scanner/detectors/rsi_divergence.py`; Modify `__init__.py`, `README.md`; Test `v2/scanner/test_detector_rsi_divergence.py`.

- [ ] **Test:** price makes a higher high over the window while RSI(14) makes a lower high → bearish divergence `triggered True`, `direction "bearish"`; price lower-low + RSI higher-low → bullish; aligned price/RSI → `False`; <~40 bars → `None`; degenerate (flat) → no raise.
- [ ] **Implement** `RsiDivergenceDetector(name="rsi_divergence")`: compute Wilder RSI(14) over the series (reuse the math style already in the repo — e.g. `src/research` RSI or inline Wilder). Over a lookback window (≈40 bars) find the two most-recent swing highs (and lows). Bearish: price hi2 > hi1 but RSI@hi2 < RSI@hi1. Bullish: price lo2 < lo1 but RSI@lo2 > RSI@lo1. `severity_z` = magnitude of the RSI gap scaled (fixed coefficient ok; no z-divisor → `# noqa: std-floor`). `components`: the price + RSI extrema. Keep swing detection simple (local max/min over small sub-windows); if swing-finding is ambiguous, use the simplest "compare last two N/2-bar halves' max" approach and log it.
- [ ] Register + metadata + README. Test → pass. Commit `feat(scanner): RSI divergence detector`. Log. **Controller: invariant review.**

### Task C5: A/B eval harness

**Files:** Create `v2/scanner/eval/__init__.py`, `v2/scanner/eval/detector_ab.py`; Test `v2/scanner/test_eval_ab.py`.

- [ ] **Test (synthetic):** feed a tiny in-memory price set + a fake detector that fires on known bars; assert `evaluate_detector(...)` returns a dict with `n_fired`, `mean_fwd_return`, `baseline_mean`, `t_stat`, `horizon` and that `n_fired` matches the crafted fires. No network.
- [ ] **Implement** `evaluate_detector(detector, tickers, prices_by_ticker, *, horizon=20, asof_dates) -> dict`: for each (ticker, date) the detector fires on, compute forward `horizon`-bar return; build a random baseline by sampling the same count of (ticker, date) points uniformly; return `{n_fired, mean_fwd_return, baseline_mean, diff, t_stat, horizon}` (Welch t-stat between fired vs baseline forward-return arrays; guard n<2 → t_stat=0.0). Pure-Python/numpy; data passed IN (no live fetch). Add a `__main__` CLI guard that, given a universe + DataClient, wires real prices — but the unit test only exercises the pure function with injected data.
- [ ] Run test → pass. Commit `feat(scanner): detector A/B eval harness vs random baseline`. Log.

### Task C6: Wave C verification

- [ ] `... -m pytest v2/ tests/ -q --tb=short` → green. Confirm `ALL_DETECTORS` now includes the 4 new detectors and existing scanner tests still pass (the detector-count/registry tests may need the new names — update expected lists if they enumerate detectors; log).
- [ ] Append Wave-C summary to `progress.md`.

---

# WAVE D — Screener Phase 3 polish (frontend, tsc-only, AM visual review)

> Frontend only. Verify with `tsc --noEmit`. No backend. Visual correctness is reviewed by the user in the morning — keep changes additive + behind the existing Screener tab.

### Task D1: Sector chip dropdown grouped by market

**Files:** Modify `app/frontend/src/components/panels/screener/chips/multi-select-chip.tsx`.
- [ ] When `meta.slug === "sector"` and the options list is long, add a search `<Input>` at the top of the popover that filters options client-side; group/header by market when both `options_us`/`options_cn` exist (the chip already picks the market-appropriate list — just add the search filter + a small header). tsc clean. Commit `feat(screener): searchable sector chip`. Log.

### Task D2: Column-group tabs (Overview / Valuation / Performance)

**Files:** Modify `app/frontend/src/components/panels/screener/snapshot-table.tsx`; Modify `screener-tab.tsx`.
- [ ] Add a small tab strip above the table with 3 groups; each selects which columns render over the SAME rows:
  - Overview: ticker, market, price, chg%, vol, mcap, rating, analyze.
  - Valuation: ticker, price, pe_ttm, pe_forward, pb, ps, peg, div%, analyze.
  - Performance: ticker, perf_1d, perf_5d, perf_1m, perf_3m, perf_ytd, perf_1y, analyze.
- [ ] Drive via a `columnGroup` state in `screener-tab.tsx` passed to `SnapshotTable`; render the column subset per group. Keep the Analyze button column in all groups. tsc clean. Commit `feat(screener): column-group tabs over the table`. Log.

### Task D3: Bulk add-to-watchlist

**Files:** Modify `snapshot-table.tsx` + `screener-tab.tsx`. Read `app/frontend/src/services/watchlist-service.ts` for the add API first.
- [ ] Add row checkboxes + a header "Add N to watchlist" action that, given a target watchlist (use the first existing watchlist, or prompt-select if multiple — pick first + log if ambiguous), calls the watchlist service to add the selected tickers. Toast the result. tsc clean. Commit `feat(screener): bulk add selected to watchlist`. Log.

### Task D4: Final verification + wrap-up

- [ ] `... -m pytest tests/ v2/ -q` (green-modulo-live) and `cd app/frontend ; node node_modules/typescript/bin/tsc --noEmit` (zero errors).
- [ ] Append an overnight-batch summary to `progress.md`: which waves/tasks completed, which were skipped, and a pointer to `findings.md` for any logged ambiguity decisions + pre-existing live failures.
- [ ] Commit `docs: overnight batch wrap-up`.

---

## Self-review

**Spec coverage:** Wave A (presets table A1, repo A2, schemas A3, routes A4, notify A5, cron A6, FE A7-A10, verify A11) ✓; Wave B (B1 earnings_event, B2 tsc, B3 coverage, B4 checkpoint) ✓; Wave C (C1-C4 detectors — Bollinger/volume dropped as already-existing, C5 eval, C6 verify) ✓; Wave D (D1 sector, D2 column tabs, D3 bulk watchlist, D4 wrap) ✓. CN-unblock + intraday correctly absent (out of scope).

**Placeholder scan:** Backend tasks (A1-A6, B1-B3, C1-C5) ship complete code + tests. Frontend tasks (A8-A10, D1-D3) give exact files + interfaces + the established pattern to follow rather than full JSX — acceptable because they are tsc-gated, follow the existing Screener components, and the autonomy rule (sensible-default + log) covers UI micro-decisions; full JSX would be guesswork against unread component internals. The executor reads the referenced components before editing.

**Type consistency:** `ScreenerPresetRepository` methods (`create/get/list/list_enabled/patch/delete/mark_run`) are used identically in A4 routes + A6 cron. `filters_json` (ORM) ↔ `filters` (API) mapping is defined in A1/A3 and consumed in A4/A6/A7. `event_type="screener.match"` matches between A5 (render/dispatch) and A6 (cron dispatch call). Detector `name` slugs (`high_breakout`, `gap`, `ma_cross`, `rsi_divergence`) are registered in C1-C4 and enumerated in C6. `_run_preset_job_body` / `SCREENER_PRESET_JOB_ID` consistent A6.
