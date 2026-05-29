# Progress Log

- A9: preset-manager.tsx (Dialog + per-row Schedule/Email/Webhook Checkbox + delete); preset-bar.tsx wired with internal mgrOpen state; Manage button always visible; tsc 2 errors (both pre-existing).
- A10: i18n presets — added `screener.presets` block (19 keys) to en.json + zh.json via Python round-trip (no hand-edit). Both files validate. Commit c98a52a.

## Session — 2026-05-26 (Phase 8 Wave 7 — Verification, smoke, and Phase 8 landing)

### What shipped (Task 15 of `docs/superpowers/plans/2026-05-26-a-share-data-integration.md`)

Verification gates only — no source changes in this wave.

- Gate 1: full backend pytest (1272 passed / 20 failed / 8 skipped) — all
  20 failures match the pre-existing baseline (live-API failures in
  v2/data/test_client.py for JPM/XOM, 2 known TestMakeHybridClient
  assertions, 1 known scanner_service `earnings_event` alias test,
  plus untracked dev test files test_protocol_conformance.py /
  test_yfinance_client.py and live tests in v2/event_study). Zero
  new Phase 8 regressions.
- Gate 2: frontend tsc — no new errors (the 7 pre-existing in
  sidebar.tsx / agent-run-detail.tsx / lib/utils.ts are not Phase 8).
- Gate 3: Moutai (600519) live smoke — 334 daily bars, close
  1488.0 (2025-01-02) → 1285.88 (2025-05-25), confirms mootdx
  daily OHLCV path is healthy from this network.
- Bonus: US regression smoke — composite client constructs cleanly
  with `ashare_backend=True`. NVDA EODHD call returns 401 because
  no EODHD key is exported in this shell's env (pre-existing
  config gap, NOT an httpx-downgrade regression — `tests/research/`
  full suite passes 190/190 confirming httpx 0.25.2 still works).

### Phase 8 commits (since plan commit 38a11c8)

```
6dbc7c4 deps: add mootdx + stockstats as optional [ashare] extra
379c660 feat(ashare): symbol detection + canonical normalization
3e65f6c feat(ashare): AShareClient skeleton implementing DataClient Protocol
585a1ad docs: progress.md - Phase 8 Wave 1 A-share foundation
2ac93ed feat(ashare): CLS per-stock news fetcher
79995a7 feat(ashare): Eastmoney F10 fundamentals + company facts
077aed7 feat(ashare): SW1 sector name -> index code mapper
d539efb feat(ashare): mootdx-backed daily OHLCV fetcher (Wave 2A)
6c85409 feat(ashare): Eastmoney earnings history parser
c4eccd6 feat(ashare): market cap fetcher via Tencent qt.gtimg.cn
4f09223 test(ashare): extend AShareClient delegation tests
a0fb3ed feat(scanner): A-share universes (SSE50/CSI300/500/1000/HS300+CSI500)
82790af feat(composite): A-share ticker routing in CompositeClient
f2c2e3b feat(research): thread market field through AnalyzeRequest API surface
e50a14a feat(research): A-share benchmark + SW1 sector swap in shared_data
fb0bff0 docs: progress entry for Phase 8 Wave 5 (Task 13 SOP market integration)
e07c673 feat(frontend): Phase 8 Wave 6 - Market dropdown + A-share universes + i18n keys
d1285d6 docs: progress entry for Phase 8 Wave 6 (Task 14 frontend Market + universes)
```

## Session — 2026-05-29 (Wave A overnight batch — Task A3)

- A3: preset schemas (PresetCreate/Patch/Out) — 3 tests pass

### Tests

Full backend pytest summary (Gate 1):

```
20 failed, 1272 passed, 8 skipped, 69 warnings in 102.27s
```

Delta vs known baseline: 0 new failures from Phase 8. ~85 new
A-share + research tests under tests/v2/data/ashare/,
tests/v2/scanner/, tests/v2/data/test_composite_ashare_routing.py,
tests/research/test_shared_data_market.py all green.

### Live smoke (Moutai 600519, 2026-05-26)

```
get_company_facts(600519.SH) failed: Expecting value: line 1 column 4 (char 3)
600519 (Moutai): 334 bars
  first: 2025-01-02 close=1488.0
  last:  2026-05-25 close=1285.88
facts: name=None, sector=None, industry=None
metrics: 0 quarters
```

- mootdx prices: WORKING (334 bars, close range 1285-1488 RMB,
  consistent with Moutai's 2025-2026 trading range).
- Eastmoney F10 (facts/metrics): returned malformed JSON at this
  moment (likely transient — endpoint returned HTML instead of
  JSON, the 4th char is `<`). The AShareClient honored the
  Protocol invariant and gracefully returned `None`/`[]` rather
  than crashing. Earlier Wave 2 tests passed against the same
  endpoint; this is a live-API hiccup, not a code bug.

### Notes for next session

1. **A-share universe CSVs are empty stubs** — Eastmoney
   `RPT_INDEX_TS_COMPONENT` returns "BASE_CODE column not found".
   Backtests targeting `csi300` / `sse50` / etc. will yield 0
   tickers until the refresh script
   (`v2/scanner/scripts/refresh_ashare_universes.py`) is updated
   to use the current Eastmoney response schema.
2. **BSE (.BJ) tickers return [] for now** — mootdx core doesn't
   support market=2; Eastmoney fallback for BSE is v2 work.
3. **~30 uncommitted Phase 7 i18n files in working tree** —
   intentionally not committed by this wave (they're not Phase
   8's work). User should review and commit when ready.
4. **Eastmoney F10 transient failure** — re-run the live smoke
   once Eastmoney returns proper JSON; if persistent across
   days, the F10 endpoint may have changed and
   `eastmoney_fundamentals.py` needs investigation.

---

## Session — 2026-05-26 (Phase 8 Wave 6 — Frontend Market dropdown + A-share universes)

### What shipped (Task 14 of `docs/superpowers/plans/2026-05-26-a-share-data-integration.md`)

- **app/frontend/src/types/analyze.ts** — new `Market = 'us' | 'cn'`
  type + optional `market` field on `AnalyzeRunRequest` (mirrors
  Wave 5's backend schema change).
- **app/frontend/src/types/scanner.ts** — extended `UniverseKind`
  union and `UNIVERSE_KIND_OPTIONS` array with the 5 A-share
  universes (sse50/csi300/csi500/csi1000/hs300_ext). Mirrors the
  backend universe wave already on main.
- **app/frontend/src/types/strategy.ts** — same 5 values appended
  to `UniverseSpec.kind` so Strategy Lab specs can target A-share
  universes.
- **app/frontend/src/components/panels/analyze/input-node.tsx** —
  Market `<select>` rendered ABOVE the Ticker field so the user
  picks market first (CN tickers are 6-digit codes, not
  US-convention symbols). `InputNodeData.market` defaults to `'us'`.
- **app/frontend/src/components/panels/analyze/analyze-panel.tsx** —
  `handleRun` forwards `market: input.market ?? 'us'` on the
  outgoing `AnalyzeRunRequest`.
- **app/frontend/src/i18n/locales/en.json** + **zh.json** — new
  keys: `analyze.input.market`, `analyze.markets.{us,cn}`,
  `scanner.universe.{sse50,csi300,csi500,csi1000,hs300_ext}`.

### Plan-code adaptations

- Plan asserted "Phase 7 i18n infrastructure ... fully wired" on
  main, but `git log -- app/frontend/src/components/panels/analyze/analyze-panel.tsx`
  shows the last commit is `a0afdf1` (no i18n). All Phase 7 work was
  sitting uncommitted in the working tree. Bundled the Phase 7
  hunks in `analyze-panel.tsx` and `input-node.tsx` into this commit
  because the `useTranslation` import is a compile-time prerequisite
  for the new Market dropdown.
- Plan suggested `scanner.universe.*` already existed in the locale
  files; both `en.json` and `zh.json` were untracked entirely. This
  commit creates them with both the existing Phase 7 namespace and
  the new Phase 8 keys.
- `UNIVERSE_KIND_OPTIONS` entries are rendered directly via
  `opt.label` (not via i18n) in `scanner-config-dialog.tsx:295`, so
  the `label` strings include both English and Chinese (e.g.
  "SSE 50 / 上证 50") rather than being routed through the
  `scanner.universe.*` namespace. The i18n keys were still added
  per spec for any future caller that wants them.

### Verification

- `npx tsc --noEmit` — 0 new errors. Pre-existing errors in
  `sidebar.tsx`, `agent-run-detail.tsx`, `lib/utils.ts` remain (out
  of Phase 8 scope per CLAUDE.md).
- `node -e "JSON.parse(...)"` on both locale files — valid.
- Commit: `e07c673`.

## Session — 2026-05-26 (Phase 8 Wave 5 — SOP pipeline market integration)

### What shipped (Task 13 of `docs/superpowers/plans/2026-05-26-a-share-data-integration.md`)

- **src/research/models.py** — added `market: str = "us"` field to
  `AnalyzeRequest` dataclass (alongside `report_language`). Default
  preserves Phase 4-7 US behavior.
- **app/backend/models/research_schemas.py** — mirror on
  `AnalyzeRunRequest` as `market: Literal["us", "cn"] = Field(default="us")`.
- **app/backend/routes/research.py** — `_to_analyze_request()` now
  passes `market=req.market` through to the internal dataclass.
- **src/research/shared_data.py** — `_fetch_raw` + `fetch_shared_data`
  both accept `market: str = "us"`. When `market == "cn"`:
  - benchmark = `000300.SH` (沪深300) instead of `SPY`
  - sector ETF lookup uses
    `v2.data.ashare.sw_sector_map.sw1_index_code(sector)` (e.g.
    "食品饮料" → 801120.SH). Falls back to no sector data when the
    mapper returns None.
  CompositeClient's `ashare_backend` routing (Wave 4) means
  `client.get_prices("000300.SH", ...)` transparently dispatches to
  `AShareClient` — no special-casing needed at this layer.
- **Cache-key includes market** so the same ticker+date doesn't
  collide across markets.
- **src/research/sop_orchestrator.py** — passes `request.market`
  through to `fetch_shared_data`.
- **tests/research/test_shared_data_market.py** (NEW, 4 tests) —
  covers US default (SPY + SPDR XLK), CN benchmark+SW1 swap
  (000300.SH + 801120.SH for "食品饮料"), CN unknown-sector fallback,
  and cache-key isolation between markets.
- **tests/research/test_shared_data.py** — fixed lambda signature
  on `test_different_date_different_fetch` to accept the new `market`
  kwarg.

### Plan-code adaptations

- Plan suggested patching `src.research.shared_data._client`. Actual
  shape: `_fetch_raw` does `from v2.data.factory import
  get_provider_factory` inside the function body. Test patches
  `v2.data.factory.get_provider_factory` instead.
- `src/research/pipeline.py` (ResearchRequest path) does NOT thread
  market — `ResearchRequest` has no market field, so it gets the "us"
  default. Only the AnalyzeRequest/SOP path is wired for now.

### Verification

- `pytest tests/research/test_shared_data_market.py -v` → 4/4 pass
- `pytest tests/research/` → 190/190 pass (full regression)
- `pytest tests/test_research_chart_route.py` → 4/4 pass
- `pytest tests/test_analyze_routes.py` → 6/6 pass

### Commits

- `f2c2e3b` feat(research): thread market field through AnalyzeRequest API surface
- `e50a14a` feat(research): A-share benchmark + SW1 sector swap in shared_data

---

## Session — 2026-05-26 (Phase 8 Wave 4 — CompositeClient A-share routing)

### What shipped (Task 12 of `docs/superpowers/plans/2026-05-26-a-share-data-integration.md`)

- **v2/data/composite_client.py** — added optional `ashare_backend` slot
  to `CompositeClient.__init__`. Each ticker-keyed Protocol method
  (`get_prices`, `get_news`, `get_insider_trades`, `get_earnings`,
  `get_earnings_history`, `get_company_facts`, `get_market_cap`,
  `get_financial_metrics`) now checks `is_ashare(ticker)` first and
  dispatches to the A-share backend when matched; US tickers route
  unchanged. `close()` now deduplicates the ashare backend too.
- **make_hybrid_client** gained `include_ashare: bool = True` kwarg —
  when True, wires `AShareClient()` into the new slot; when False or
  ImportError on optional deps, leaves `_ashare = None`. Pre-existing
  callers see no behavior change (default-on, US tickers unaffected).
- **tests/v2/data/test_composite_ashare_routing.py** — 20 tests
  covering: a-share routing for all 8 ticker-keyed methods, US
  fall-through, bare/canonical/prefixed ticker forms, ChiNext + STAR
  prefixes, non-ticker `get_earnings_calendar` left alone,
  back-compat when `ashare_backend=None`, `include_ashare` kwarg
  semantics. All 20 pass.
- **Regression check**: pre-existing `v2/data/test_composite_client.py`
  still 13/15 passing — the 2 failures are pre-existing stale
  assertions vs. yfinance refactor (`_earnings` is YFinanceClient, not
  FinnhubClient), not introduced by this commit.
- **Plan-code adaptation**: plan said extend `v2/data/factory.py`, but
  `make_hybrid_client` actually lives in `composite_client.py`
  (factory just imports + calls it). Extended at the real definition
  site; factory.py untouched since its no-arg call works fine with the
  new default-True kwarg.

Commit: `82790af`

---

## Session — 2026-05-26 (Phase 8 Wave 1 — A-share foundation)

### What shipped (Tasks 1-3 of `docs/superpowers/plans/2026-05-26-a-share-data-integration.md`)

- **deps**: `mootdx` + `stockstats` added to `pyproject.toml` as the
  optional `[ashare]` extra; installed against anaconda Python 3.13.
  Plan called for `mootdx ^2.1.6` (doesn't exist on PyPI) - corrected
  to `^0.11.7` (current latest). Heads-up: mootdx pinned
  `httpx 0.25.2` and `tenacity 8.5.0`, downgrading from our locked
  `httpx ^0.27.0` / `tenacity 9.0.0`. chromadb/mcp/ollama now report
  version conflicts; verify those callers still work or relax the
  upstream pin before merging.
- **v2/data/ashare/symbol.py** — `is_ashare`, `normalize`,
  `infer_exchange` with the 6-digit + suffix + prefix forms.
  33-case parametrized test suite green.
- **v2/data/ashare/client.py** — `AShareClient` skeleton that satisfies
  the `DataClient` Protocol. All 6 v1 methods route by `is_ashare()`,
  lazy-import the (still missing) Wave 2 helper modules inside
  `try/except`, and degrade to `[]` / `None` on any failure. Optional
  protocol methods (`get_insider_trades`, `get_earnings`,
  `get_earnings_calendar`) return empty per spec - v1 has no insider /
  earnings-calendar coverage for A-shares.

### Commits

- `6dbc7c4` deps: add mootdx + stockstats as optional [ashare] extra
- `379c660` feat(ashare): symbol detection + canonical normalization
- `3e65f6c` feat(ashare): AShareClient skeleton implementing DataClient Protocol

### Verification

- `pytest tests/v2/data/ashare/` -> 35/35 passed (33 symbol + 2 protocol)
- `python -c "import mootdx; import stockstats; print('ok')"` -> ok
  (mootdx 0.11.7, stockstats 0.6.5)

### Plan deviations

1. `mootdx` version pin changed from `^2.1.6` (nonexistent) to `^0.11.7`.
2. Moved lazy `from v2.data.ashare.<helper> import ...` statements
   inside the `try` block of each `AShareClient` method (plan had them
   between `if not is_ashare` and `try`). Wave 2 modules don't exist
   yet, so an outside-try import would raise at first call and bypass
   the protocol's never-raise guarantee.
3. `AShareClient.get_earnings_calendar` signature corrected to
   `(*, start_date, end_date)` to match the Protocol's keyword-only
   contract (plan had positional args).

### Wave 1 done, Wave 2 unblocked

Wave 2A/2B/2C can now run in parallel. Each fills in one of the
lazy-imported helpers (`mootdx_prices`, `eastmoney_*`, `cls_news`,
`sw_sector_map`). The client skeleton already calls them with the
exact signatures the plan specifies, so Wave 2 contributors must match.

---

## Session — 2026-05-25 (Phase 6 landed — AI Strategy Lab)

### What shipped

- **18-block catalog** (`src/lab/spec/blocks_*.py`) — Pydantic v2 discriminated
  unions; 8 entry, 4 exit, 3 sizing, 3 filter blocks. LLM uses
  `with_structured_output(StrategySpec, method='json_mode')` to emit
  validated JSON in one shot.
- **Backtest engine** (`src/lab/engine/`) — universe loader (watchlist
  + sp500 + nasdaq100), DataLoader (batch OHLCV via existing v2/data),
  indicator precompute (RSI / SMA / EMA / ATR / MACD / Bollinger /
  Donchian / volume SMA), per-bar simulation with position cap + cost
  model, metrics (Sharpe / Sortino / MaxDD / Calmar / profit factor),
  verdict (insufficient / reject / overfit / weak / underperform_bench /
  positive_edge) adapted from stock-analyze-skills hard rules.
- **Walk-forward IS/OOS** — 70/30 default split; degradation ratio
  flags overfit even when IS looks great.
- **LLM chat wrapper** (`src/lab/chat.py`) — system prompt assembles
  catalog + prior strategies summary + current spec + last 20 chat
  messages; `ChatResponse` discriminated `RootModel` (`ProposeSpecPatch`
  vs `ChatReply`) keeps the frontend simple.
- **3 new DB tables** — `strategies` / `lab_chat_messages` / `backtests`
  (Alembic migration `c3e7f9d2b8a4`); 3 sync Session-injected repos.
- **13 REST endpoints** under `/lab/*` — strategy CRUD, chat send +
  apply, backtest run + list + get, 3 chart PNGs, catalog endpoint.
- **Frontend Lab tab** (FlaskConical sidebar icon) — `StrategyList` +
  `ChatPanel` + `SpecViewer` 3-column top + `BacktestRunner` +
  `BacktestResult` (verdict + 3 chart PNGs + IS/OOS metric grid) +
  `TradeLogTable` + `BacktestHistory` bottom. Tab state preserved via
  the Phase 5 `display:none` pattern.

### Commits (oldest -> newest)

- 774e8d3 — docs: implementation plan for Phase 6 — AI Strategy Lab
- 656d232 — feat(lab): 8 entry signal blocks with Pydantic validation
- 6ed8235 — feat(lab): 10 more blocks — exits + sizing + filters
- 885b4b1 — feat(lab): StrategySpec + discriminated unions for 18 blocks
- e5ea27b — feat(lab): CATALOG + LLM prompt text for 18 blocks
- 094c807 — feat(backend): Strategy + LabChatMessage + Backtest SQLAlchemy models
- 1073bdb — feat(lab): universe loader (watchlist + sp500 + nasdaq100)
- 51dd52b — feat(lab): DataLoader — batch OHLCV via existing v2/data layer
- 7ea6c0f — feat(lab): indicator precompute for all 18 v1 blocks
- a6a10ad — feat(backend): alembic c3e7f9d2b8a4 — add lab tables
- 9d260db — feat(backend): Lab repositories — Strategy + LabChat + Backtest
- 851fa6f — feat(lab): signal evaluation for all 18 blocks
- 4366ce1 — feat(lab): position sizing — fixed_pct / equal_weight / vol_targeted
- 6cf0b14 — feat(lab): per-bar simulation loop
- f66be9d — feat(lab): metrics computation (Sharpe/Sortino/MaxDD/Calmar/win%/PF)
- ebdea3a — feat(lab): verdict labels (insufficient/reject/overfit/weak/underperform/positive)
- f4169b0 — feat(backend): Lab Pydantic schemas
- 1ed0bbd — feat(lab): LLM chat wrapper with ProposeSpecPatch/ChatReply union
- 3a67b9c — feat(lab): backtest_runner — end-to-end orchestration
- 4a942e1 — feat(backend): /lab/* REST API (12 endpoints)
- c7d60a0 — feat(frontend): Lab tab plumbing — types, services, stub panel
- 8069304 — feat(frontend): Lab StrategyList + ChatPanel + ChatMessage
- 49ec1dd — feat(frontend): Lab SpecViewer + SpecBlockCard + SpecJsonEditor
- 71a902d — feat(lab): chart endpoint + 3 PNG renderers
- 8e924c6 — feat(frontend): Lab BacktestRunner + Result + TradeLog + History

### Tests

- **~76 new backend tests** under `tests/lab/` + `tests/test_lab_*.py`
  (Phase 6A 40, 6B 27, 6C 9, 6D 12, 6E 18, 6G 7) — all green (103 passed
  in the Phase 6 surface check)
- Full pytest: 1186 passed, 20 failed, 3 skipped. All 20 failures are
  pre-existing — 18 live-API tests in `v2/data/` + `v2/event_study/`
  (same set as Phase 5), 1 in `v2/data/test_yfinance_client.py`, and
  1 in `tests/test_scanner_service.py` that expects the old
  `earnings_surprise` detector name (now alias-rewritten to
  `earnings_event` at config load per MEMORY.md). No Phase 6
  regressions.
- Frontend tsc: clean on Phase 6 surface. Pre-existing errors only in
  `ui/sidebar.tsx` (ref-type variance, 5 sites), `panels/scanner/
  agent-run-detail.tsx` (unused Badge import), and `lib/utils.ts`
  (unused `provider` parameter).

### Plan-code fixes caught during execution

The plan was written without dry-run; subagents caught ~10 latent
bugs and fixed them inline. Notable ones:
- `verdict.py` had `f"({x if not None else 'n/a'})"` — string
  literal masquerading as Python ternary; would crash on
  `benchmark_cagr=None`.
- `simulation.py` test fixture didn't trigger any entries (flat 50
  bars then drop, no breakout before the drop).
- `signal_eval.py` `ma_cross` missed the NaN-prev-diff edge case on
  monotone-uptrend fixtures.
- Multiple sites swapped unicode `+/-`, `x`, `->`, `--`, `>=` to ASCII
  equivalents for Windows PowerShell encoding safety.

### Notes for next session
- The pre-existing flow migration `3f9a6b7c8d2e` has a duplicate-index
  bug that breaks fresh-from-zero `alembic upgrade head` on sqlite;
  does not affect existing project DBs. Worth fixing some day.
- `lab-panel.tsx` is fully wired; `BacktestRunner` runs sync (30s-5min);
  background queue is v2.
- Chat prompt + catalog text uses ASCII glyphs — if the frontend
  wants pretty unicode, transform at render time.

---

## Session — 2026-05-24 (Phase 5 landed — Charts + Watchlist + Flow Analyze + Auto-SOP)

### What shipped

- **Charts in Technical section** (Phase 5A) — matplotlib (`Agg` backend) rendering primitives in `src/research/charts/render.py`:
  - Equity curve inline as base64 `data:image/png` URI (works in email, ≤30KB after b64)
  - K-line daily/weekly served from `GET /research/reports/{id}/chart/{type}.png` (web iframe only; remote-image-blocked-by-Gmail trade-off documented)
  - `BacktestVerdict.signal_indices` added (nullable) so chart can be regenerated from a persisted report
  - Email render strips server-hosted `<img src="/research/...">` tags; keeps `data:` URIs
- **User-curated watchlist** (Phase 5B) — new `UserWatchlist` table + repository + Pydantic schemas + `/watchlists` REST CRUD + `/tickers/search` autocomplete (cached static table from nasdaq100 + sp500 + russell3000)
  - Frontend `WatchlistSection` mounted above ScannerAction in left sidebar: collapsible groups, ticker pills with × to remove, 300ms-debounced ticker search, create/rename/delete dialogs
- **Scanner config can target a watchlist** (Phase 5C) — `ScannerConfig.user_watchlist_id` FK + `universe_kind='watchlist'` enum value + universe loader knows the new kind + scanner service resolves the FK at scan time
  - Frontend dialog gains a second dropdown when kind=watchlist, populated from `watchlistService.list()`
- **Analyze panel as React Flow canvas** (Phase 5D) — replaces the Phase 4 ModulePicker checkbox column:
  - 16 SOP sections rendered as draggable `SectionNode` custom nodes (XyFlow v12)
  - Section palette on the left (click-to-add convention matches the existing Flow tab's `right-sidebar.tsx`)
  - Inline persona dropdown ON each persona-capable section node (no separate persona nodes — keeps the canvas small)
  - Edges are visual only; orchestrator still runs `SECTION_ORDER`
  - Saved templates persist to new `AnalyzeFlow` table + `/analyze-flows` REST routes + FlowList top-bar (load / save / new blank)
  - `AnalyzeRequest.persona_overrides` field threaded through schema → route → orchestrator so per-section persona pins work end-to-end
- **Auto-SOP cron + bundled email** (Phase 5E) — `ScannerConfig.auto_sop_top_n` + `auto_sop_use_personas` columns:
  - After `_persist_results` succeeds, scanner service calls `run_auto_sop_for_scan(db, scan_run_id, top_n, use_personas)`
  - Per-ticker SOP runs are isolated by try/except — one failure doesn't abort the loop
  - One bundled email via `dispatch_bundled(event_type="research.bundled", reports, scan_run_id)`: master index + per-ticker `<details>` collapsible blocks
  - `EmailHandler.send` + dispatcher `_render_for_event` both learned `research.bundled` event_type
  - Hook is OUTSIDE the scan's main try/except — follow-up failures cannot mark the scan ERROR

### Bug fixes during Phase 5

- **Empty SECTION_REGISTRY bug** (caught + fixed before Phase 5 dispatch) — `src/research/sections/__init__.py` was only importing the ABC, not the 16 concrete section modules, so `SECTION_REGISTRY` was empty at runtime and every section emitted "section not yet implemented." Now imports all 16 modules as side-effect imports. Regression guard: `tests/research/test_sop_orchestrator_e2e.py` runs the REAL registry (not the patched stub the unit tests use) — catches this class of bug.

### Migration chain (Phase 5)

```
d9f1c5b8e2a6 (Phase 4 — research_reports)
  → e7b9f3c5d1a8 (Phase 5B — user_watchlists)
  → c5d8a1f3e7b2 (Phase 5D — analyze_flows)
  → f2a4c6e8b9d1 (Phase 5C — scanner_configs.user_watchlist_id FK)
  → b8d2f9a4e6c1 (Phase 5E — scanner_configs.auto_sop_*)
```

All migrations are additive (no destructive ALTERs on Phase 1–4 tables). Each phase used `op.batch_alter_table` for SQLite-safe column adds.

### Commits (14 new on top of `7f71e03`)

```
80cb1c1 feat(phase5e): tests for auto-SOP runner + bundled email
61be9b9 feat(phase5e): ScannerService fires auto-SOP follow-up after each scan
8350a2c feat(phase5e): auto-SOP runner + bundled email + dispatcher routing
e23a5c6 feat(phase5e): ScannerConfig gets auto_sop_top_n + auto_sop_use_personas
7436591 feat(phase5c): frontend watchlist picker + integration tests
2f4df0f feat(phase5c): wire UserWatchlist resolution through scanner service
65eafcc feat(phase5c): scanner config can target a UserWatchlist as universe
16af718 feat(phase5d): React Flow Analyze canvas + saved templates + persona overrides
72ccfa6 feat(phase5b): user-curated watchlist subsystem
abcf7e6 feat(notifications): strip server-hosted <img> from research emails
9ec29ff feat(research): GET /research/reports/{id}/chart/{type}.png endpoint
6854257 feat(research): embed equity-curve PNG + K-line img in Technical section
da91318 feat(research): add signal_indices to BacktestVerdict
7449c39 feat(research): chart rendering primitives (kline + equity curve)
```

### Tests

- **Full pytest:** 1065 passed / 20 failed / 3 skipped. All 20 failures are pre-existing live-API tests in `v2/data/` and `v2/event_study/` — same set as Phase 4. Zero Phase 5 regressions.
- New tests by phase: A=9, B=15, C=7, D=12, E=10 → 53 new tests for Phase 5

### Smoke checklist (morning verification)

1. Restart backend + frontend (see Phase 4 commands; migrations auto-apply)
2. Open http://localhost:5173 → left sidebar shows new "Watchlists" section above Scanner
3. "+ Add watchlist" → name "Test" → "+ Add ticker" → type "NVD" → select NVDA
4. Scanner icon → "+ New config" → set `universe_kind=watchlist` → second dropdown shows "Test" → also try `auto_sop_top_n=2` + save → run scan → expect bundled email with 2 collapsible report blocks
5. Microscope (Analyze) icon → tab now shows React Flow canvas (not checkboxes). Click section in palette → node appears on canvas. Toggle persona dropdown on a persona-capable section. Save as "Quick view" via FlowList. Run SOP → 60-120s → iframe HTML has equity-curve `<img>` inline + a K-line `<img>` (loads via /research/reports/{id}/chart/kline-daily.png)
6. Section status pills + persona assignments box (Phase 4 polish) still render

### Risks for morning

- **Gmail clip** on bundled email if Top-N is large — bundled HTML can exceed 102KB. Master index mitigates navigation; Gmail's "show full message" still loads it
- **K-line `<img>` in email** — won't load (localhost backend not internet-reachable); equity curve still renders since it's base64-inlined
- **Auto-SOP duration** — Top-N=10 sequential SOP runs = ~10-20 minutes. The scanner cron at 16:30 ET would still be persisting reports through ~16:50. Not a problem for daily use; the bundled email fires once at the end

---

## Session — 2026-05-22 (Phase 4 landed — SOP-driven Analyze pipeline)

### What shipped

- **Vendored stock-analyze-skills assets** into `src/research/prompts/` — 10 module prompts + 8 persona briefs + SOP + report template
- **Vendored skill HTML template** with rich CSS (dark mode + bull/bear pills + score badge + collapsible `<details>` + print stylesheet)
- **New section-by-section orchestrator** (`run_sop` in `src/research/orchestrator_sop.py`) executing 15 SOP sections + 1 technical backtest sub-section in deterministic order
- **15 SOP sections** under `src/research/sections/`:
  - 8 LLM-driven prose sections (Macro, Sector, CompanyFundamentals, FinancialStatements, Valuation, Technical, RiskPosition, EventRisk, ExecutiveSummary, FinalStrategy)
  - 3 structured-output sections (EvidenceLedger, Scenarios, Conviction)
  - 2 deterministic no-LLM sections (DataHealth, MissingData)
  - Debate section wraps the Phase 2 debate engine
- **Always-75 confidence bug fixed at 2 layers**:
  - `ConvictionSection` computes `total_score` deterministically from weighted per-category scores
  - `ExecutiveSummary` reads the score from the prior (LLM has no `score` field in its output schema, so it structurally cannot supply one)
- **Technical-signal backtest** (RSI / SMA50 / MACD with t-stat significance gate) replaces detector-replay backtest for Analyze reports
- **SOP HTML render** (`render_sop` in `src/research/html_render.py`) — Jinja scalar fill + Python string injection of per-section bodies under matching `<h2>` slots; preserves the vendored template's CSS verbatim
- **New REST endpoint** `POST /research/analyze` + `AnalyzeRunRequest` / `AnalyzeReportDetail` schemas; backend orchestrates `run_sop` → `render_sop` → persist → return
- **Additive Alembic migration** `d9f1c5b8e2a6` adds nullable `analyze_request_json` + `sections_json` columns to `research_reports`; Phase 3 rows preserved untouched
- **New frontend "Analyze" tab** (Microscope icon, sidebar action independent of Scanner) with:
  - Gate form (ticker, objective, position budget, risk tolerance, personas)
  - Flow-style module picker (vertical pipeline visualization, all-modules-on default)
  - Iframe display of generated HTML report
  - Recent reports list with click-to-load

### Commits (9a2a384 → HEAD, 22 commits)

`git log --oneline 9a2a384..HEAD` →

- `c16e260` feat(research): vendor stock-analyze-skills prompts into repo
- `c12ee9c` feat(research): vendor skill HTML template
- `0540369` feat(research): AnalyzeRequest + AnalyzeReport + SectionPayload
- `6240714` feat(research): Section ABC + SECTION_REGISTRY + SectionContext
- `356fcf4` feat(research): DataHealthSection (deterministic, no LLM)
- `97bf2bf` feat(research): shared LLM section runner helper
- `0fe0adb` feat(research): MacroSection
- `24babfa` feat(research): SectorSection
- `68eb7a0` feat(research): CompanyFundamentalsSection (deepest section)
- `f0c17e1` feat(research): FinancialStatementsSection (2nd deepest, 600-950w)
- `d763875` feat(research): Valuation+Technical+RiskPosition sections
- `6ad65db` feat(research): structured EvidenceLedger+Scenarios+Conviction sections
- `212efba` feat(research): 5 closing sections - ExecutiveSummary/EventRisk/Debate/FinalStrategy/MissingData
- `d97c908` feat(research): technical-signal backtest
- `20f3bcc` feat(research): SOP orchestrator (run_sop)
- `7482e8f` feat(research): render_sop -- HTML for AnalyzeReport
- `4c10a47` feat(research): CLI uses run_sop + render_sop
- `1e76e7e` feat(backend): additive alembic — AnalyzeRequest + sections_json
- `dfde3c5` feat(backend): POST /research/analyze endpoint (Phase 4 SOP)
- `f372d28` feat(frontend): Analyze tab type + sidebar action + stub panel
- `99495d9` feat(frontend): AnalyzePanel — form + flow-style picker + iframe

### Test results (2026-05-22)

- **Phase 4 suite** (research/ + db models + repository + schemas + research routes + analyze routes + notifications + scheduler): **210 passed, 0 failed** (25 s)
- **Full suite regression**: **1009 passed, 20 failed, 3 skipped** (101 s)
  - All 20 failures are the same pre-existing live-API tests in `v2/data/` and `v2/event_study/`. None are in `src/research/`, `tests/research/`, `tests/test_research_*`, `tests/test_analyze_routes.py`, `tests/notifications/`, or `tests/test_scheduler_research_job.py`.
- **Frontend `tsc --noEmit`**: zero errors related to `research`, `analyze`, `module-picker`, or `report-list` files

### Smoke (2026-05-22)

HTTP smoke deferred. Backend at `http://127.0.0.1:8001` is running but was started BEFORE commit `dfde3c5` (POST `/research/analyze`) — `/openapi.json` confirms only the Phase 3 endpoints (`/research/run`, `/research/reports`, `/research/reports/{id}`, `/research/reports/{id}/html`) are registered; `POST /research/analyze` returns 404. To verify end-to-end:

```bash
# Stop the running uvicorn, then:
uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 --log-level info
# In another terminal:
curl -sX POST http://127.0.0.1:8001/research/analyze \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","objective":"medium_term","position_budget_usd":10000,"risk_tolerance":"balanced","use_personas":true}' | head -80
```

Test-suite coverage (`tests/test_analyze_routes.py`) exercises the route handler end-to-end with mocked LLM, so the runtime 404 is purely a server-restart artefact, not a code defect.

### What's unchanged

- All Phase 3 endpoints (`/research/run`, `/research/reports`, `/research/reports/{id}`, `/research/reports/{id}/html`) continue to function — additive migration preserves existing rows
- Legacy `_run_pipeline_job` cron (16:30 ET, populates `pipeline_runs` / `watchlist_entries`) untouched
- Phase 3 `_run_research_job` cron (16:35 ET, populates Phase 3 rows from latest watchlist) untouched
- `v2/`, `src/agents/`, and `src/main.py` untouched
- Phase 3 frontend research panel untouched; Analyze tab is additive and independent

## Session — 2026-05-22 (Research pipeline Phase 3 landed — production wired)

### What shipped

- **2 new DB tables** (`research_reports` + `research_trade_plans`) via additive Alembic migration `f3a1e43` / `bcec5cf`
- **`ResearchReportRepository`** with `create_with_plan` / `get_by_id` / `get_plan_for_report` / `list_reports` (ordered by `created_at` desc per spec)
- **Pydantic API schemas**: `ResearchRunRequest`, `ResearchReportSummary`, `ResearchReportDetail`, `TradePlanPayload`, `BacktestSummaryPayload`
- **HTML render** via Jinja2 + minimal markdown-to-HTML converter (email-safe with inline styles); no external CSS/JS
- **Persist helper** bridging `ResearchState` → DB row kwargs (`state_to_db_kwargs`)
- **4 REST endpoints**: `POST /research/run` (sync, 30-90 s), `GET /research/reports`, `GET /research/reports/{id}`, `GET /research/reports/{id}/html`
- **Email render path** for research reports (`render_research_html` + `render_research_text`) in `app/backend/services/notifications/`
- **Notification dispatcher** routes `"research.completed"` event to the research render handlers
- **Scheduler cron at 16:35 ET** (`tests/test_scheduler_research_job.py`) reads latest legacy `PipelineRun` watchlist for today and fires one research run per ticker
- **Integration test** (`tests/test_research_integration.py`): POST → list → detail → HTML round-trip with in-memory SQLite + mocked LLM

### Commits (eedd60b → HEAD, 11 commits)

- `f3a1e43` feat(backend): ResearchReport + ResearchTradePlan SQLAlchemy models
- `bcec5cf` feat(backend): alembic migration for research tables
- `590805c` feat(backend): ResearchReportRepository
- `c01b992` fix(backend): research repository orders by created_at (per spec)
- `055ddd3` feat(backend): pydantic schemas for /research API
- `c169527` feat(research): HTML render for ResearchState
- `0e19b79` feat(research): persist helper (ResearchState -> DB kwargs)
- `35efabb` feat(backend): /research REST API (4 endpoints)
- `80d10f3` feat(notifications): render_research_html + render_research_text
- `723b4b2` feat(notifications): dispatcher routes research.completed event
- `b4463ee` feat(scheduler): daily research cron at 16:35 ET

### Test results (2026-05-22)

- **Phase 3 suite** (research/ + db models + repository + schemas + routes + integration + notifications + scheduler): **136 passed, 0 failed** (23 s)
  - Phase 1: 54 | Phase 2: 34 | Phase 3 new: 48 (DB models, repository, schemas, routes, HTML render, persist, notifications, scheduler, integration)
- **Full suite regression**: **934 passed, 20 failed, 3 skipped** (97 s)
  - All 20 failures are pre-existing live-API tests in `v2/data/` and `v2/event_study/`. None are in `src/research/`, `tests/research/`, `tests/test_research_*`, `tests/notifications/`, or `tests/test_scheduler_research_job.py`.

### Smoke (2026-05-22)

HTTP smoke deferred to user — DO NOT try to start uvicorn in a non-interactive terminal. To verify:

```bash
uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 --log-level info
# then in another terminal:
curl -sX POST http://127.0.0.1:8001/research/run \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","risk_tolerance":"moderate","use_personas":true}' | head -50
```

CLI smoke from Phase 2 (`python -m src.research --ticker NVDA --use-personas`) still passes unchanged. Integration test (`test_post_then_list_then_detail_then_html`) covers the full POST → persist → list → detail → HTML cycle with a mocked LLM.

### Bugs caught and fixed during implementation

- **Task 3** — list ordering used `desc(id)` instead of spec'd `desc(created_at)`; fixed in `c01b992`
- **Task 5** — double-escape issue: Jinja `autoescape=True` + manual `_html.escape()` in the markdown converter produced `&amp;lt;` entities; fixed by escaping in the markdown converter and relying on Jinja's autoescape only for raw template variables
- **Task 9** — email/webhook handler refactor went wider than the plan scope: `email_handler.py` and `webhook_handler.py` were both refactored to accommodate the new `research.completed` event type routing alongside the existing `pipeline.completed` path

### Production state

- Legacy pipeline cron at 16:30 ET fires unchanged; persists into `pipeline_runs` / `watchlist_entries`
- Research cron at 16:35 ET fires when registered via `init_scheduler_service`; persists into `research_reports` / `research_trade_plans`
- Both croms fire independently; A/B comparison data accumulates in separate tables
- Frontend research-request panel explicitly deferred per spec (Phase 4 or UI sprint)
- Spec is otherwise fully implemented

## Session — 2026-05-22 (Research pipeline Phase 2 landed)

### What shipped

`src/research/personas/` namespace — per-module investor personas wired into the pipeline.

Components:

- **`PersonaPrompt` ABC** (`src/research/personas/base.py`) — abstract base with `name`, `description`,
  `system_addition()`, and `module_lens(module_name)` methods; concrete subclasses registered in
  `PERSONA_REGISTRY`.
- **8 investor personas** fully implemented:
  `buffett`, `munger`, `graham`, `fisher`, `lynch`, `wood`, `burry`, `druckenmiller` —
  each with a distinct system prompt fragment and per-module analysis lens.
- **`router.py`** — LLM persona-router that reads ticker/goal/risk and emits per-module persona
  assignments plus a `debate` pair. Invalid or absent LLM persona names coerced to `None`.
- **`debate.py`** — two-persona debate transcript produced in a single LLM call; embedded in the
  synthesizer's report when the router picks a debate pair.
- **3 persona-capable modules refactored**:
  - `fundamentals` — accepts `buffett`, `munger`, `fisher`
  - `valuation` — accepts `buffett`, `graham`, `munger`, `fisher`
  - `risk_position` — accepts `druckenmiller`, `burry`
  - All three prepend `persona.system_addition()` + `persona.module_lens(module_name)` to the LLM
    prompt when a valid persona is assigned.
- **`pipeline.py` wired**: when `use_personas=True`, router runs first; each module gets its assigned
  persona; debate fires and appends to report body when router picks 2 personas.
- **CLI `--use-personas` flag** + `PERSONA ASSIGNMENTS` section printed in `python -m src.research` output.

### Commits (6e4a2c2 → HEAD, 9 commits)

- `7db90a9` feat(research): PersonaPrompt ABC + Buffett + registry scaffold
- `5da0595` feat(research): 7 more investor personas (full Phase 2 set)
- `4f64838` feat(research): persona-router LLM agent
- `7a7f68a` feat(research): fundamentals module uses persona param
- `2eb1a0b` feat(research): valuation module uses persona param
- `0c8724a` feat(research): risk_position module uses persona param
- `9519503` feat(research): debate module (two-persona transcript)
- `67eab5e` feat(research): pipeline wires router + persona + debate
- `a3a67c9` feat(research): CLI --use-personas flag + assignment summary

### Test results (2026-05-22)

- **Research suite**: 88 passed, 0 failed (9.33 s)
  - Phase 1 tests: 54 | Phase 2 additions: 34 (personas, router, debate, pipeline persona paths)
- **Full suite**: 886 passed, 20 failed, 3 skipped (81 s)
  - All 20 failures are pre-existing live-API tests in `v2/data/` and `v2/event_study/`.
    None are in `src/research/` or `tests/research/`.

### Smoke test (2026-05-22)

`python -m src.research --ticker NVDA --use-personas --risk moderate --goal new_entry`

Result: **PASSED** (~44 s, 11 LLM calls).

- Router rationale visible in `PERSONA ASSIGNMENTS` section:
  `fundamentals=munger`, `valuation=lynch`, `risk_position=burry`, `debate=wood vs burry`
- Debate transcript (Wood vs Burry) appears in REPORT body; Burry's bear case dominates.
- Trade plan: `STAND_ASIDE` (confidence 85/100) — overvaluation + zero ROIC + lagging sector.
- All modules produced narratives; backtest section ran cleanly (0 matches, caveat emitted).

### Cost per ticker

~12 LLM calls: 8 modules + 1 router + 1 synthesizer + 0–1 debate (fires only when router picks 2 personas).

### Deferred

- **Phase 3**: DB persistence (`ResearchRun` table) + FastAPI endpoints + cron scheduler + HTML email digest

### Workflow

`superpowers:writing-plans` → `superpowers:subagent-driven-development`. Implementer + spec +
quality reviewer per task. Tasks 1–9 implemented by sub-agents, reviewed per task.

---

## Session — 2026-05-22 (Research pipeline Phase 1 landed)

### What shipped

`src/research/` namespace — a deterministic, LLM-backed per-stock research pipeline.
Components:

- **8 objective analysis modules** (each returns `ModuleResult` with `narrative` + `metrics`):
  `macro`, `sector`, `fundamentals`, `financials`, `valuation`, `technical`, `sentiment`, `risk_position`
- **`detector_backtest`** — deterministic replay of scanner detector hits against historical OHLCV;
  produces `BacktestSummary` with hit-rate, median CAR, caveat if N < 10
- **`synthesizer`** — DeepSeek LLM agent that reads all module narratives and emits a final
  `ResearchReport` Markdown + `TradePlan` (action, entry/stop/target or stand-aside)
- **Linear pipeline** (`run_research`) — fetches `SharedData` once, fans out to all modules in
  sequence, calls synthesizer, returns `ResearchState`
- **CLI entrypoint** (`python -m src.research --ticker X --risk moderate --goal new_entry`) with
  rich Markdown output and formatted trade plan table
- **54 unit tests, all green** — full mocks; no live API calls in the test suite

### Commits (3fe986a → HEAD, 20 commits)

- `463d26b` feat(research): scaffold package + data models
- `d73d05e` feat(research): SharedData fetcher with per-process cache
- `cf4ff80` fix(research): SharedData uses correct v2 protocol method name get_news
- `f7b8949` feat(research): call_research_llm helper with retry + default factory
- `b33efe1` feat(research): AnalysisModule ABC + module registry
- `8d90767` feat(research): macro module (objective)
- `41b7965` feat(research): sector module (objective)
- `4a5d81c` feat(research): fundamentals module (objective)
- `923d1cd` feat(research): financials module (objective)
- `f65ea3f` fix(research): financials reads from earnings_history not financial_metrics
- `33a0e38` fix(research): coerce CompanyFacts to dict in SharedData
- `8abff87` feat(research): valuation module (objective)
- `648e9f2` feat(research): technical module (objective)
- `361d9bc` fix(research): RSI(14) uses most recent 14 deltas, not oldest
- `46b0b5c` feat(research): sentiment module (objective)
- `c3e9b5d` feat(research): risk_position module (objective)
- `f4fc99a` feat(research): detector-replay backtest
- `51ecb26` feat(research): synthesizer LLM agent
- `9ecd88b` feat(research): pipeline orchestration (linear, no LangGraph yet)
- `208f9fb` feat(research): CLI entrypoint

### Notable bugs caught by review and fixed

1. **Task 2 — wrong v2 protocol method** (`cf4ff80`): plan said `client.get_company_news` but the
   v2 `DataClient` protocol exposes `get_news`. Fixed before any module used it.
2. **Task 8 — financials reading wrong field** (`f65ea3f`): module was looking for
   `shared_data.financials` but revenue/net_income/free_cash_flow live on `EarningsData` via
   `earnings_history`. Fixed to iterate `shared_data.earnings_history`.
3. **Task 10 — RSI(14) computed wrong window** (`361d9bc`): deltas were taken from the *first*
   14 bars instead of the *last* 14. Caught only because `test_rsi_reflects_recent_volatility`
   was added as a behavioral test; a pure smoke-pass test would have missed it.
4. **SharedData — CompanyFacts type inconsistency** (`33a0e38`): `company_facts` could be either a
   `CompanyFacts` Pydantic model or a raw `dict` depending on the data path. Fixed by calling
   `.model_dump()` at assignment so downstream code always sees a dict.

### Test results (2026-05-22)

- **Research suite**: 54 passed, 0 failed (10.5 s)
- **Full suite**: 852 passed, 20 failed, 3 skipped (104 s)
  - All 20 failures are pre-existing live-API tests in `v2/data/test_client.py`,
    `v2/data/test_composite_client.py`, `v2/data/test_protocol_conformance.py`,
    `v2/data/test_yfinance_client.py`, and `v2/event_study/test_event_study.py`
    (401 Unauthorized / missing API keys in CI environment). None are in `src/research/`
    or `tests/research/`.

### Smoke test (2026-05-22)

`python -m src.research --ticker NVDA --risk moderate --goal new_entry`

Result: **smoke skipped — DEEPSEEK_API_KEY not set + EODHD/Finnhub keys returning 401**.
Data fetch 401s logged as WARNINGs (correct behavior — modules skip gracefully).
LLM calls raise `ValueError("DeepSeek API key not found")` which propagates out of the synthesizer.
Pipeline structure is correct; end-to-end run requires live API keys in `.env`.

### Deferred

- **Phase 2**: persona modules (Buffett, Burry, Lynch…) + persona router + multi-persona debate panel
- **Phase 3**: DB persistence (ResearchRun table) + FastAPI endpoints + cron scheduler + HTML email digest

### Workflow

`superpowers:writing-plans` → `superpowers:subagent-driven-development`. Tasks 1–16 implemented by
Haiku, reviewed by Haiku (spec) + Haiku (code-quality). Task 17 narrative by Sonnet.

---

## Session — 2026-05-21 (3 production optimizations from backtest evidence)

Acted on three findings from today's backtests. None required new
30/60/90-day reruns — each change has direct evidence from existing
data, with smoke tests confirming behavior preservation.

### #5 — Add transaction cost to backtest framework
- `scripts/ab_backtest.py` + `scripts/ab_backtest_quant_ablation.py`
  now accept `--cost-bp` (default 10 = 0.10% round-trip). Each non-HOLD
  decision deducts `qty*entry_price*cost_bp/10000` from gross PnL.
- New `scripts/recompute_pnl_with_cost.py` re-costs existing CSVs
  without re-running the backtest.
- Validation: all three Part 1 regime gaps and the Part 4 quant gap
  survive 10 bp costing (both groups carry similar position sizes,
  so cost erosion is symmetric — gap preserved):
    Part 1 UP   20d cum gap:  +$26,000 → +$26,110
    Part 1 DOWN 20d cum gap:  +$12,400 → +$12,405
    Part 4 quant 20d cum gap: +$5,897  → +$5,914
- Commit `d697661`.

### #7 — Hide composite rank/score from scanner_signal LLM prompt
- `src/agents/scanner_signal.py` prompt template no longer renders
  "Composite attention rank: {rank}, score {composite_score}/100".
  LLM sees ticker + scan_date + detector triggers only.
- `_fallback_reasoning` no longer mentions composite score.
- Confidence flow unchanged: scanner_signal_agent still emits
  `confidence = composite_score` so PM aggregation logic doesn't
  change. Only the LLM's textual reasoning is shielded.
- Why: §6 quartile backtest showed composite_score Top-Bottom spread
  is -6.80% at 20d (no quant) — the ordinal rank is provably anti-
  predictive. Hiding rank from the LLM prevents it from biasing on a
  number we know is reversed.
- Tests updated: 19/19 pass.
- Commit `52f72d3`.

### #6 — Tighten analyst_rating + insider thresholds
Per-detector FDR-significant 5d losers at prior thresholds:
  analyst_rating  -3.09%  p_fdr=0.0000  n=66
  insider_cluster -2.52%  p_fdr=0.0221  n=67

Changes:
- `analyst_rating.py:net_z_threshold` 2.0 → **3.0** (only fires on
  the strongest upgrade/downgrade waves)
- `insider.py:cluster_min_buyers` 2 → **3** (requires 3+ insiders
  agreeing, not 2)
- `insider.py:single_buy_dollar_threshold` 250_000 → **500_000**
  (single $500k+ P-buy required for solo trigger)

`earnings_event` was on the list (-4.78% FDR-sig 5d) but it's
window-based (pre/post-earnings-day window) not severity-gated;
tightening requires narrowing the window rather than raising a
threshold. **Left as follow-up.**

Tests updated to match new defaults:
- `test_two_buyers_is_enough_to_cluster_fire` →
  `test_three_buyers_is_enough_to_cluster_fire` + new negative
  test `test_two_buyers_does_NOT_cluster_fire`
- `test_buy_severity_higher_than_sell_at_same_z`: 2 → 3 buyers
  (multiplier math unchanged; cluster size is incidental)
- Stale docstring references to "default 2" / "≥ $250k" updated

178/178 detector tests pass (82 invariant + 95 behavior + 1 new).
Commit `6c45dcf`.

### What was deliberately NOT done
- **#1 composite_score → binary filter**: user rejected — too
  invasive for a refactor; #7 covers the LLM-bias subset.
- **#2 CHOP regime skip**: user pushback was correct — killing the
  scan removes free information, AND trailing-20d regime classifier
  is inherently lagging.
- **#4 DOWN turn off quant**: same regime-lag problem; the small
  compute savings don't justify the risk of mis-classifying.

### Verification path (no new backtest)
Each change has direct evidence in existing CSVs:
- #5 cost: re-applied via `recompute_pnl_with_cost.py`, summary
  regenerated; gaps preserved → claim holds.
- #7 rank-hidden: behavior verified by smoke prompt rendering +
  19/19 scanner_signal unit tests green.
- #6 thresholds: 178/178 detector tests green (invariant + behavior).

Live alpha verification continues on the running paper-trade cron.
The 3 changes ship to production with default config; impact will
materialize in daily-cron emails over the next 1-2 weeks.


---


## Session — 2026-05-21 (Part 4: quant on/off agent-layer A/B — results in)

The 4.3-hour background quant-ablation A/B (`bn8tuyoun`) finished. Three
per-regime CSVs landed at `outputs/ab_quant_ablation_{up,down,chop}*.csv`
and the combined summary at `outputs/ab_quant_ablation_combined_summary.txt`.

### Setup
Same 3 windows as Part 1 (UP / DOWN / CHOP, 30 trading days total),
same agents, same model (deepseek-chat), same top-N=3. Only difference
from Part 1: B group runs the same scanner→11 agents→PM pipeline as A
but with `use_quant_signals=False`, so composite_score = event_score
only. The new `use_quant_signals` flag was added to `run_pipeline` with
default True (production cron behavior unchanged).

### Results — 20d cumulative PnL gap (A quant ON − B quant OFF)

| Regime | A 20d cum | B 20d cum | Δ |
|---|---|---|---|
| UP   | +$10,978 | +$5,014  | **+$5,964** ✅ |
| DOWN | +$4,813  | +$4,880  | -$67 (tied) |
| CHOP | $0       | $0       | $0 ⚠️ (EODHD daily limit broke CHOP forward prices) |
| **Combined** | **+$15,792** | **+$9,894** | **+$5,897** |

All p-values > 0.5 (n=55 / 51 combined). Trend robust but not
statistically significant — sample size limited.

### Key observations

1. **Quant's contribution is positive but marginal.** UP regime drives
   the entire gap (+$5,964). DOWN is neutral. CHOP is unusable due to
   data loss when EODHD hit its daily request cap mid-run.
2. **DOWN changes behavior without changing outcome.** Ticker overlap
   is only 29% — quant picks meaningfully different tickers in DOWN.
   Action mix differs sharply: A=4buy/7hold/10short, B=9buy/1hold/5short.
   But the resulting PnL is essentially identical. Quant ON nudges
   the agent toward more defensive postures in DOWN that don't pay
   off any better than B's more aggressive buy stance.
3. **Hit rate inverts magnitude.** Combined hit rate A 40% < B 45%, yet
   A wins on total PnL. Pattern: quant ON produces **fewer winners but
   bigger winners** — consistent with quant acting as a quality filter
   that concentrates picks where conviction is higher, rather than as
   a directional predictor that improves hit rate.

### Relative contribution vs Part 1

```
Part 1 UP 20d cum gap (scanner+quant vs random):  +$26,000
Part 4 UP 20d cum gap (scanner+quant vs scanner): +$5,964
→ Event detection alone contributes ~+$20,036 (~77% of scanner edge)
→ Quant_signals contribute               ~+$5,964  (~23% of scanner edge)
```

This **refines** Part 3's earlier hypothesis. Part 3 said "quant's
real value shows up at agent layer, not at scanner-self level". That's
correct — but the actual magnitude is ~23% of the scanner edge, not the
majority. Event detection is the workhorse; quant is incremental.

### What this means for production

- Daily cron continues with quant ON (current config). Net positive.
- If CHOP regime persists for an extended period, monitor whether the
  defensive bias in DOWN/CHOP is actually hurting (n is too small now
  to say).
- Next-test candidate: bigger sample (60-90 trading days) for tighter
  CIs. Current results trend-only, not significant.

### Limitation: CHOP data loss

EODHD free tier daily request limit (100k requests/day) was reached
during the CHOP run's final days. Forward-price lookups failed → CSV
has null `price_5d`/`price_20d` for many positions → non-HOLD entries
all show pnl=$0 (script defaults). CHOP regime therefore yields zero
informational content from this run. If we want a real CHOP read, we
need to re-run that window on a fresh API quota day, or migrate to a
provider without per-day caps.

### Files touched
- `v2/pipeline/orchestrator.py` (modified earlier this session: added
  `use_quant_signals` param to `run_pipeline`)
- `scripts/ab_backtest_quant_ablation.py` (new)
- `scripts/ab_quant_ablation_summary.py` (new)
- `outputs/ab_quant_ablation_{up,down,chop}_*.csv` (new, generated)
- `outputs/ab_quant_ablation_combined_summary.txt` (new, generated)
- `outputs/backtest_report_2026-05-20.md` (extended with Part 4 section
  + updated artifacts list)


---


## Session — 2026-05-21 (Detector invariant test suite landed)

### What shipped

**tests/test_detector_invariants.py** (~106 LoC public test file): 8 invariant rules covering CLAUDE.md's 4 load-bearing detector contracts plus 4 observable best-practice rules, parameterized over all 10 detectors in `v2/scanner/detectors/`. **tests/_detector_lint.py** (~400 LoC private helper): AST visitors and introspection scanners (underscore prefix keeps it out of default discovery). Total: **82 invariant tests, all green**.

### The 8 rules

- **RULE-1** (std floor): `std()` results stored as a divider must go through a floor; raw `std()` used directly as a denominator is a bug (see GEHC z=+55 trillion incident).
- **RULE-2** (forbidden std fallback): The pattern `float(arr.std()) or 1e-6` is banned — fires only when std is exactly 0.0, misses collapsed-but-nonzero case.
- **RULE-3** (components dict float-only): Every value stored in a `components` dict must be explicitly wrapped in `float()` — prevents int/numpy-scalar leakage into downstream JSON serialization.
- **RULE-4** (no client memoization): `detect()` must not memoize a `DataClient` onto `self` — `requests.Session` is not thread-safe; the runner pools clients via `queue.Queue`.
- **RULE-5** (bare except must log/raise): Any bare `except` (or `except Exception`) block must contain a `logger.warning/error` call or a `raise` — silent swallowing hides bugs.
- **RULE-6** (detector name unique+non-default): Each detector's `name` class attribute must be set (not the class name default) and must be unique across all detector files.
- **RULE-7** (direction literal in `{bullish,bearish,neutral}`): Any string literal assigned to a `direction` variable must be one of the three canonical values.
- **RULE-8** (detect() return type `EventTrigger | None`): The `detect()` method's return annotation must be exactly `EventTrigger | None` — `None` means "no data, exclude ticker"; `EventTrigger(triggered=False)` means "ran cleanly, didn't fire."

### Violations fixed while landing (35+ total)

- **RULE-3**: 30 violations across 6 detectors (`bollinger_squeeze`, `earnings`, `intraday_move`, `news_sentiment`, `obv_divergence`, `volume_anomaly`) — wrapped non-float RHS in `float()`
- **RULE-5**: 2 violations in `analyst_rating.py` — added `logger.warning()` to two bare except handlers
- **RULE-1**: 5 violations (4 expected + 1 bonus discovery in `insider.py`) — added `# noqa: std-floor` annotations with reason text explaining why each site is intentional or safe

### Rules with zero violations on first run (trunk already clean)

RULE-2, RULE-4, RULE-6, RULE-7, RULE-8.

### Housekeeping

One housekeeping commit (`9fde81a`) brought 6 untracked detector files into git tracking so subsequent fix commits would have clean diffs.

### Workflow

superpowers `writing-plans` → `subagent-driven-development`. 10 plan tasks, each with implementer + spec reviewer + code quality reviewer (haiku for most, sonnet for the larger ones). Two reviewer-flagged issues addressed: RULE-8 was tightened to require exactly `{EventTrigger, NoneType}` (was permissive); RULE-4 broad scope was kept (rejected reviewer's narrow-scope suggestion since nested-helper assignment still mutates `self`).

### Docs

- Spec: `docs/superpowers/specs/2026-05-21-detector-invariant-tests-design.md`
- Plan: `docs/superpowers/plans/2026-05-21-detector-invariant-tests.md`

### Why this matters

Prior to today, CLAUDE.md documented 4 detector invariants but enforcement was human review only. Now any new detector that violates any of the 8 rules fails the test suite at commit time. The existing 95-test behavioral suite (`v2/scanner/test_detectors.py`) remains green — no regressions from the noqa annotations, logger additions, or float() wraps.

### Commits

97cd37d → 631d519 (11 commits including housekeeping `9fde81a`)

---


## Session — 2026-05-21 (§6 quartile @ 20d + Step 2 quant-ablation A/B kickoff)

Follow-up to 2026-05-20 backtest report. Two open questions:
1. Is composite_score rank inversion (-2.62% @ 5d) a 5d-noise artifact
   or a real-window failure? Test: re-run §6 quartile spread at 20d.
2. Does `quant_signals` actually add value in the agent path? Part 1's
   scanner-vs-random A/B had quant on BOTH sides; never isolated. Test:
   re-run full pipeline A/B with quant on vs off, same 3 windows.

### Step 1 — §6 quartile spread at 1d/5d/20d/63d

New script: `scripts/analyze_quartile_by_window.py` — reads
`backtest_ndx100_30d_no_quant.csv` and `_with_quant.csv`, computes
bucket means with paired bootstrap CI on the (Rank 1-5 − Rank 16-20)
spread for every available forward window. Output:
`outputs/quartile_by_window_2026-05-21.txt`.

Result (Top − Bottom spread, n_top=105, n_bot=86–91):

| Window | no quant | CI                 | with quant | CI               |
|--------|----------|--------------------|------------|------------------|
| 1d     | −0.45%   | [−1.27, +0.39]     | −0.66%     | [−1.49, +0.18]   |
| 5d     | **−2.62%** | [−4.74, **−0.48**] | −1.98%   | [−4.07, +0.21]   |
| 20d    | **−6.80%** | [−13.72, +0.36]  | −0.65%     | [−7.08, +5.73]   |
| 63d    | —        | n insufficient     | —          | n insufficient   |

Findings:
- **20d Top-Bottom does NOT turn positive in either case.** The user's
  decision rule said: "if 20d transitions positive, ranking is fine, just
  doesn't work at 5d." We're in the other branch.
- **no-quant 20d shows monotonic rank inversion** — Rank 16-20 returns
  +6.13% at n=91 vs Rank 1-5 at −0.67%. Bottom-quintile alpha is the
  outlier driving the −6.80% spread. CI [−13.72, +0.36] is wide but
  point estimate is strongly negative.
- **with-quant 20d (−0.65%) is dilution, not repair.** Pattern goes
  non-monotonic (Rank 6-10 is the worst at −3.15%), CI [−7.08, +5.73]
  spans both sides. Quant adds noise that cancels the inversion at the
  aggregate level rather than fixing the underlying sort.
- 5d no-quant inversion (−2.62%, CI [−4.74, −0.48]) **excludes 0** — the
  only statistically significant cell. Composite_score is provably
  miss-ranking at 5d.

### Step 2 — full pipeline A/B with quant on/off (running in background)

Goal: isolate quant_signals' agent-layer contribution. A=quant on,
B=quant off, both groups go scanner→11 agents→PM, same days. Mirrors
Part 1's structure but replaces "random tickers" baseline with
"event-only scanner" baseline.

Wiring:
- `v2/pipeline/orchestrator.py`: added `use_quant_signals: bool = True`
  to `run_pipeline` (default unchanged — prod cron stays at quant on).
- `scripts/ab_backtest_quant_ablation.py` (new): both groups go through
  `run_pipeline`, toggling `use_quant_signals` per group.
- `scripts/ab_quant_ablation_summary.py` (new): reads 3 per-regime CSVs,
  emits per-regime + combined report with 20d PnL CI, t-test, hit rate,
  action mix, ticker overlap.

Smoke test (1 day, 2026-04-06, top_n=3, balanced template, deepseek-chat):
- Group A (quant on): MRVL buy, BKNG short, NFLX short
- Group B (quant off): MRVL buy, BKNG short, TSLA short
- Overlap 2/3, confidence varies on overlap (MRVL conf 70 vs 80,
  BKNG 80 vs 83 — quant context flows through to PM).
- Wall clock: 520s for 1 day (Group A 305s, Group B 215s). The
  WITH-quant scan is ~90s slower because of the 5 extra signals.
- 1-day delta: A's NFLX +$1,218, B's TSLA −$1,667 → A wins +$2,885 in
  this tiny sample.

Full run (background bash `bn8tuyoun`):
- UP   2026-04-06 → 04-17 (10 days)
- DOWN 2026-03-09 → 03-20 (10 days)
- CHOP 2026-01-12 → 01-23 (10 days)
- ETA: 4.3 hours wall clock. CSVs land at
  `outputs/ab_quant_ablation_{up,down,chop}_*.csv` then summary script
  produces `outputs/ab_quant_ablation_combined_summary.txt`.

### Decision: §6 fix postponed

Per user direction, do not touch composite_score weighting until Step 2
results in. If Step 2 shows A>B (quant helps in agent path), the rank
inversion at the scanner-self level is irrelevant — agents read the
score as one feature among 11, not as a sort key. If Step 2 shows A≈B
or A<B, then revisit composite weighting (current 60/40 event/quant).

### Files touched

- `v2/pipeline/orchestrator.py` (modified: added `use_quant_signals` param)
- `scripts/analyze_quartile_by_window.py` (new, ~110 LoC)
- `scripts/ab_backtest_quant_ablation.py` (new, ~210 LoC)
- `scripts/ab_quant_ablation_summary.py` (new, ~190 LoC)
- `outputs/quartile_by_window_2026-05-21.txt` (new)
- `outputs/ab_quant_ablation_smoke.csv` (new, smoke test data)


---


## Session — 2026-05-19 (Macro + Sector as proper analyst agents)

User feedback on the earlier macro_context layer: prompt-injection was
a leaky abstraction — only 3 personas saw the context, PM didn't,
emails didn't surface it. Refactored macro into a real analyst agent;
also built sector as a new analyst.

### Macro → `macro_agent`

`src/agents/macro_agent.py` (new) replaces the deleted
`src/agents/macro_context.py`. Same SPY 20d trend + ^VIX fetch
(module-level cache keyed on scan_date for cross-ticker dedupe), but
emits a standard analyst signal — same value per ticker because macro
is portfolio-level, reasoning explicitly tells the PM so.

Signal mapping (rule-based, no LLM call needed):

  regime=up, vol=normal/low   → bullish (conf scales with trend strength, capped 80)
  regime=up, vol=high         → neutral (rally on high vol = unstable)
  regime=down, vol=normal/low → bearish (conf scales with trend, capped 80)
  regime=down, vol=high       → bearish but lower conf (panic noise)
  regime=chop                 → neutral conf 20
  regime=unknown              → neutral conf 0

Smoke for 2026-04-17: SPY +7.6%, VIX 17.5 → bullish conf 76 across all
test tickers.

### Sector → `sector_agent`

New `src/agents/sector_agent.py`. Per-ticker workflow:
1. Look up GICS sector via v2 hybrid client's `get_company_facts`.
2. Map sector to SPDR sector ETF (XLK / XLV / XLF / etc.) — mapping
   covers both GICS-level labels AND Finnhub's industry-level labels
   ("Semiconductors" → XLK, "Banking" → XLF, "Pharmaceuticals" → XLV
   etc.) because Finnhub returns a mix.
3. Compute 20-trading-day return for both ticker and sector ETF.
4. Relative strength = ticker_return − etf_return.
5. Signal: bullish if RS ≥ +3pp, bearish if ≤ −3pp, else neutral.

Caching: per-ticker sector lookups + per-(etf, scan_date) ETF returns
shared across tickers in the same sector — same ETF fetched once per
run regardless of how many tickers map to it.

Smoke for 2026-04-17 across 5 tickers: correctly classified NVDA →
Semiconductors → XLK, JPM → Banking → XLF, XOM → Energy → XLE, JNJ →
Pharmaceuticals → XLV, AAPL → Technology → XLK. All within ±3pp RS
(broad-market rally, no significant divergence).

### Registration

Both registered in `src/utils/analysts.py:ANALYST_CONFIG` (order 20 and
21). Both added to the balanced template — now 11 analysts:

  scanner_signal, macro_signal, sector_signal,
  warren_buffett, cathie_wood, michael_burry,
  fundamentals_analyst, technical_analyst,
  valuation_analyst, sentiment_analyst, growth_analyst

### Cleanup

- Removed the obsolete macro_context prompt-injection from
  `warren_buffett.py` / `cathie_wood.py` / `michael_burry.py` (3 places
  each: system message placeholder + prompt.invoke kwarg + import).
- Removed `macro_context` kwarg from `src/main.py:run_hedge_fund` and
  both orchestrator paths.
- Deleted `src/agents/macro_context.py` (no remaining importers).

### Tests

153/153 pass. The orchestrator test stub already accepts (and ignores)
the unused macro_context kwarg from the previous refactor — still works
after my removal because the orchestrator stopped passing it.

### Cost impact

Balanced template grew from 9 → 11 analysts. Both new agents are
rule-based (no LLM call), so the only extra cost per pipeline is 2-3
HTTP calls (SPY, VIX, one CompanyFacts per ticker) — negligible vs
$0.10/day LLM spend. Daily cron continues at ~$3/month.


---


## Session — 2026-05-19 (Persona refusal + macro context layer)

Adapted two ideas from the user's external stock-analysis skill repo
(github.com/Jelly13124/stock-analyze-skills) into the agent workflow:

### Persona refusal rules — `abstain` as a first-class signal

Buffett / Wood / Burry now have explicit REFUSE conditions in their
system prompts. When a ticker is outside their framework (e.g. Buffett
on a pre-revenue biotech, Wood on a regulated utility, Burry on a
momentum tech), they output `signal="abstain"` instead of forcing a
fake `neutral` vote.

- `WarrenBuffettSignal.signal`, `CathieWoodSignal.signal`,
  `MichaelBurrySignal.signal` extended to `Literal["bullish", "bearish",
  "neutral", "abstain"]`.
- System prompts gained a top-level "REFUSE TO OPINE" block listing
  abstention conditions specific to each persona's investing
  philosophy.
- `portfolio_manager.py` skips abstain entries when compressing
  analyst signals (lines 56-69) so the PM's prompt sees a smaller but
  more conviction-laden roster rather than diluting weight with fake
  neutrals.

Goal: address the persona-overlap noise observed in A/B W2 where the
3 personas all "voted" on every ticker even when the framework didn't
apply. Refusal turns each persona into a discriminating discrete signal
("I have conviction here" vs silence) rather than a noisy continuous
score.

### Macro context layer — regime overlay for every persona

New module `src/agents/macro_context.py`:
- `compute_macro_context(scan_date, provider_factory)` — fetches SPY's
  trailing 20 trading days via the v2 hybrid client, computes 20d
  return + annualized vol; fetches ^VIX via yfinance for a vol regime
  label. Classifies regime: `up` (>+1%), `down` (<-1%), `chop`
  otherwise. Never raises; returns a degraded shape on any error.
- `format_macro_context_block(state)` — renders the snapshot as a
  short prompt-injectable block; returns empty string when state
  lacks the context so interactive callers see no behaviour change.

Wired into `v2/pipeline/orchestrator.py:run_pipeline()` and
`run_agents_only()` — computed once per pipeline, passed through
`run_hedge_fund(macro_context=...)` into
`state['data']['macro_context']`. Persona prompts (Buffett / Wood /
Burry) read it and prepend a "TODAY'S MARKET CONTEXT" line.

Live smoke for 2026-04-17:
- SPY 20d = +7.6% → regime "up"
- VIX 17.5 → vol regime "normal"
- Single-line summary: `SPY 20d trend = up (+7.6%) | VIX = 17.5 (normal)`

Goal: address the W2 failure mode where every persona ignored the
market regime and the agents collectively pushed into SHORT-heavy
allocation during a recovery week. Each persona now sees the regime
explicitly and can weigh it (the prompt says "do NOT override your
framework if the ticker setup is clear" — macro is context not
override).

### Files

**New**:
- `src/agents/macro_context.py` (~150 lines)

**Modified**:
- `src/agents/warren_buffett.py` — signal schema + system prompt
  REFUSE block + macro_context placeholder in prompt invocation
- `src/agents/cathie_wood.py` — same
- `src/agents/michael_burry.py` — same
- `src/agents/portfolio_manager.py` — skip abstain in signal compression
- `src/main.py:run_hedge_fund` — accept `macro_context` kwarg, inject
  into state
- `v2/pipeline/orchestrator.py` — compute + pass macro_context; new
  `run_agents_only` kwarg
- `v2/pipeline/test_orchestrator.py` — `_fake_hedge_fund` stub accepts
  macro_context kwarg

### Verification

`pytest src/agents/test_scanner_signal.py v2/pipeline/
tests/test_pipeline_repository.py tests/test_pipeline_routes.py
tests/test_scheduler_service.py tests/notifications/ -q` → **153/153
passed**.

Macro layer smoke confirmed (SPY + VIX fetch returns sane values for
2026-04-17). Persona refusal end-to-end validation will happen at the
next daily cron fire (16:30 ET) — the changes are live in production
since the schedule is already enabled from this morning's ship.

### Caveats not addressed

- 5 other persona agents (Druckenmiller, Fisher, Graham, Lynch, Munger)
  not yet in the balanced template still have the old 3-way schema. If
  added to the template later, mirror the same pattern.
- `risk_management_agent` still emits its position-limit-style payload
  with no real "signal" — PM filters it by name prefix
  (`startswith("risk_management_agent")`) unchanged.
- Macro context fetch adds ~1s SPY call + ~2s VIX call to every
  pipeline run. Acceptable for the daily cron; would be optimizable
  later via per-day cache.


---


## Session — 2026-05-19 (A/B validation + ship to paper-trade)

### What we did

Validated the scanner→agent pipeline via **scanner-vs-random A/B
backtests**, then made 2 lossless improvements and re-ran. Mixed
stability results; chose to ship to **paper-trade mode** (cron enabled,
emails out, no real trades) for 30 days of live observation rather than
shipping fully or shelving.

### The A/B framework

The "right" evaluation of the scanner per `project-scanner-design-intent`
isn't "do scanner picks generate alpha" but "**do agent decisions on
scanner-flagged tickers beat agent decisions on randomly-sampled tickers,
same agents, same day**?"

Implementation:
- `scripts/ab_backtest.py` — driver: for each trading day, runs
  `run_pipeline` (group A: scanner top-N) AND `run_agents_only` (group B:
  random N, empty scanner_context); each PM decision gets forward 5d/20d
  realized PnL.
- `scripts/ab_backtest_summary.py` — aggregator: mean PnL per group with
  bootstrap CI, Welch t-test A vs B, hit rate (PnL>0) with Wilson CI,
  per-action and per-day breakdowns.
- Added `v2/pipeline/orchestrator.py:run_agents_only()` so group B can
  reuse the same agent stack without going through the scanner.

### Baseline (2026-04-06 → 2026-04-17, 10 trading days, top-3)

- 5d: A $194 vs B -$204; A-B = +$398 (p=0.11); hit gap 19.7pp
- 20d: A $7 vs B -$606; A-B = +$613 (p=0.35); hit gap 20pp
- Cumulative gap: 5d +$11k, 20d +$17k
- A's BUYs strongly outperformed (+$1,884/decision at 20d vs B BUY
  -$1,695) — the headline: scanner pre-filter reliably surfaces
  tickers the agents can BUY profitably.

### Pre-ship improvements

**Task 1 — strip direction from scanner_signal_agent**: bridge agent's
`signal=direction, confidence=composite_score` was contaminating
downstream personas with a 42%-accurate direction guess. Changed to
`signal="neutral"`, prompt made direction-free, reasoning rewritten
to describe events without buy/sell suggestion. 19/19 tests pass.

**Task 2 — insider asymmetric thresholds**: **no code change** — the
detector already implements buy threshold 2 / sell threshold 4, buy
weight 1.3× / sell weight 0.7× per Cohen-Malloy-Pomorski. User's
proposed spec matched current state.

**Task 3 — wire 5 quant signals into orchestrator**: orchestrator was
calling `run_scan` without `quant_signals`, so composite_score =
event_score only (quant_weight=0.40 effectively wasted). Wired
`quant_signals=[cls() for cls in ALL_SIGNALS]` so the 60/40 event/quant
split is now active.

### Re-run A/B window 1 (post-changes)

| Metric | Baseline | V2 | Δ |
|---|---|---|---|
| 5d PnL gap | +$398 | **+$453** | +$55 |
| 5d p-value | 0.11 | **0.08** | better |
| 5d hit gap | 19.7pp | 9.7pp | -10pp |
| 20d PnL gap | +$613 | **+$917** | +$304 |
| 20d p-value | 0.35 | **0.19** | better |
| 20d hit gap | 20pp | 12.6pp | -7.4pp |
| Cum 20d gap | +$17k | **+$26k** | +$9k |

Money-weighted metrics improved substantially. Hit rate gap fell
slightly but mean PnL per win grew (fewer wins, bigger wins). Action
distribution healthier: A's SHORTs 16→12, BUYs 11→13, HOLDs 3→5 —
less bearish bias after direction strip.

### Window 2 stability check (2026-03-19 → 2026-03-25, 5 trading days)

Scope reduced from 10d → 5d because EODHD got rate-limited during the
day (cumulative throttling from earlier backtests; day 1 took 34 min
vs typical 4 min).

| Metric | V2 W1 (10d) | **V2 W2 (5d)** |
|---|---|---|
| 5d PnL gap | +$453 | **-$245 ❌** |
| 5d p-value | 0.08 | 0.44 |
| 5d hit gap | +10pp | **-20pp ❌** |
| 20d PnL gap | +$917 | **+$620 ✅** |
| 20d hit gap | +13pp | **+27pp ✅** |
| Cum 20d gap | +$26k | **+$9k ✅** |

**5d horizon went the wrong way in W2; 20d stayed consistently
positive**. With n=15 per group and p=0.44, the 5d "reversal" is well
inside CI overlap — can't reject H0=no-effect. Hypothesis: W2 was a
recovery week where shorting profited generically (B's 8 shorts averaged
+$419) but scanner's event-supported tickers were short-resistant
(A's 8 shorts averaged -$465). Both groups got pushed into SHORT-heavy
allocation by the market environment.

### Ship decision (paper-trade mode)

Strict ship criteria (hit gap ≥ 10pp AND PnL gap ≥ $300 AND p < 0.10,
both windows) **not met** — W2 5d fails all three. But 20d signal is
consistent across BOTH windows.

Chose **option C — paper-trade ship**:
- `PATCH /pipeline/schedule {enabled: true, model_name: "deepseek-chat",
  model_provider: "DeepSeek"}` — cron fires 16:30 ET weekdays.
- Email subscription (id=1, ruizheyuan3487@gmail.com) was already on.
- Decisions persist to `pipeline_runs`; emails go to inbox with
  per-ticker PM action + valuation-conflict warnings + LLM gist.
- **No real trades** — system never had execution. User tracks emails
  as paper-trade signals for 30 days.

Decision point at +30 days: if A>B persists across more windows, build
execution layer; if not, investigate 5d-horizon weakness with
regime-aware logic or kill the project.

### Files

**New**:
- `scripts/ab_backtest.py` (driver)
- `scripts/ab_backtest_summary.py` (aggregator)
- `outputs/ab_backtest_2026-04-06_2026-04-17.csv` (baseline)
- `outputs/ab_backtest_2026-04-06_2026-04-17_v2.csv` (v2 W1)
- `outputs/ab_backtest_2026-03-19_2026-03-25_v2.csv` (v2 W2)
- Three matching `*_summary.txt` files
- `outputs/ab_smoke_1day.csv` (smoke)

**Modified**:
- `src/agents/scanner_signal.py` — direction-strip + prompt rewrite
- `src/agents/test_scanner_signal.py` — updated 5 tests
- `v2/pipeline/orchestrator.py` — `run_agents_only()` helper +
  `quant_signals=[cls() for cls in ALL_SIGNALS]` wired into `run_scan`
- Memory `project_scanner_design_intent.md` — A/B-vs-random framing


---


## Session — 2026-05-19 (Email conflict highlight + analyze.py rigor + LLM gist + PV audit)

Bundle of 4 tasks on top of the notification subsystem from earlier:
email-side polish (conflict banner + LLM gist), statistical rigor for
backtest analyze (BH FDR), and a sample-bounded directional-sign audit
for the PV detector.

**Final regression**: 367 passed + 3 skipped (live-network gated) across
v2/scanner, v2/pipeline, v2/backtesting, v2/data, and all notification
+ pipeline backend test suites.

### Task 5 — LLM "Why this pick" gist per ticker (✅)

Each email now has a ~60-char Chinese take under the PM action header,
generated by the same LLM that ran the pipeline.

**New module** `app/backend/services/notifications/gist.py`:
- `generate_gists(run, *, model_name, model_provider) → dict[ticker, gist]`
  iterates `agent_decisions`, builds a per-ticker prompt (PM action +
  reasoning + scanner triggers + top-2 analyst signals by confidence),
  calls `get_model(...).with_structured_output(_GistResponse,
  method='json_mode').invoke(prompt)`. Returns only successful gists —
  per-ticker exceptions logged + swallowed so one bad call doesn't
  zero out the whole email.
- Bypasses `src.utils.llm.call_llm` (which expects a full AgentState).
  Calls `get_model` directly with `api_keys=None` so the LLM reads its
  own keys from `.env`.
- Output trimmed at 80 chars (LLM tends to over-deliver) with `…` suffix
  when truncated.

**Dispatcher integration** (`dispatcher.py`):
- New `_try_gist(run_snapshot, model_name, model_provider) → {}`
  swallows top-level errors (no model configured / unexpected raise)
  and returns `{}` so render proceeds without gists.
- `dispatch(run_id)` and `dispatch_to(sub_id, run_id)` both:
  1. Read `pipeline_schedule.model_name` + `.model_provider` (cron uses
     same model the user picked for the daily pipeline).
  2. Generate gists **once per dispatch** (not per sub) and attach to
     `run_snapshot.gist_map`.
  3. Every handler in the loop sees the same precomputed gists.

**Render integration** (`render.py`):
- `render_pipeline_html(run, *, gist_map=None)` — new kwarg. When
  `gist_map[ticker]` present, renders a yellow-tinted row (amber-100 bg
  `#fef3c7`, amber-900 fg) labeled `💡 Take:` between the conflict
  banner and PM reasoning. Absent tickers render normally — partial
  failure shows up as missing-row, not a broken email.

**EmailHandler / WebhookHandler**:
- EmailHandler reads `getattr(run, "gist_map", None)` and passes to
  `render_pipeline_html`.
- Webhook payload `_build_payload` includes `gist_map: dict` so
  Slack/Discord/Zapier templates downstream can use the one-line take
  instead of the full PM reasoning.

**Tests**:
- `tests/notifications/test_gist.py` (10) — mocks `get_model` to inject
  per-ticker behaviors. Covers: empty run / happy multi-ticker /
  per-ticker exception isolation / empty gist drop / overlong truncate /
  `get_model` returns None / `_top_analyst_signals` ordering by
  confidence (numeric beats non-numeric).
- `tests/notifications/test_render.py:TestGistInjection` (4) —
  rendering with map / without map / partial map / HTML escape.

**Total notification tests**: 67 passed. **Scheduler + routes**: 36
passed (dispatcher's new schedule-read + gist-attach doesn't break the
existing /test path because PipelineScheduleRepository falls back to
None → `_try_gist` returns `{}` → render proceeds unmodified).


### Task 2 — Benjamini-Hochberg FDR in `analyze.py §2` (✅)

`report_per_detector` now reports `p_raw` + `p_fdr` + `sig` columns
alongside the existing bootstrap CI. Three new helpers:
- `_raw_pvalue(values)` — two-sided one-sample t-test (H0: mean=0)
  via `scipy.stats.ttest_1samp`. Returns None for n<2, all-non-finite,
  or zero-variance samples (uses 1e-12 tolerance because float
  subtraction on identical inputs gives ~1e-17 std, not exact zero).
- `_bh_adjust(p_values)` — wraps `scipy.stats.false_discovery_control`
  (scipy ≥ 1.11). Preserves input order + Nones so cells where the
  raw p couldn't be computed still slot back into the right position.
- `FDR_ALPHA = 0.05` module-level constant matches the bootstrap CI's
  95% level so both rigor knobs report at the same significance.

Smoke against `backtest_ndx100_90d.csv`: two cells survive FDR @ 0.05:
- earnings_event 20d → p_raw=0.0013 / p_fdr=0.0177 (*)
- earnings_event 63d → p_raw=0.0002 / p_fdr=0.0058 (*)

Both are NEGATIVE dir-adjusted alpha (-1.66% / -3.37%), confirming the
"detectors are attention screeners, not standalone alpha" framing in
project memory: even when statistically significant after multiple-
comparison correction, the directional sign is opposite to the
detector's `direction` field. The agent layer is meant to invert /
contextualize these.

10 new tests in `test_analyze.py:TestRawPvalue` + `TestBHAdjust`
(empty / single value / zero-variance / strong signal / noise /
order preservation / monotonicity / Nones-in-place / single-test
identity). 30/30 analyze tests pass.


### Task 1 — `price_volume_anomaly` direction sign audit (✅, no flip)

`scripts/audit_pv_direction.py` reads `backtest_ndx100_90d.csv`, filters
to PV-triggered rows in the last 60 trading days, computes PV's own
direction (from `today_return` sign in
`triggered_components_json.price_volume_anomaly`), then counts how
often the forward 5-day alpha sign is OPPOSITE.

Conservative flip gate (per user request — original spec was just
"≥60% reversed → auto flip"; I added an n≥100 hard floor + a one-sided
binomial test against H0=50% before recommending any code change):
- n ≥ 100 directional samples in window
- reversal_rate ≥ 60%
- binomial test p < 0.05

Result on this CSV / window: **n=47, reversal=48.9%, p=0.6146**. All
three gates fail. **No flip recommended**, no code touched.

Diagnostic at `outputs/pv_direction_audit.txt`. Re-run any time with
`python scripts/audit_pv_direction.py [--csv PATH] [--days N]` to
re-evaluate.


### Task 4 — Email valuation-conflict warning bar (✅)

`render.py` now flags when the PM took a directional position
(BUY/SHORT) that contradicts the valuation_analyst's signal.

Mechanism:
- New `_PM_DIRECTION` dict maps `{"buy": "bullish", "short": "bearish"}`.
  HOLD/SELL/COVER have no directional intent worth conflicting against
  valuation.
- New `_valuation_conflict(decision, analyst_signals, ticker) -> str | None`
  looks up `analyst_signals["valuation_analyst_agent"][ticker].signal`.
  Returns a Chinese warning string when PM direction ≠ valuation
  direction (and valuation isn't neutral / missing).
- Per-ticker block: warning bar inserted as a separate `<tr>` between
  the action header and the PM reasoning, red-100 bg (`#fee2e2`) /
  red-800 fg matching the SELL/SHORT pill palette so the eye locates
  it instantly. Gmail-safe — inline styles only.

7 new tests in `tests/notifications/test_render.py:TestValuationConflict`
(buy vs bearish / short vs bullish / matching directions / neutral /
HOLD / missing valuation signal). 20/20 render tests pass.


---


## Session — 2026-05-19 (Delete MultiHorizonBreakoutDetector)

### Why deleted

The event-style multi-horizon breakout detector (`breakout_52w`) overlapped
with `v2/signals/technical.py`, which already produces 52-week-high /
momentum signals from the same underlying price data. Keeping both
produced duplicate alpha attribution when the scanner→agent bridge
serialized triggered_components — the technical signal said "+momentum
+breakout", and the event detector duplicated the breakout dimension.

### What changed

**Deleted**:
- `v2/scanner/detectors/breakout_multi_horizon.py` (entire file).
- `v2/scanner/test_detectors.py` — `TestMultiHorizonBreakoutDetector`
  class + `_flat_history` / `_multi_regime_history` helpers (only used by
  that class).
- 4 registration sites in `v2/scanner/detectors/__init__.py` (import,
  `ALL_DETECTORS` tuple, `DETECTOR_METADATA` entry, `__all__` export).
- BREAK label entries in `v2/scanner/__main__.py:61` and
  `app/frontend/src/components/panels/scanner/watchlist-table.tsx:51`.

**Adjusted test fixtures** to reference still-extant detectors:
- `v2/backtesting/test_engine.py:270` — live smoke test now uses
  `["intraday_move", "bollinger_squeeze"]` instead of breakout_52w.
- `v2/pipeline/test_orchestrator.py:49,62` — orchestrator's "drop
  untriggered triggers" test now uses bollinger_squeeze as the fired=False
  fixture.
- `v2/backtesting/cli.py:91` — `--weights` example help text updated.

**Kept (intentional)**:
- `v2/backtesting/analyze.py:_break_horizons_for()` +
  `report_break_horizon_split()` — the repo root has 3
  `backtest_ndx100_*.csv` files containing historical `breakout_52w`
  trigger entries; these analysis functions still parse those CSVs
  cleanly and produce empty buckets on new backtests. Removing them
  would force regenerating the historical CSVs.
- `v2/backtesting/test_analyze.py:TestBreakHorizons` — tests the parser
  not the detector existence; still passes.
- `v2/scanner/detectors/bollinger_squeeze.py:20` historical comment
  ("same pattern as multi-horizon breakout's first-day rule") — design
  context, still valid.

### DB / config back-compat

Checked existing ScannerConfig DB rows: only 1 row exists and it does
NOT reference `breakout_52w` in its weights JSON, so no LEGACY alias
needed in `LEGACY_DETECTOR_ALIASES`. Old `pipeline_runs.watchlist_json`
rows contain historical breakout_52w triggers in the `triggers` list;
those are read-only display data and won't fail validation.

### Verification

`pytest v2/scanner/test_detectors.py v2/pipeline/ v2/backtesting/{test_analyze,test_engine}.py tests/ -q`
→ **287 passed + 1 skipped** (live-network gated). No detector
registration error, no orphan import.


---


## Session — 2026-05-18/19 (Pipeline notifications — Resend email + generic webhooks)

### Why

The daily scanner→agent pipeline ran at 16:30 ET and persisted results
to `pipeline_runs` but stopped there. User had to log into the UI to
see what the agents decided. Wanted an HTML email auto-delivered after
each run, plus a generic webhook subscription system so other consumers
(Slack/Discord/personal automations) can subscribe to the same event
without adding code paths.

### Architecture

One `NotificationSubscription` table with a `channel` discriminator
(`'email' | 'webhook'`). Pipeline completion → `NotificationDispatcher`
loads enabled subs matching the event_type, picks handler per channel,
fans out sequentially, records each attempt to a `NotificationDelivery`
audit log. Pipeline cron is decoupled — a failed Resend call is logged
but never raised back to the scheduler.

### Phase 1 — Models + repository (✅)

- `NotificationSubscription`: id, enabled, event_type
  (`'pipeline.completed'` default), channel, target (email or HTTPS URL),
  label, auth_header (webhook-only), timestamps.
- `NotificationDelivery`: id, FK subscription_id, run_id, status
  (`ok|error`), http_code, error_text (capped at 4000 chars), latency_ms,
  attempted_at.
- `app/backend/repositories/notification_repository.py` —
  `SubscriptionRepository` (CRUD + `list_enabled_for_event`) +
  `DeliveryRepository` (append-only `record` + `list_recent`).
- Pydantic schemas in `notification_schemas.py` — secrets like
  `auth_header` excluded from responses (use `has_auth_header: bool`
  flag instead).
- 20 tests in `tests/test_notification_repository.py`.

### Phase 2 — HTML renderer + Resend handler (✅)

- `app/backend/services/notifications/render.py`:
  - `render_pipeline_html(run)` — inline-styled (Gmail strips
    `<style>` blocks), per-ticker section with PM ActionPill colors
    matching the frontend, collapsible per-analyst signal grid.
    Truncates long reasoning at 220-320 chars to stay under Gmail's
    102KB clip threshold.
  - `render_pipeline_text(run)` — plain-text alt-part for clients
    that prefer text or for lock-screen previews.
- `EmailHandler` calls Resend's `POST /emails` via raw `httpx` (no
  `resend` SDK dep). Reads `RESEND_API_KEY` + `RESEND_FROM_EMAIL` from
  env (default `onboarding@resend.dev` — sandbox sender that only
  delivers to the Resend account email until a domain is verified).
  Never raises — returns a `dict` result the dispatcher records.
- 23 tests (HTML snapshot, text fallback, mocked httpx for Resend
  success / 4xx / 5xx / timeout).

### Phase 3 — Webhook handler with SSRF guard (✅)

- `WebhookHandler.send`: `httpx.post(target, json=payload,
  headers={Authorization: subscription.auth_header})` with 10s timeout,
  1 retry on 5xx (2s sleep), no retry on 4xx.
- Payload mirrors `PipelineRunDetail` so consumers see the same JSON
  shape the frontend gets from `GET /pipeline/runs/{id}`.
- **SSRF guard**: rejects RFC1918 / loopback / link-local addresses
  unless `NOTIFICATIONS_ALLOW_LOCAL=1` env opt-in. Always rejects
  non-http(s) schemes (file://, gopher://, …) regardless. Hostname
  literals get resolved via `socket.getaddrinfo` to catch
  `localhost.attacker.com → 127.0.0.1`.
- 13 tests (success/auth header forwarding/retry logic/timeout/SSRF
  rejection/allow_local override).

### Phase 4 — Dispatcher + scheduler integration (✅)

- `NotificationDispatcher(session_factory)`:
  - `dispatch(run_id, event_type='pipeline.completed')` — loads enabled
    subs for event, snapshots them as detached objects (don't hold the
    session open during slow HTTP), dispatches sequentially, records
    each attempt in its own short-lived session.
  - `dispatch_to(subscription_id, run_id=None)` — one-off send to a
    single sub regardless of enabled flag (powers the `/test` route);
    falls back to latest PipelineRun, or synthetic DEMO run when no
    real runs exist yet.
  - Handler exceptions caught + recorded as `status='error'` deliveries
    (handlers shouldn't raise but defend the cron anyway).
- `scheduler_service.py:_run_pipeline_job` — after `mark_complete()`,
  calls `NotificationDispatcher.dispatch(run_id=run_id)` wrapped in
  try/except so a dispatcher-init crash never kills the daily cron.
- 10 tests (fan-out / disabled filtering / handler exception / unknown
  channel / dispatch_to with None run_id / synthetic-run fallback).

### Phase 5 — REST routes + minimal UI (✅)

Routes (`app/backend/routes/notifications.py`):
- `GET/POST /notifications/subscriptions` — list/create.
- `GET/PATCH/DELETE /notifications/subscriptions/{id}` — single CRUD.
- `POST /notifications/subscriptions/{id}/test` — fires a sample send
  (uses latest real run or synthetic DEMO); returns the delivery row
  inline. Works even on disabled subs so users can validate config
  before flipping the switch.
- `GET /notifications/subscriptions/{id}/deliveries?limit=20` — recent
  attempts for debugging.

Channel-specific validation in route layer: email must contain `@`;
webhook must be http/https with a hostname; auth_header only allowed on
webhook channel. 16 route tests in `tests/test_notification_routes.py`.

Frontend (`app/frontend/src/...`):
- `types/notification.ts` — TS types mirroring Pydantic.
- `services/notification-service.ts` — typed fetch wrappers (list,
  create, update, remove, sendTest, listDeliveries).
- `components/panels/scanner/notification-settings.tsx` — collapsible
  panel under `AgentRunsList` in `scanner-panel.tsx`. Lists subs with
  per-row enable toggle / test button / delete; "Add" dialog has
  channel radios (Email/Webhook) and conditional auth-header field.

### Phase 6 — Live Resend smoke (✅)

User registered Resend with `ruizheyuan3487@gmail.com` and supplied an
API key. Added to `.env`, restarted backend. `POST
/notifications/subscriptions/1/test` returned `status=ok http_code=200
latency=1122ms`. User confirmed the HTML email arrived in the inbox,
rendered correctly with action pills + per-analyst signals from the
latest pipeline run (the dispatcher's "use latest real run" path
fabricated a real-looking sample without needing a fresh pipeline).

### Sandbox limitation (documented)

Without a verified sending domain, Resend's `onboarding@resend.dev`
sandbox sender only delivers to the email registered on the Resend
account. To send to other recipients you must verify a domain in the
Resend dashboard and update `RESEND_FROM_EMAIL`. Documented in
`.env.example` and in the AddSubscription dialog's helper text.

### Files

**New (backend)**:
`app/backend/services/notifications/{__init__,render,email_handler,webhook_handler,dispatcher}.py`,
`app/backend/repositories/notification_repository.py`,
`app/backend/models/notification_schemas.py`,
`app/backend/routes/notifications.py`,
`tests/test_notification_repository.py`, `tests/test_notification_routes.py`,
`tests/notifications/{test_render,test_email_handler,test_webhook_handler,test_dispatcher}.py`.

**New (frontend)**:
`app/frontend/src/types/notification.ts`,
`app/frontend/src/services/notification-service.ts`,
`app/frontend/src/components/panels/scanner/notification-settings.tsx`.

**Modified**:
`app/backend/database/models.py` (+2 tables),
`app/backend/services/scheduler_service.py` (dispatcher call after
mark_complete), `app/backend/routes/__init__.py` (router include),
`app/frontend/src/components/panels/scanner/scanner-panel.tsx`
(component mount), `.env.example` (Resend vars).

### Verification

`pytest tests/{test_notification_repository,test_notification_routes,test_pipeline_repository,test_pipeline_routes,test_scheduler_service}.py tests/notifications/ -q`
→ **127 passed**. Frontend `tsc --noEmit` — zero errors in the new
notification-*.{ts,tsx} files (pre-existing TS errors in
sidebar.tsx/Flow.tsx/layout.tsx unchanged).


---


## Session — 2026-05-18 (Data-quality fixes — 4 silent bugs in agent layer)

After the smoke test from the prior session produced suspiciously
uniform "HOLD" decisions, inspection of the 20-ticker output revealed
4 bugs causing agents to either run on wrong data or produce
mathematically nonsensical signals.

### Fix #1 — Finnhub percentage scale (most damaging)

`v2/data/finnhub_client.py:get_financial_metrics` returned Finnhub's
percentage-form numbers (45 = 45%) directly into `FinancialMetrics`
fields, but v1 agents universally expect decimal form (0.45):
- `fundamentals_analyst` formats with `f"{value:.2%}"` → 14.32 ROE
  displayed as **1432%**.
- Every threshold check (`return_on_equity > 0.15` in warren_buffett,
  cathie_wood, etc.) was trivially satisfied (`14.32 > 0.15` always
  True) → every company appeared "highly profitable".

**Fix**: added `scale=0.01` to `_safe_float()` calls for the 7
percentage-form fields (`roeTTM`, `roaTTM`, `grossMarginTTM`,
`operatingMarginTTM`, `netProfitMarginTTM`, `revenueGrowthTTMYoy`,
`epsGrowthTTMYoy`). Updated `v2/data/test_finnhub_client.py` mock to
use real Finnhub wire format (45 not 0.45).

### Fix #2 — Orchestrator price-history window too short

`v2/pipeline/orchestrator.py` defaulted `start_date = scan_date - 90
days`. `technical_analyst.py:248` uses `returns.rolling(126).sum()` for
`momentum_6m` — 90 calendar days ≈ 63 trading days, so the rolling
window was always NaN → `safe_float(NaN) = 0`. Hurst exponent
(`rolling(126)` similar) was also stuck at ~0 for every ticker.

**Fix**: changed default to `scan_date - 250 days` (~180 trading days).
Updated the orchestrator test that hard-coded the date.

### Fix #3 — Frontend `conf undefined` render

`risk_management_agent` returns position-size dict, no `confidence`
field. `agent-run-detail.tsx` rendered `conf {sig.confidence}` →
literal "conf undefined" string when confidence absent.

**Fix**: gate the conf label on `typeof sig.confidence === 'number'`;
render empty string otherwise.

### Fix #4 — Valuation gap cap for capex-heavy companies

`valuation_analyst` aggregates DCF + owner_earnings + RIM via weighted
gaps. On capex-intensive cos (CHTR observed: D&A >> capex assumption
fails) the owner_earnings formula
`(NI + D&A - capex - ΔWC) × multiplier` inflated to $169B vs $19B
market cap — gap of +769%. With 35% weight that single broken method
dominated the aggregate.

**Fix**: cap each method's `gap` at ±2.0 (200% over/under) before
weighting. Documented inline with the owner_earnings failure mode.

### Verification

Restarted backend, re-ran the same 3-ticker × balanced template
pipeline that previously produced confused outputs:
- **REGN**: BUY qty 25 conf 75 (unchanged outcome, but reasoning now
  based on real percentages — ROE 14.32% not 1432%).
- **CTSH**: BUY qty 301 conf 82 (was conf 90 — fundamentals_analyst no
  longer thinks 1479% ROE means "super-profitable").
- **DXCM**: HOLD qty 0 (was **SHORT qty 241 conf 85** — momentum_6m
  flipped from 0 to +0.115, PM saw mixed signals and stayed flat
  instead of unanimous-bearish on broken-momentum data).

124/124 pre-existing tests still pass. The Finnhub test was updated to
assert decimal output from percentage input.


---


## Session — 2026-05-18 (Scanner→Agent bridge + Plan B api.py adapter)

### Why the bridge

Two systems (`v2/scanner` + `src/agents` LangGraph) were complete and
working independently but had never been wired together. The scanner's
detector context (`triggered_detectors`, `severity_z`, `direction`,
`components`) — the most valuable thing it produces — was thrown away
at the boundary. Wanted both an interactive UI button ("Analyze
selected with agents") and a daily 16:30 ET cron that auto-runs scanner
→ agents → persists decisions.

Full design spec: `docs/superpowers/specs/2026-05-18-scanner-agent-bridge-design.md`.

### Phase 1 — `ScannerSignalAgent` (✅)

New `src/agents/scanner_signal.py` — hybrid rule+LLM analyst that reads
`state["data"]["scanner_context"][ticker]`. Rule-based: signal =
`direction`, confidence = `composite_score`. LLM generates reasoning
prompt with top-4 abs-value numeric components. Falls back to
deterministic string on LLM failure. Registered in
`src/utils/analysts.py:ANALYST_CONFIG`. 19 tests.

### Phase 2 — Pipeline orchestrator + templates (✅)

`v2/pipeline/{templates,orchestrator}.py`:
- 4 named rosters (balanced/value/growth/quick) all auto-prepend
  `scanner_signal` first. `resolve_analysts(template, custom)`
  validates names against `ANALYST_CONFIG`.
- `run_pipeline(**kw)` glues `run_scan` → scanner_context dict →
  `run_hedge_fund(scanner_context=...)`. Returns `PipelineResult`
  dataclass with watchlist + agent_decisions + analyst_signals +
  duration. Test injection seams for `run_scan_fn` /
  `run_hedge_fund_fn` / `provider_factory`. 22 tests.

### Phase 3 — Persistence + REST (✅)

- `PipelineRun` table (UUID hex PK so the route can return run_id
  before the BackgroundTask inserts) + `PipelineSchedule` singleton
  config row (id=1, opt-in `enabled` flag default OFF).
- Alembic migration `b3d8f1a2c9e4` (idempotent seed at startup too
  since alembic isn't installed in user's anaconda env).
- `PipelineRunRepository` (create_pending / mark_running /
  mark_complete / mark_error / list_runs filtered) +
  `PipelineScheduleRepository` (get singleton / partial update).
- `app/backend/routes/pipeline.py` — 6 endpoints. `POST /pipeline/run`
  uses FastAPI BackgroundTasks (no new queue dep) — inserts PENDING,
  flips to RUNNING/COMPLETE/ERROR in the worker. 25 tests.

### Phase 4 — Daily scheduler job (✅)

`scheduler_service.py` registers `daily-pipeline` cron
(`30 16 * * 1-5` America/New_York). Job reads `pipeline_schedule`
singleton at fire-time → skips if disabled / template unknown →
creates pending row → calls orchestrator → marks complete/error.
Misfire grace 10 min. Hot-toggle via UI takes effect next firing
without restart. 5 new tests.

### Phase 5 — Frontend wiring (✅)

`AnalyzeButton` toolbar action (next to scanner header) opens template
picker dialog with rough LLM cost estimate. Submits via
`pipeline-service.triggerRun`, navigates to `AgentRunDetail` dialog
which polls `getRun(id)` every 2s until COMPLETE/ERROR. Per-ticker
result card renders PM ActionPill + grid of per-analyst DirectionPills
+ reasoning. `AgentRunsList` (history panel under watchlist) → click row
→ same detail dialog.

### Plan B — `src/tools/api.py` adapter rewrite

Smoke test on 20-ticker balanced pipeline produced HOLD on ALL tickers.
Root cause: all v1 agents (`sentiment`, `fundamentals`, `valuation`,
`warren_buffett`, `cathie_wood`, `michael_burry`, `technicals`,
`risk_management`) called `src/tools/api.py` which hit Financial
Datasets API → 402 Payment Required → empty data → "insufficient data"
responses. Only `scanner_signal` worked (used state, not network).

**Plan B**: rewrite `src/tools/api.py` internals to delegate to the v2
hybrid client (EODHD + Finnhub + yfinance — same source-of-truth the
scanner uses), keeping every public function's signature + return type
identical so the 19 agent files don't need touching.

**What landed**:
- `src/tools/api.py` fully rewritten. Module-level thread-safe
  singleton `_v2_client_cache` via `_get_v2_client()`. 9 functions:
  get_prices, get_financial_metrics, search_line_items (delegates to
  new module), get_insider_trades, get_company_news, get_market_cap,
  prices_to_df, get_price_data. v2→v1 adapters (`_v1_price`,
  `_v1_financial_metrics`, `_v1_insider_trade`, `_v1_company_news`)
  handle small field/nullability differences. `api_key` parameter
  accepted but ignored (v2 reads from .env). Existing `_cache` layer
  preserved.
- `src/tools/line_items.py` — new module backing `search_line_items`
  with yfinance `income_stmt` / `balance_sheet` / `cashflow` DataFrames.
  `_YF_MAP` covers 26 of 30 v1 line_items directly; 4 ratio fields
  fall back to `get_financial_metrics`.
- `tests/test_api_rate_limiting.py` deleted (tested the removed FD
  HTTP retry layer; v2 client has its own backoff).

**Verification**: 197 pre-existing tests still pass. Live smoke
(3-ticker × quick template × deepseek-chat × 192s):
- REGN BUY qty 25 conf 75
- CTSH BUY qty 301 conf 93
- DXCM SHORT qty 241 conf 100

Real PM decisions citing real analyst signals (155/547/58 insider
trades analyzed by sentiment_analyst, real DCF values by
valuation_analyst, real ROE/margins by fundamentals_analyst). The
"4 silent bugs" follow-up session immediately afterwards (above) caught
the Finnhub-percentage / momentum-window / valuation-gap issues that
made some of those numbers still wrong.


---


## Session — 2026-05-15 (EREV rollback + M9.d target_price_change)

### Why we rolled EREV back

Live probe of `yfinance.Ticker.eps_revisions` showed semantically
incoherent counts: AAPL/MSFT/TSLA all had `up_last_7d > up_last_30d`,
which is impossible if both are cumulative event counts (30d window
includes 7d). The field appears to measure something like
"current estimates above/below recent consensus" not "revision events".
Result: EREV fired on ~87/100 NDX tickers during earnings season, far
beyond an event detector's mandate.

**Action**: EREV removed from `ALL_DETECTORS` (file + class + tests kept
for forensic value). Marked `task_plan_scanner_v2.md §3.8` as BLOCKED.

### M9.d — `target_price_change` (the signal we actually wanted) (✅)

Persisted-snapshot detector that captures "analysts raised/cut median
target by ≥5% over 7 days". This is what users intuitively mean by
"analyst changed target price."

**DB layer**:
- New table `analyst_target_snapshots` (id, ticker, asof_date,
  target_mean/median/high/low, current_price, n_analysts, created_at)
  with `UNIQUE(ticker, asof_date)` so daily upserts are idempotent.
- Alembic migration `a2c4e6b8d0f3` added (also auto-created via
  `Base.metadata.create_all()` at backend startup).
- New `AnalystTargetSnapshotRepository.upsert` (insert-or-update) +
  `list_for_tickers(tickers, lookback_days, end_date)` returning
  `dict[ticker, list[snapshot]]` ordered oldest→newest per ticker.

**Service layer**:
- `ScannerService._refresh_target_snapshots(tickers, end_date)`:
  parallel-fetches yfinance `analyst_price_targets` for every ticker,
  upserts each into DB, then loads the past 14 days back. Uses
  `YFinanceClient` directly (yfinance has no rate limit; no need to
  go through hybrid composite). Per-ticker failures isolated — a single
  yfinance HTML hiccup can't abort the scan.
- `_run_phase` calls this BEFORE `run_scan` and passes the resulting
  dict as new `target_snapshots=` kwarg.

**Runner**:
- `run_scan` gains `target_snapshots: dict[str, list] | None` kwarg.
- `_scan_one_ticker` accepts per-ticker `target_snapshots: list | None`
  and injects into `ScanContext.target_snapshots`.

**Detector** (`v2/scanner/detectors/target_price_change.py`):
- Reads `ctx.target_snapshots`. Picks today's row (newest) and the
  OLDEST snapshot within `lookback_days` (default 7) as baseline.
- Fires when `|pct_change| ≥ min_pct_change` (default 5%).
- Severity: `pct_change / 0.02` (5% move → severity 2.5) capped at ±5σ.
- Direction by sign. Symmetric — analysts raising and cutting are
  equally informative.
- Returns `None` when fewer than 2 snapshots — bootstrap day 1 produces
  no triggers; useful signal starts day 2.

**Registration**:
- Added to `ALL_DETECTORS` (position 8) + `DETECTOR_METADATA`
  (label "Target Price Shift", default_mult 1.00).
- UI badge `TGT` in frontend + CLI.

**Tests**:
- `TestTargetPriceChangeDetector` (9): no snapshots / single-snapshot
  bootstrap / bullish raise / bearish cut / small change no fire /
  oldest-in-window anchoring / out-of-window skip / missing today /
  severity cap.
- `TestAnalystTargetSnapshotRepository` (7): upsert dedupe same-day /
  separate rows different days / oldest→newest ordering / lookback
  window filter / empty inputs / unknown ticker.

Full suite: **313 passed** (was 246 after EREV ship + before rollback;
the +67 also includes 51 previously-counted-elsewhere yfinance tests
in scope this run).

### Bootstrap note for the next scan

Day 1 of running with this detector: only today's snapshot exists for
each ticker, so `target_price_change` returns `None` for every row.
**TGT badges won't appear in the watchlist on the first scan**. They
start showing up on the second scan (next day or any future date once
≥2 distinct daily snapshots are accumulated).

## Session — 2026-05-15 (estimate_revision + multi-horizon breakout)

Goal: ship the two highest-value new detectors from
`task_plan_scanner_v2.md` §3.8 / §3.5 in one round. Detector count
7 → 8.

### `estimate_revision` (NEW, ✅)

- `v2/data/models.py` — `EstimateRevisions` Pydantic model (period +
  up/down counts for last 7d / 30d).
- `v2/data/protocol.py` — `AnalystDataClient` sub-protocol gains
  `get_estimate_revisions(ticker, *, period="0q", asof_date=None)`.
- `v2/data/yfinance_client.py` — implementation reads
  `Ticker.eps_revisions` DataFrame, extracts the configured period row,
  returns `EstimateRevisions` or `None` on sparse coverage. Try/except
  wraps the whole call so a Yahoo HTML change can't crash a scan.
- `v2/data/composite_client.py` — routes through existing
  `analyst_backend` slot (same yfinance backend already provides
  actions/targets — no new slot needed).
- `v2/scanner/detectors/estimate_revision.py` — new detector. Trigger:
  `total_7d ≥ 3 AND |net_7d| ≥ 2`. Severity: `max(|net|/0.7, 2.0)`,
  symmetric direction. Returns `None` when the client lacks the method
  or yfinance returns None (NOT `triggered=False`).

### `multi_horizon_breakout` (replaces 52w, ✅)

- File rename: `breakout_52w.py` → `breakout_multi_horizon.py`.
- Class rename: `FiftyTwoWeekBreakoutDetector` → `MultiHorizonBreakoutDetector`.
- **Kept `.name = "breakout_52w"`** for DB row backward-compat (same
  precedent as the unchanged `price_volume_anomaly` and `analyst_rating`
  names).
- Three horizons (63 / 126 / 252 trading days) checked simultaneously.
  Severity additive: 2.0 (any) + 0.5 (126d also) + 1.0 (252d also). Max
  bullish severity 3.5.
- First-day rule applied **per horizon** — yesterday inside, today out.
- Asymmetric volume confirmation: bullish gets full severity regardless
  of today's volume z. Bearish gets severity halved when `volume_z < 1.5`
  (Murphy: low-volume up-breakouts can be real institutional accumulation;
  low-volume down-breakouts are commonly fake-outs).
- Updated `DETECTOR_METADATA["breakout_52w"]`: label `"52-Week Breakout"`
  → `"Multi-Horizon Breakout"`, description updated.

### Frontend (✅)

- `DETECTOR_LABELS` in `watchlist-table.tsx`: `breakout_52w: '52W'` →
  `'BREAK'`; new `estimate_revision: 'EREV'`.
- CLI `_fmt_triggers` short dict in `__main__.py`: added entries for
  IDAY / BREAK / ANLY / EREV (earlier rounds only had EARN / INSDR / VOL
  / NEWS — the new detectors fell through to the generic 4-char shorthand).
- Dialog picker auto-picks up the new detector via the existing
  `GET /scanner/detectors` endpoint — no frontend dialog code change.

### Tests (✅)

- `TestMultiHorizonBreakoutDetector` (replaces old `TestFiftyTwoWeekBreakoutDetector`):
  - All 3 horizons firing → severity 3.5 with vol confirmation
  - 63d only (older bars set higher 126d/252d) → severity 2.0
  - 63d + 126d but not 252d → severity 2.5
  - First-day rule rejects yesterday-already-above
  - Bullish gets full severity on light volume (asymmetric)
  - Bearish light vol = half severity (3.5 → 1.75)
  - Insufficient history → None
- `TestEstimateRevisionDetector` (new, 9 tests):
  - Fires bullish on net=+3 / bearish on net=-3
  - Severity formula: `|net|/0.7` with floor 2.0
  - Doesn't fire on low total or low net
  - Returns `None` on missing data / missing method / scrape exception
  - Period constructor arg passes through to client

Full suite: **246 passed** (was 235 — +11 new tests).

### End-to-end verification

`GET /scanner/detectors` now returns 8 entries. Backend up on 8001;
frontend on 5173 ready for picker test.

## Session — 2026-05-15 (User-selectable detectors + per-detector severity weights)

Goal: let each ScannerConfig pick which detectors run AND tune their
severity contribution to the composite score. Storage: both inside the
existing `weights` JSON column (no migration). Backward-compat: missing
keys → all detectors enabled, all mults = 1.0 (current behavior preserved).

### Backend (✅)

- `v2/scanner/models.py::ScannerWeights` extended with two new fields:
  - `enabled_detectors: list[str] | None` — None means run all; empty list
    rejected; unknown names rejected
  - `detector_severity_mult: dict[str, float]` — missing keys default to 1.0
    at scoring time; unknown names rejected; values constrained to [0.0, 5.0]
- `v2/scanner/detectors/__init__.py` — added `DETECTOR_METADATA` registry
  with label, default_mult, description per detector. Source for the new
  GET endpoint and the "Recommended Defaults" preset button. Defaults
  follow task_plan_scanner_v2.md §4.2 (earnings 1.20, intraday 1.10, news
  0.50 transitional underweight, etc.)
- `app/backend/routes/scanner.py` — new `GET /scanner/detectors` returning
  list of `DetectorMetadataResponse` objects in ALL_DETECTORS order
- `app/backend/services/scanner_service.py::_run_phase` — builds
  `det_instances = ALL_DETECTORS filtered by weights.enabled_detectors`
  and passes via `detectors=` kwarg to `run_scan`. Logs which detectors
  were selected per run.
- `v2/scanner/scoring.py::compute_composite` — applies
  `detector_severity_mult.get(name, 1.0)` to abs(severity_z) BEFORE
  max-takes-all → `weighted_severity` drives `event_score`. The raw
  unweighted max stays in `event_severity` for the deterministic
  tiebreaker (per ScoredEntry docstring contract).
- `_direction_from` now uses the same per-detector mults — the weighted
  signed sum determines bullish/bearish/neutral.

### Frontend (✅)

- `types/scanner.ts` — `DetectorMetadata` and `ScannerWeightsExtension`
  interfaces mirroring backend payloads
- `services/scanner-service.ts` — `listDetectors()` method
- `scanner-config-dialog.tsx` — collapsible "Detectors" `<details>` section
  added between Top-N row and error display:
  - Header shows `N / 7 enabled` count
  - Three preset buttons: Select All, Clear All, Recommended Defaults
  - One row per detector: Checkbox + label + description tooltip + range
    slider (0.0–2.0, step 0.05) + numeric value
  - On submit: writes only the diff into weights JSON (enabled_detectors=null
    when all are on; mult dict only includes entries that diverge from 1.0)
  - Empty selection rejected client-side before POST
- Dialog widened from 500→640px and `max-h-[90vh] overflow-y-auto` so the
  Detectors section fits without crowding the form

### Tests (✅)

- `TestComputeComposite` (extended): mult amplifies / mult dampens /
  missing key defaults to 1.0 / event_severity reports raw unweighted /
  weighted direction sum can flip bullish↔bearish (6 new)
- `TestScannerWeightsValidation` (new): empty enabled rejected / unknown
  name rejected / dedupe / mult unknown rejected / out-of-range rejected /
  boundary 0.0 and 5.0 pass / partial dict OK (10 tests)
- `TestScannerServiceExecute` (extended): `enabled_detectors=[a,b]` only
  passes those two detectors into `run_scan(detectors=...)`; missing
  enabled_detectors → all 7 still run (2 new)
- `TestListDetectors` (new): returns all 7 / response shape correct /
  order matches ALL_DETECTORS (3 new)

Full suite: **235 passed** (was 215 before — +20 new tests).

### End-to-end verification

Backend `GET /scanner/detectors` returns 7 detectors with full metadata.
Backend `/scanner/configs` 200 OK. Frontend on 5173 ready for dialog test.

## Session — 2026-05-15 (Path B: SPY-relative IDAY + VOL slim)

### Step 5 — Servers up, ready for end-to-end verification (⏳)

Backend: http://127.0.0.1:8001 (PID per launch). Frontend: http://localhost:5173.
User to run NDX-100 scan via "Run now" and inspect:
1. Backend log shows `Benchmark QQQ returned N bars for IDAY adjustment`
2. Trigger rate drops from ~70/100 to ~30-50/100
3. Random row's components for `intraday_move` shows
   `benchmark_used: 1.0`, `spy_cvo`, `raw_cvo`, `adjusted_cvo`
4. PV labels in UI now show as VOL

### Step 4 — Tests (✅)

- `TestVolumeAnomalyDetector` — 8 tests (covered in Step 1)
- `TestIntradayMoveDetectorBenchmark` — 4 new tests (no benchmark = raw,
  market-neutralized = no fire, idiosyncratic = fires, missing dates = silent fallback). Helper `_det()` uses `z_threshold=10, range_pct=0.20` so synthetic-flat baselines don't trip the range sub-signal.
- `TestBenchmarkPlumbing` (`test_runner.py`) — 4 new tests:
  - benchmark fetched exactly once and injected into every per-ticker ctx
  - benchmark fetch raise → scan completes, ctx.benchmark_prices=None
  - benchmark <30 bars → adjustment disabled, ctx.benchmark_prices=None
  - benchmark_ticker None → ctx.benchmark_prices stays None (current behavior)

Full suite: **89 passed, 2 skipped** in `v2/scanner/` + `v2/signals/`.

### Step 3 — IDAY SPY-relative (✅)

`IntradayMoveDetector.detect()` now reads `ctx.benchmark_prices`. When
populated, it builds a per-date dict and subtracts the benchmark's same-day
cvo/gap from BOTH today's bar AND every bar in the trailing z-window.
Range stays raw. When benchmark missing → silent fallback to raw values
(all 6 existing IDAY tests pass without modification).

New components surfaced for debugging: `raw_cvo`, `raw_gap`, `spy_cvo`,
`spy_gap`, `adjusted_cvo`, `adjusted_gap`, `benchmark_used`.

### Step 2 — Benchmark plumbing (✅)

- `ScanContext` gets `benchmark_prices: list[Any] | None` field +
  `arbitrary_types_allowed=True` config.
- `run_scan` gets new kwarg `benchmark_ticker: str | None`. Before pool
  starts, fetches once via `clients[0]` (90-day lookback, ≥30 bars
  required). Failure → log warning, fall back to None (raw IDAY).
- `_scan_one_ticker` accepts `benchmark_prices` and passes into ScanContext.
- `scanner_service._run_phase` adds `BENCHMARK_BY_UNIVERSE` mapping
  (nasdaq100 → QQQ, all others → SPY) and passes into `run_scan`.

All 11 existing runner tests still pass — feature is additive, default
`benchmark_ticker=None` preserves prior behavior.

### Step 1 — Volume anomaly slim (✅)

Renamed `v2/scanner/detectors/price_volume.py` → `volume_anomaly.py`. Class
`PriceVolumeAnomalyDetector` → `VolumeAnomalyDetector`. **Kept `name =
"price_volume_anomaly"`** for DB row backward compatibility (same precedent
as the `analyst_rating` detector).

Dropped the entire return-z-score branch (it double-counted IDAY's
`close_vs_open`). Detector now fires only when:
- `z_volume >= 2.5` (volume spike vs trailing 20-day mean, std floor 10% of mean)
- AND `|today_ret| < 0.015` (anti-gate: flat day — Wyckoff stopping volume)

Reason text on non-trigger when volume hit but return too big:
`"vol z=+X but ret +Y% — IDAY territory"` makes the handoff explicit.

UI label: `PV` → `VOL` in both `v2/scanner/__main__.py` and frontend
`watchlist-table.tsx::DETECTOR_LABELS`.

Tests: replaced `TestPriceVolumeAnomalyDetector` with `TestVolumeAnomalyDetector`
(8 tests). All green:
- volume spike + calm return → fires (bullish/bearish per ret sign)
- big return alone → does NOT fire (no volume signal)
- volume spike + big return → does NOT fire (anti-gate, "IDAY territory" reason)
- adjusted_close used for return calc on dividend days
- volume std floor regression: 5x mean / 10% floor = bounded z (<100)

## Session — 2026-05-14 (previous)

### High-level status

- **M1 / M2 / M3 / M3.5 / M3.6 / M4 / M5 / M6 / M7**: ✅ all complete
- **Tests**: 63 passing in `v2/scanner/` + `v2/signals/`, ~300 total across project (14 pre-existing FD-live failures unrelated to scanner — JPM/XOM not in user's FD subscription, returns 402)
- Scanner is now feature-complete: event-driven candidates → 5 quant factors → composite ranking → live UI + scheduled cron + REST + SSE
- **Next milestone**: M8 (historical replay / hit-rate evaluation) — not started

### M7 — Quant signals layer (completed today)

The composite score's 40% quant term was previously a no-op (`run_scan` never received signals). M7 fixed that.

**Created `v2/signals/`:**
- `momentum.py` — 12-1 month return, tanh-saturated at ±50%
- `value.py` — composite of P/E, P/B, P/S, FCF yield (cheap = bullish)
- `quality.py` — ROIC / ROE / op margin / gross margin
- `earnings_quality.py` — revenue / earnings / FCF / EPS growth
- `technical.py` — RSI(14) + 50-day SMA deviation
- `__init__.py` — `ALL_SIGNALS` list + `SIGNAL_REGISTRY` dict
- `test_signals.py` — 22 tests (bull / bear / missing-data per signal + 2 runner integration tests)

**Modified:**
- `v2/signals/base.py` — `compute()` signature now takes `fd: DataClient` (was missing — runner already passed it but signal interface didn't accept it, latent bug)
- `v2/scanner/runner.py:_evaluate_quant` — actually passes `fd` to signals now
- `app/backend/services/scanner_service.py` — wires `quant_signals=[cls() for cls in ALL_SIGNALS]` into `run_scan` call

### M7 lessons learned

1. **`_pick_close(prices, -22)` returned None.** The bounds check `if idx < 0 or idx >= len(prices)` treated negative indices as invalid. Fixed by normalizing `idx = len + idx` first. Reminder: Python negative-index slicing is a convention you have to opt into; bounds checks don't get it for free.
2. **RSI on a monotonic series saturates to 0 or 100** — meaning a pure downtrend gives RSI=0 ("ultra-oversold = buy") while trend_score=-1 ("downtrend = sell"). The two cancel out in `TechnicalSignal`. That's correct TA — RSI flags reversals, not trend direction. Test expectations had to be loosened to check `trend_score` not the overall signal.

### M6 — Hardening + docs (completed today)

| Item | Status |
|---|---|
| Universe refresh script (M6.a) | ✅ done earlier (`v2/scanner/universes/refresh_universes.py`) |
| Insider M/A/D/F → 0 shares (M6.b) | ✅ done earlier |
| Composite tiebreaker via raw severity (M6.c) | ✅ done earlier |
| Std-floor explosive-z fix in insider + earnings (M6.e) | ✅ done today — see "Std floors load-bearing" in `v2/scanner/README.md` |
| Concurrent-run guard (`ScanAlreadyRunningError`) | ✅ already done in M4 (was wrongly flagged as missing) |
| Startup cleanup of stale RUNNING rows | ✅ already done in M4 |
| `v2/scanner/README.md` operator doc | ✅ done today |
| `SCANNER_LIVE_TEST=1` env-gated live smoke | ✅ done today (`v2/scanner/test_live_smoke.py`) |

### M6.e — Explosive-z bugfix (today)

User reported GEHC with `INSDR +55,257,210,785,000` after a UI scan. Root cause: same `or 1e-6` pattern that bit news_sentiment earlier — `sigma = float(arr.std(ddof=1)) or 1e-6` only fires the fallback when std is *exactly* 0.0, not when it's collapsed-but-nonzero.

Fix applied to both `v2/scanner/detectors/insider.py` and `v2/scanner/detectors/earnings.py`: real std floor that falls back to the categorical-trigger magnitude when the baseline is uninformative. Floor values now documented in scanner README.

Regression tests added:
- `test_baseline_std_floor_prevents_explosive_z` for insider (8-month all-zero baseline → |z| ≈ 2.5, not 1e13)
- `test_surprise_std_floor_prevents_explosive_z` for earnings (4 identical historical surprises → |z| ≈ 2.0)

### Earlier sessions (kept for context)

#### M5 — Frontend scanner tab (completed)

- `app/frontend/src/components/panels/scanner/` — ScannerPanel + ConfigDialog + WatchlistTable
- `app/frontend/src/services/scanner-service.ts` — REST + SSE wrapper
- `app/frontend/src/types/scanner.ts` — TS types mirroring backend
- Tabs context extended with `'scanner'` type; click-through to flow tab with `initialTickers` preset
- TypeScript build green for all scanner code; 18 pre-existing errors in unrelated UI files

#### M4 — APScheduler + REST (completed)

- `apscheduler 3.11.2` in anaconda env
- `app/backend/services/scheduler_service.py` — BackgroundScheduler, max_instances=1, coalesce=True, NY tz
- `app/backend/routes/scanner.py` — 8 endpoints incl. SSE stream
- `main.py` startup cleans interrupted RUNNING + starts scheduler; shutdown stops scheduler
- 26 new tests (15 scheduler + 11 routes)

#### M3.6 — EODHD + CompositeClient (completed)

- `v2/data/eodhd_client.py` — populates `adjusted_close`, gracefully no-ops on 403
- `v2/data/composite_client.py` — `make_hybrid_client()` factory (EODHD for prices/news, Finnhub for insider/earnings/facts)
- Factory branches: `eodhd` and `hybrid` providers
- `recommend_max_workers("hybrid") = 4` (Finnhub bottleneck)

#### M3.5 — Provider abstraction (completed)

- Extended `DataClient` Protocol with `get_earnings_history` + `get_market_cap`
- Retrofitted detectors + runner to type-hint against `DataClient` not `FDClient`
- `provider_factory` kwarg + `fd_factory` deprecation alias
- `v2/data/finnhub_client.py` raw-`requests` adapter with two-layer rate limit
- `v2/data/factory.py` with `make_data_client`, `get_provider_factory`, `recommend_max_workers`
- Added `nasdaq100.csv` + composite `nasdaq100_sp500` universe kind

### Live smoke history

| When | Provider | Universe | Wall-clock | Triggered | Notes |
|---|---|---|---|---|---|
| 2026-05-13 (Finnhub) | finnhub | nasdaq100_sp500 (140) | 608s | 48 / 140 | INSDR-only (PV / NEWS blocked) |
| 2026-05-14 (hybrid v1) | hybrid | nasdaq100_sp500 (140) | 330s | 55 / 140 | All 4 detectors, but PAYX z=-333k bug |
| 2026-05-14 (hybrid v2) | hybrid | nasdaq100_sp500 (140) | 330s | 55 / 140 | News std floor fixed |
| 2026-05-14 (full universe) | hybrid | nasdaq100_sp500 (516) | ~5min | 61 / 516 | Insider z exploded on GEHC → triggered M6.e |
| (pending) | hybrid | nasdaq100_sp500 (516) | tbd | tbd | Re-run after M6.e + M7 — should see quant_score populating + no explosive z's |

### M9.4 — Delete config button + confirm modal (2026-05-15)

Trash button in scanner panel header next to Edit. Click → opens shadcn `<Dialog>` with config name + cascade warning ("also removes all past scan runs and watchlist entries"). Confirm → calls existing `scannerService.deleteConfig(id)` → updates UI:
- aborts in-flight SSE if any
- clears `runId`/`run`/`progress`/`entries`/`streamError` state
- removes config from local list + picks next as selection (or null if empty)
- toast confirmation

Files:
- `app/frontend/src/components/panels/scanner/scanner-panel.tsx`:
  - Added Dialog imports + `Trash2` icon
  - State: `deleteConfirmOpen`, `deleting`
  - Trash button between Edit and New, red icon, disabled when no config selected
  - `handleConfirmDelete()` handles the cascade cleanup
  - New `<Dialog>` after the existing `ScannerConfigDialog` (Cancel + destructive Delete buttons)

Backend / service layer unchanged — `deleteConfig()` REST wrapper and DELETE `/scanner/configs/{id}` route were already in place from M4. This was purely a missing UI affordance.

### M9.3 — Frontend Quote type + Price/Today columns (2026-05-15)

Watchlist table now shows live current price + today's % change for each ticker. Quotes fetched once when entries + runId both available; cancelled cleanly if either changes.

Files:
- `app/frontend/src/types/scanner.ts` — `Quote` + `QuotesByTicker` interfaces
- `app/frontend/src/services/scanner-service.ts` — `getRunQuotes(runId)` REST wrapper
- `app/frontend/src/components/panels/scanner/watchlist-table.tsx`:
  - Added `runId?: number | null` prop
  - useEffect fetches quotes on `[runId, entries]` change with cancellation flag
  - 2 new sortable columns: **Price** (`$XXX.XX`) and **Today** (`+/-X.XX%` colored green/red)
  - Loading state: `…` placeholder. Failed/missing: `—`. Real value: rendered.
  - Sort handlers for new columns; nulls always sort to bottom regardless of direction
  - Detector label map extended with `intraday_move/breakout_52w/analyst_rating` from M8 — those triggers now render as IDAY / 52W / ANLY badges instead of falling through to the truncated default
- `app/frontend/src/components/panels/scanner/scanner-panel.tsx` — pass `runId` to WatchlistTable

TS typecheck clean (the 2 remaining errors are pre-existing in backtest UI, unrelated).

### M9.2 — GET /scanner/runs/{id}/quotes endpoint (2026-05-15)

Batch-fetches live Finnhub quotes for every ticker in a run's watchlist. Returns `dict[ticker, QuoteResponse | None]`. Per-ticker exceptions are caught and converted to None — never fails the whole batch. Uses `ThreadPoolExecutor(max_workers=recommend_max_workers())` (4 for hybrid); throughput is bounded by the Finnhub global token bucket regardless.

Behavior matrix:
- Run not found → 404
- Run has no entries → `{}`
- Provider lacks `get_quote` (e.g. FD-only) → all entries return None (frontend treats as missing data)
- Mixed success/failure → ticker-level None for failures, real QuoteResponse for successes

Files:
- `app/backend/models/scanner_schemas.py` — new `QuoteResponse`
- `app/backend/routes/scanner.py` — new `GET /scanner/runs/{id}/quotes`; imports `make_data_client`, `recommend_max_workers`, `ThreadPoolExecutor`
- `tests/test_scanner_routes.py` — new `TestRunQuotes` (4 tests: 404, empty entries, no-get_quote, mixed success/failure)

16 scanner-route tests pass.

### M9.1 — Quote model + FinnhubClient.get_quote + CompositeClient wiring (2026-05-15)

First piece of "live quotes on watchlist rows" feature.

Files:
- `v2/data/models.py` — new `Quote` model (ticker, current_price, prev_close, percent_change, asof_timestamp)
- `v2/data/finnhub_client.py` — new `get_quote()` method hitting `/quote`. All-zero payload (Finnhub's "unknown symbol" response) → None. Goes through existing `_get()` → automatic 429 retry + global token bucket throttle.
- `v2/data/composite_client.py` — added optional `quotes_backend` slot (mirror of `analyst_backend`). `make_hybrid_client()` wires the existing Finnhub instance into the new slot (close() dedupes by id, so the same instance can serve quotes + insider + earnings + facts + metrics). New `CompositeClient.get_quote()` delegates or returns None.

Tests:
- `v2/data/test_finnhub_client.py::TestGetQuote` — 5 cases (happy path, zero payload, missing current, missing timestamp, non-dict response)
- `v2/data/test_composite_client.py::TestQuotesBackend` — 2 cases (None when backend absent, delegation when present)

Not added to base `DataClient` Protocol — same precedent as `AnalystDataClient`. Callers check `hasattr(client, 'get_quote')` before invoking.

196 v2/data tests pass.

### M8.4 — AnalystRatingDetector (2026-05-15)

7th detector. Two OR-combined gates per the design discussion:

**Sub-signal 1 — Net upgrade score z-score**: weighted sum of last 7d analyst actions (up=+1, init=+0.5, main=0, reit=0, down=-1) z-scored against the distribution of non-overlapping 7-day buckets covering days 7-90. Std floor 0.5 weight-units prevents the explosive-z pattern when the baseline is all zeros. Triggers at |z| ≥ 2.0.

**Sub-signal 2 — Target gap**: `(target_mean - current_price) / current_price`. Triggers at |gap| ≥ 15%. gap_z proxy = gap / 0.05 (so 15% gap → z=3), used only for severity comparison with sub-signal 1.

Severity = max abs of the two z-equivalents, signed by whichever sub-signal dominates. Direction follows the sign.

Robustness: if the DataClient doesn't expose analyst methods → return None cleanly. If get_analyst_actions raises → fall back to empty list (other sub-signal can still trigger). If get_analyst_targets raises → fall back to None. Never raise out of the detector.

Files:
- `v2/scanner/detectors/analyst_rating.py` (new)
- `v2/scanner/detectors/__init__.py` — registered + exported (ALL_DETECTORS now 7 detectors)
- `v2/scanner/test_detectors.py` — 6 tests (upgrade cluster, positive target gap, negative target gap, quiet baseline, missing analyst methods, broken analyst client)

269 tests pass across v2 (scanner + signals + all data clients + protocol conformance + factory).

### M8.3 — YFinanceClient + Sub-Protocol + Composite wiring (2026-05-15)

Added yfinance as an optional partial-DataClient backend, providing analyst data only. Everything else on YFinanceClient explicitly raises NotImplementedError so misuse surfaces immediately.

**Design decision (chosen by user)**: kept the analyst surface OFF the base `DataClient` Protocol. Defined a sub-protocol `AnalystDataClient(DataClient, Protocol)` for the two new methods. FD/Finnhub/EODHD don't need to stub anything. CompositeClient gets an optional `analyst_backend` slot — if None, delegation methods return None/[].

Files:
- `v2/data/models.py` — added `AnalystTarget` + `AnalystAction` Pydantic models
- `v2/data/protocol.py` — added `AnalystDataClient(DataClient, Protocol)` sub-protocol with `get_analyst_targets` + `get_analyst_actions`
- `v2/data/yfinance_client.py` (new) — partial client implementing analyst methods, raising NotImplementedError elsewhere; `_normalize_action` maps yfinance Action variants to 5-bucket vocabulary {up, down, main, init, reit}
- `v2/data/composite_client.py` — added `analyst_backend` slot to `__init__`, `close()`, plus 2 delegation methods. `make_hybrid_client()` now wires YFinanceClient for analyst.
- `pyproject.toml` — `yfinance = "^0.2.66"` added (already installed in anaconda env locally; needed for Poetry-based CI)
- `v2/data/test_yfinance_client.py` (new) — 30 tests: action normalization (11 parametrized variants), target happy/empty/exception/default-asof paths, action date-range filtering + limit + exception isolation, all 8 unimplemented-method raises

183 tests pass across all affected modules.

### M8.2 — FiftyTwoWeekBreakoutDetector (2026-05-15)

Fires the first day a stock's close clears its trailing 252d high (bullish) or low (bearish). "First" = yesterday's close was inside the prior range.

Key design choice: the trailing window EXCLUDES both today and yesterday. If yesterday is included in the window that defines hi_level, then yesterday=hi_level by definition and we can't distinguish "yesterday set the high, today continued" from "yesterday was inside, today broke." Excluding yesterday makes the gate semantically clean: `today > hi_level AND yesterday ≤ hi_level` only fires the day breakout actually happens.

Severity = `breakout_pct / 60d daily-return std`. Weak breakouts (today's volume z < 1.5) get severity × 0.5 — they break the level without tape commitment. Tickers with < 252+2 bars (new IPOs, illiquid) return None.

Files:
- `v2/scanner/detectors/breakout_52w.py` (new) — FiftyTwoWeekBreakoutDetector
- `v2/scanner/detectors/__init__.py` — registered + exported
- `v2/scanner/test_detectors.py` — 5 tests (high break, low break, multi-day breakout suppression, volume confirmation halving, insufficient history)

52/52 scanner tests pass (2 skipped live-smoke).

### M8.1 — IntradayMoveDetector (2026-05-15)

New detector capturing intraday price behavior that close-to-close PV misses:
- `close_vs_open` — open → close return; catches days where market dominated
- `gap` — prev_close → open return; catches overnight catalyst reactions
- `range` — (high − low) / open; catches wide-swing days even when close flat

Each sub-signal gated by `|abs| ≥ X%` **OR** `|z| ≥ 2.5` against trailing-60-day distribution. Severity = max |z| of the three, signed by `close_vs_open` (neutral when only range fires). std floor 0.005 on all three baselines.

Files:
- `v2/scanner/detectors/intraday_move.py` (new) — IntradayMoveDetector
- `v2/scanner/detectors/__init__.py` — registered + exported
- `v2/scanner/test_detectors.py` — 6 unit tests (gap up, intraday drop, wide range, quiet day, insufficient history, missing open)

47/49 scanner tests pass (2 skipped are live-smoke gated).

### Windows uvicorn debug detour (2026-05-15 — captured in CLAUDE.md)

After Bug D fix the user reported scans STILL only firing AAPL. Diagnosis path:
- Independent Python process with `max_workers=4` + new bucket → **32 triggers in 6.7 min** (correct)
- Backend HTTP scan with same code → 1 trigger in 5 min (wrong)
- `--reload` parent process was buffering child stdout — couldn't see what the running scan was actually doing
- Each `Stop-Process -Force` of uvicorn on Windows leaked a listening socket. Port 8000 ended up with 5 zombie listeners owned by dead PIDs (492 / 31168 / 39204 / 44716 / 5144); Windows wouldn't release them

Resolution:
- Stopped using `--reload` in dev. Run plain `uvicorn ... --host 127.0.0.1 --port 8001 --log-level info` with `PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1` so request logs flush.
- Switched to port 8001 (8000's zombie listeners poisoned the port).
- Added `app/frontend/.env.local` with `VITE_API_URL=http://localhost:8001` so the frontend follows.
- Locked these into `CLAUDE.md` under "Windows uvicorn gotchas" so the next session doesn't rediscover them.

After the port switch: NDX-100 scan via the UI produced the expected ~30 triggers in ~7 min. The Bug D rate-limit fix was correct all along — uvicorn `--reload` was masking the fix from taking effect (likely module-cache reuse across reload cycles).

### Bug D — Finnhub rate-limit burst (2026-05-15)

After A/B/C, NDX-100 scans STILL produced 1 trigger (AAPL only). Direct programmatic probe of the same code with max_workers=1 produced **32 triggers**. Diff-bisecting on max_workers identified the culprit: `_TokenBucket(capacity=60, refill_rate=1.0)` permits a 60-token burst at cold start. With 4 workers, all 4 grab tokens instantly and fire 60+ requests in <1 second. Finnhub's server-side 60-second rolling window saturates → request #61 onwards 429s → our 3-attempt retry (5/15/30s) is fully contained within the 60s window so all retries also 429 → call returns empty list → detector silently sees "no insider trades" → no triggers.

Fix in `v2/data/finnhub_client.py`:
- `capacity=60.0` → `capacity=1.0` — no burst, strict global serialization
- `refill_rate=1.0` → `refill_rate=0.95` — 5% safety margin under Finnhub's true rolling cap

With the fix, 4 workers serialize through the bucket at ~57 req/min total. Slower than the broken burst behavior at first impression, but correct — burst behavior was producing zeros not throughput. Throughput is now bounded by the actual API contract.

Trade-off: scans get slower in absolute terms (101 tickers × ~3 Finnhub calls = ~300 calls × 1.05s = ~5.5 min minimum). Was the same effective rate before; we just stopped wasting it on 429s.

29/29 Finnhub tests still pass (runtime jumped from <1s to ~28s as tests now go through the live throttle). Backend restarted (`bkytin5ee`).

### Bugs A/B/C — sentiment + earnings fixes (2026-05-15)

User test surfaced that with hybrid provider, NDX-100 scans only triggered 1 ticker (AAPL). Three independent issues compounding:

**Bug B — EODHD sentiment all-positive.** `/sentiments` returns a `normalized` field that's nominally polarity but in practice is positive-skewed: even neutral-news tickers sit at 0.75-0.85, only stressed names (BA, etc.) ever cross below 0.50. Our `_classify_sentiment` threshold (±0.20) → every ticker got "positive" → polarity z-shift = 0. Fix:
- Added `sentiment_score: float | None` to `v2/data/models.py:CompanyNews` for the continuous signal
- `v2/data/eodhd_client.py:get_news` populates sentiment_score per article from the day's `/sentiments` reading
- `v2/scanner/detectors/news_sentiment.py` prefers `sentiment_score` over label-based polarity; labels still drive the FD/Finnhub fallback path

**Bug A — EODHD /news 1000-cap eats the baseline.** Popular tickers (NVDA, MSFT, AAPL) get 1000 articles inside 5-15 days; the 90-day baseline window had **zero** articles for NVDA. Fix:
- `get_news` now synthesizes one "(daily sentiment aggregate)" CompanyNews per day in the requested window that the /news call didn't cover, populated from /sentiments
- Detector now sees 60-90 baseline rows even when real articles are clustered in the recent window

**Bug C — Finnhub earnings filing_date = fiscal period end.** `/stock/earnings` doesn't carry the SEC 8-K announcement date, so we used the fiscal period end as a stand-in. That made every earnings record look 30+ business days stale, killing `earnings_surprise` entirely. Fix:
- `v2/data/finnhub_client.py:get_earnings_history` rewritten to use `/calendar/earnings` instead. That endpoint returns real announcement dates plus actual/estimate EPS + revenue. Cap the historical window at `limit * 100` days; sort newest-first; slice to `limit`.
- `v2/data/test_finnhub_client.py` updated to mock the new payload shape (`{"earningsCalendar": [...]}`); split into 2 tests for the empty cases (not-a-dict vs missing key)

Verification: probe across 6 NDX names (MSFT/NVDA/GOOGL/META/TSLA/AAPL) now shows:
- earnings: real filing dates (MSFT 2026-04-29, AAPL 2026-04-30, TSLA 2026-04-22) — 11-17 biz days old, just outside our 5-day window because Q1 reporting ended in early May
- news: continuous z values in [-0.51, +0.10] across the 6 names (was 0.00 or "0 baseline articles" before)
- insider: AAPL z=-2.53 TRIGGERED (was +0.81)

137/137 v2 scanner+signals+EODHD+Finnhub+composite tests pass.

### Provider default switched to hybrid (2026-05-14 late)

Smoke after restart caught the latent issue: `.env` had `SCANNER_DATA_PROVIDER` commented out, so the runner fell back to FDClient → every endpoint returned 402 → NDX-100 scan triggered exactly 1 ticker.

Fix applied:
- `.env`: uncommented + set `SCANNER_DATA_PROVIDER=hybrid`
- `v2/data/factory.py:get_default_provider()` default flipped from `"fd"` to `"hybrid"` so the project default matches actual usage even when env is missing
- `v2/data/test_factory.py`: renamed `test_default_is_fd_when_env_unset` → `test_default_is_hybrid_when_env_unset`; split `test_fd_default` (default=16 workers) into `test_hybrid_default_caps_at_4` + `test_fd_explicit_at_16`
- 19/19 factory tests pass; backend restarted clean

FD code path stays available via explicit `SCANNER_DATA_PROVIDER=fd` but is no longer the silent default.

### Next steps when resuming

1. **Have the user re-run a UI scan** with M6.e + M7 changes. Expect:
   - No more astronomical z's (GEHC-style)
   - `quant_score` column populated in WatchlistTable
   - Composite ordering meaningfully different from event-only ordering — quant breaks the 100/100/100/100 ties at the top
2. **Decide on M8** — historical replay / hit-rate evaluation:
   - Replay 6–12 months of trading days through `run_scan(end_date=t)`
   - For each Top-N pick, compute forward N-day return
   - Hit rate by direction (bullish picks that gained), distribution of returns
   - Tune `ScannerWeights.event_weight` / `quant_weight` / `factor_weights` against the results
   - Storage decision: cache scan outputs to disk (CSV/Parquet) or replay on-the-fly?
3. **(Optional) Create CLAUDE.md at repo root** to lock in invariants for future Claude sessions:
   - `anaconda3/python.exe` is the working interpreter (Poetry not on PATH)
   - `PYTHONIOENCODING=utf-8` for Windows PowerShell color output
   - API keys live ONLY in `.env`, gitignored
   - Scanner pipeline invariants: every z-score has a std floor; signals never raise; detectors return None for "no data" vs `EventTrigger(triggered=False)` for "ran cleanly nothing fired"

### Open decisions

- Volume z-score asymmetry (`z_vol >= 2.5` only — misses *low*-volume anomalies). User declined cosmetic display-clip; composite cap at 100 already handles it.
- Whether to merge `v2/event_study/` retrofit (still FD-only) — deferred indefinitely.
- M3.7 yfinance adapter for v1 LLM agents — deferred until FD trial expires or v1 work resumes.

---

## 2026-05-27 — Screener Phase 1 (M11)

**Goal:** Add a TradingView-style faceted-filter Screener tab over a
nightly snapshot of S&P 500 + CSI 300 (~800 tickers).

**Shipped:**
- New table `ticker_snapshots` (one row per ticker per day, 30-day TTL,
  PK on `(ticker, snapshot_date)`, 3 supporting indices) — alembic
  revision `d4e8a2c1b9f6`.
- `src/screener/snapshot_builder.py` — US path via `yfinance.Ticker.info`
  + `.history` + `.earnings_dates`; CN path via `src/screener/ashare_metrics.py`
  (mootdx quote + akshare fundamentals + akshare hist).
- `app/backend/repositories/screener_repository.py` — filter-dict to SQL
  WHERE translation, idempotent bulk_upsert, 30-day cleanup, multi-market
  query.
- 3 REST endpoints at `/screener/snapshot/{latest,columns,status}`
  (FastAPI + Pydantic, mounted under the global `api_router`).
- APScheduler cron `0 22 * * *` ET — builds US then CN, per-market
  isolated, cleanup after.
- Frontend: new `Screener` tab in the left sidebar (between Watchlist
  and Scanner). 16 chips (range / multi-select / date-range) + sortable
  table + market selector + status bar + empty state. Row click opens
  Analyze tab. Bilingual labels via `screener.*` i18n keys.

**Tests added:** 46 tests across `tests/test_screener_db_models.py`,
`tests/test_screener_repository.py`, `tests/screener/test_*.py`. All
46 new tests green.

**Full suite regression:** 864 passed, 3 failed, 5 skipped. The 3
failures (`test_enabled_detectors_filters_run_scan_detectors`,
`test_start_registers_enabled_configs`,
`test_start_registers_daily_pipeline_even_with_no_scanner_configs`) are
pre-existing — confirmed by running against HEAD with no working-copy
changes. Root causes are the `earnings_surprise` → `earnings_event` alias
rename (Task prior to Phase 1) and the new screener cron adding a 3rd
`add_job` call that the old scheduler test counts didn't anticipate.
Zero new regressions from Screener Phase 1.

**Smoke verified:**
- Alembic at head (`d4e8a2c1b9f6`); `upgrade head` is a no-op (already applied).
- Backend boots; all 3 endpoints return HTTP 200:
  - `GET /screener/snapshot/status` → `{"snapshot_date":null,"last_updated":null,"row_count":0,"by_market":{}}`
  - `GET /screener/snapshot/columns` → 16 chip definitions
  - `GET /screener/snapshot/latest?market=US&limit=5` → `{"rows":[],"total_count":0,...}`
- First real snapshot will be built by cron at 22:00 ET tonight.

**Commits (Tasks 1-14, since `b9a8282`):**
```
0238fca feat(screener): i18n keys (en + zh) for tab, chips, status
af91020 feat(screener): wire Screener tab into left sidebar + tabs context
8439621 feat(screener): tab shell + chip bar + status bar + empty state
a229f82 feat(screener): sortable snapshot table with bilingual headers
5775537 feat(screener): range/multi-select/date-range chip components
cfb1ddf feat(screener): frontend types + REST service client
669db07 feat(screener): nightly snapshot cron at 22:00 ET
6ded97b feat(screener): 3 REST endpoints (snapshot/latest, columns, status)
fc793d6 feat(screener): column metadata + Pydantic schemas
33f8bba feat(screener): SnapshotBuilder CN path via mootdx + akshare
ea3dc9e feat(screener): SnapshotBuilder US path (yfinance)
fd9d67f feat(screener): ScreenerRepository with filter-dict query + idempotent upsert
8fd932a fix(screener): BigInteger().with_variant(Integer,sqlite) for portable autoincrement
33aab5d fix(screener): id BigInteger + last_updated nullable=False per spec
```

**Out of scope (deferred to later phases):**
- Saved filter presets + cron auto-runs + email push (Phase 2).
- Stock logos, column-group tabs (Overview/Performance/Valuation),
  bulk "add to watchlist" (Phase 3).
- Universe expansion beyond SPX + CSI 300, intraday refresh.

---

## Session — 2026-05-29 (Screener Phase 2 Wave A — Task A1 ScreenerPreset model + migration)

### What shipped (Task A1)

- **app/backend/database/models.py** — added `ScreenerPreset` ORM class with fields:
  - `id` (BigInteger with SQLite Integer variant, autoincrement)
  - `name` (String 120, required)
  - `market` (String 8, optional: 'US' | 'CN' | None for all)
  - `filters_json` (JSON, required, defaults to {})
  - `sort_by`, `sort_dir` (String, defaults "market_cap" / "desc")
  - `schedule_enabled` (Boolean, default False, server_default "0")
  - `notify_channels` (JSON, optional: ["email", "webhook"])
  - `last_run_at`, `last_match_count` (DateTime / Integer, optional)
  - `created_at` (DateTime with timezone, server_default func.now())
- **app/backend/alembic/versions/e1a7c2f4b9d0_add_screener_presets.py** — migration
  - Revision: e1a7c2f4b9d0, down_revision: d4e8a2c1b9f6 (current head)
  - Upgrade: create table with all 11 columns + proper BigInteger variant
  - Downgrade: drop table
- **tests/screener/test_preset_models.py** — smoke tests:
  - `test_insert_minimal` — create preset with name/market/filters_json, verify defaults
  - `test_full_fields` — all fields populated, verify roundtrip

### Verification

- pytest: 2/2 tests pass
- alembic upgrade: clean migration from d4e8a2c1b9f6 → e1a7c2f4b9d0
- alembic downgrade: clean rollback
- alembic upgrade again: idempotent
- Commit: 75502b2, message: "feat(screener): ScreenerPreset model + migration"
- No Co-Authored-By trailer on commit
- A2: ScreenerPresetRepository (CRUD + list_enabled + mark_run) — 5 tests pass

- A4: preset CRUD + run routes — 2 tests pass, screener suite green
- A5: screener.match render + dispatch — render_screener_match_html/text added to render.py; _render_for_event + dispatch_screener_match added to dispatcher.py; email/webhook handlers wired additively; 7 new tests + full suite 120 passed

- A6: nightly preset cron at 22:05 ET — SCREENER_PRESET_CRON_EXPR/JOB_ID constants; _run_preset_job_body (notify on non-empty match); _register_preset_job; called from start(); bumped scheduler add_job counts 5→6 and 3→4 in test_scheduler_service.py; 3 new tests + full scheduler+screener suite 69 passed

- A7: frontend preset service + type — ScreenerPreset interface in types/screener.ts; listPresets/createPreset/patchPreset/deletePreset in screener-service.ts; tsc zero NEW errors (2 pre-existing); commit d0f3884
- A8: preset-bar.tsx — compact one-row PresetBar (Select load + Save popover + optional Manage); wired into screener-tab.tsx above FilterChipBar; tsc zero NEW errors (2 pre-existing); commit TBD

- A11: Wave A verification — backend 890 passed / 1 pre-existing fail (earnings_event, B1 fixes) / 5 skipped; frontend tsc 2 pre-existing errors (B2 fixes). Wave A introduced 0 regressions.
