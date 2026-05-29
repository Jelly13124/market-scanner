# Overnight batch — Screener Phase 2/3 + test hardening + Scanner detectors

## Context

This is an **unattended overnight run**. The user approved a sequenced batch
of four waves, executed A → B → C → D, "do as much as fits the night." The
agent works the queue top-down; whatever finishes is shippable on its own.

The batch follows a long session that delivered: Screener Phase 1 (snapshot
table + faceted UI), the buy/sell/hold **verdict** (5-level + confidence,
surfaced in report banner + Analyze card + API), and a **Reports tab**
(full-area list, batch-delete, pop-out viewer). All committed + pushed except
the Reports tab (committed at batch start — see Wave 0).

### Autonomy rules (load-bearing for unattended execution)

1. **Never block on the user.** On any ambiguous decision, pick the sensible
   industry-default, proceed, and record the decision in `findings.md` (a
   one-line entry: what was ambiguous, what was chosen, why). The user reviews
   these in the morning.
2. **Backend-first, test-verified.** Every backend task ships mock-based tests
   and must leave the suite green before moving on. Frontend tasks must pass
   `tsc --noEmit` with zero new errors.
3. **No destructive actions on user data.** Do not delete reports, watchlists,
   scanner configs, or DB rows the agent didn't create. Migrations are
   additive only.
4. **Commit hygiene** (enforced by the git-guard hook): commit per task; NO
   `Co-Authored-By:` trailers; never `--no-verify`. Conventional-commit
   messages.
5. **Environment** (per CLAUDE.md): Python = `C:\Users\Jerry\anaconda3\python.exe`;
   run uvicorn from repo root, NO `--reload`; tests via
   `C:\Users\Jerry\anaconda3\python.exe -m pytest`; frontend `tsc` via
   `node node_modules/typescript/bin/tsc` (npm is not on the non-interactive PATH).
6. **Progress logging** (per CLAUDE.md): after each task, update `progress.md`.
7. **External-API resilience.** yfinance/akshare/mootdx calls in *tests* are
   always mocked. The agent does not depend on live data to verify code.

---

## Wave 0 — clean baseline (prerequisite, ~1 task)

Commit the already-verified Reports-tab work (currently uncommitted: new
`reports/reports-panel.tsx` + `left/reports-action.tsx`; deleted
`report-list.tsx` + `reports-section.tsx`; modified tab-service/tabs-context/
left-sidebar/i18n). One commit, then the tree is clean for the batch.

---

## Wave A — Screener Phase 2: presets + cron auto-run + notify-on-match

The Phase 1 spec explicitly deferred these. Goal: save a filter as a named
preset; a daily cron runs each enabled preset against the latest snapshot;
matches are pushed via the existing notification channels.

### Data model

New table `screener_presets`:

```python
class ScreenerPreset(Base):
    __tablename__ = "screener_presets"
    id            = Column(BigInteger().with_variant(Integer(), "sqlite"),
                           primary_key=True, autoincrement=True)
    name          = Column(String(120), nullable=False)
    market        = Column(String(8))            # 'US' | 'CN' | None(all)
    filters_json  = Column(JSON, nullable=False) # the ChipValues dict
    sort_by       = Column(String(32), default="market_cap")
    sort_dir      = Column(String(4),  default="desc")
    schedule_enabled = Column(Boolean, default=False)
    notify_channels  = Column(JSON)              # ["email","webhook"] subset
    last_run_at      = Column(DateTime(timezone=True))
    last_match_count = Column(Integer)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
```

Alembic migration `<sha>_add_screener_presets.py`, `down_revision` = current
head (`d4e8a2c1b9f6`). Additive only.

### Backend

- `app/backend/repositories/screener_preset_repository.py` — CRUD + `list`,
  `list_enabled`, `mark_run(id, count, when)`.
- `app/backend/models/screener_preset_schemas.py` — Pydantic create/patch/out.
- `app/backend/routes/screener.py` — add preset CRUD under `/screener/presets`
  (GET list, POST create, PATCH {id}, DELETE {id}, POST {id}/run → runs the
  preset's filters through `ScreenerRepository.query` now, returns matches).
- `scheduler_service.py` — new cron `SCREENER_PRESET_CRON_EXPR = "5 22 * * *"`
  (22:05 ET, 5 min after the snapshot cron at 22:00). Job body: for each
  enabled preset, run its filters via `ScreenerRepository.query` against the
  latest snapshot, `mark_run`, and if `notify_channels` non-empty + matches > 0,
  dispatch via the existing notification dispatcher (a new `screener.match`
  event_type + render path mirroring the research/pipeline render).
- Notifications: extend `services/notifications/render.py` with a
  `screener.match` body (preset name, match count, top-N tickers table) and
  `dispatcher.py` event-type routing. Reuse the existing subscription model.

### Frontend

- `screener-service.ts` — preset CRUD client.
- `types/screener.ts` — `ScreenerPreset` type.
- Screener tab: a "Save preset" button (captures current `filterValues` +
  market + sort), a preset dropdown to load one, and a small "Presets" manager
  (list, toggle schedule, pick channels, delete). Keep it compact — a popover
  or a thin bar above the chip row.

### Tests
`tests/screener/test_preset_repository.py`, `test_preset_routes.py`,
`test_preset_scheduler.py` (mock builder/dispatcher; assert enabled presets run
+ notify on matches, disabled don't, 0-match doesn't notify).

---

## Wave B — test hardening + clean baseline

- Fix the 3 known pre-existing failures:
  - `tests/test_scanner_service.py::...filters_run_scan_detectors` — asserts the
    old `earnings_surprise` slug; update to `earnings_event` (the rename is
    intentional per memory). Confirm against current detector registry.
  - Frontend `tsc`: `agent-run-detail.tsx` unused `Badge` import;
    `lib/utils.ts` unused `provider` param. Remove/underscore them.
- Expand coverage where this session added code with thin tests: verdict
  extraction in `_report_to_detail` (a report dict with exec_summary structured
  → verdict populated; missing/invalid → None); `ScreenerRepository` date-range
  + perf filters; `delete` repo path (create→delete→gone).
- End state: `pytest tests/ -q` green except genuinely-live-API tests (which
  are pre-existing skips/failures unrelated to our code — log which in
  findings.md, don't chase).

---

## Wave C — Scanner detectors + A/B eval harness

Modifying `v2/scanner/` IS the point of this wave (the Phase-1 "don't touch
scanner" constraint is lifted here). Each detector is a self-contained unit
obeying the 4 invariants; the `scanner-invariant-reviewer` subagent reviews
each before it's accepted.

### New detectors (`v2/scanner/detectors/`)
Implement 4–6, each with a test in the existing detector-test style:
- **52-week-high breakout** — close within X% of / breaking the 252-day high.
- **Volume dry-up → spike** — N-day declining volume then a >Kσ volume day
  (real std floor, per invariant #1).
- **Gap up/down** — open vs prior close beyond a threshold.
- **Golden/death cross** — SMA50 crossing SMA200.
- **RSI divergence** — price higher high while RSI lower high (reuse RSI math).
- **Bollinger squeeze** — band width at an N-day low (compression → breakout).

Each returns `None` for no-data (exclude) vs `EventTrigger(triggered=False)`
for ran-but-didn't-fire (invariant #3); signals never raise (invariant #2);
per-worker DataClient respected (invariant #4). Register in the detector
registry; document the std floor in `v2/scanner/README.md`.

### A/B eval harness (`v2/scanner/eval/`)
A script that, for a universe + lookback, computes each detector's forward
N-day return distribution on fired vs a random-sample baseline, and prints a
small table (n_fired, mean fwd return, vs random mean, simple t-stat). This is
the project's stated evaluation method (A/B vs random baseline, NOT
directional alpha). Mock data path for tests; live run is opt-in.

### Tests
`v2/scanner/test_detectors_new.py` (or extend the existing detector test file)
— per detector: fires on a crafted series, returns None on empty, doesn't raise
on degenerate input. Eval harness: a tiny synthetic-data unit test.

---

## Wave D — Screener Phase 3 polish (frontend, visual review AM)

Lowest priority; tsc-verified; user eyeballs visuals in the morning.
- **Sector chip dropdown** grouped by market (GICS for US) — already has option
  data in column_metadata; make the multi-select chip nicer (search box if long).
- **Column-group tabs** over the table: Overview / Valuation / Performance —
  same row set, different visible columns (TradingView-style).
- **Bulk add-to-watchlist** — row checkboxes + "Add N to watchlist" using the
  existing watchlist service.
- Skip: stock logos, per-row mini-charts (low value / high effort / flaky).

### Tests
Frontend only; rely on `tsc --noEmit` + the morning visual review. No new
backend.

---

## Verification (per wave)

```
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/ v2/ -q --tb=short
cd app/frontend ; node node_modules/typescript/bin/tsc --noEmit
```
Each wave ends green before the next starts. `progress.md` updated per task;
ambiguous-decision log in `findings.md`.

## Out of scope (tonight)

- CN data unblock (flaky overseas APIs — unsafe unattended; separate spec).
- Phase 10 Wave 2 intraday fetch.
- Lab/strategy ↔ Screener integration.
- Stock logos, per-row mini-charts.
- Any live-API-dependent verification (all tests mocked).

## Risks

1. **Frontend visual tasks can't self-verify** — mitigated by doing them last
   (Wave D), tsc-gating, and leaving them for the morning review.
2. **Notification dispatch** reuses an existing path that may assume
   pipeline/research event shapes — the `screener.match` render must be additive
   and not break existing events (test the existing events still render).
3. **Scanner detector std floors** — the #1 invariant; the reviewer subagent
   must gate each. A wrong floor silently corrupts ranking.
4. **Scope overrun** — expected; the A→B→C→D order ensures the most
   valuable/safe work lands first. Unfinished waves are logged for tomorrow.
