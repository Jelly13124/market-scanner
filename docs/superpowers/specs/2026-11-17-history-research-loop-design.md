# Historical data and research loop design

Status: proposed design for user approval; not an implementation claim.
Date: 2026-11-17

## Intent and confirmed decisions

Deliver one traceable local workflow: Screener selection -> frozen stock universe -> Scanner evidence -> Analyze explanation -> user-confirmed strategy -> Backtest -> links back to its sources. Users should be able to explain why an instrument was selected, why a signal fired, what information informed the report, and exactly which rules and data produced a backtest.

Confirmed with the user:

- Local deployment without a rented server; PostgreSQL remains required. MongoDB remains optional. Ordinary runs fetch online data when usable history is missing.
- US equities, daily bars, fixed user-selected universes initially; default backtest window three years with editable dates.
- Separate historical market values from observations actually available to this application at a particular time. Backfilled prices do not establish historical financial/news availability.
- Preserve workflow relationships in PostgreSQL even without MongoDB. Persist large historical inputs in MongoDB when available; declare exact replay capability only when complete inputs are durably available.
- Share relative volume, closing-range breakout, and SPY-relative strength rules between scanning and backtesting; support AND/OR, initially long-only.
- AI explains evidence and proposes structured strategy drafts; users confirm trading parameters before execution. No historical daily AI trading loop or automatic optimization.
- Strict original-data replay never fetches online. Fetch-and-rerun produces a new record. AI output is archived; regenerating it is a new analysis, not deterministic replay.
- One position per ticker, no pyramiding, leverage, or shorting. Shared portfolio cash. After exit, only a newly evaluated qualifying signal can cause re-entry.
- Evaluate entries/exits at close, execute at next available instrument session open. Exit conditions are OR: holding period, close-based stop/profit, or selected rule conditions.
- Rank competing entries by signal-time Scanner score descending then ticker ascending. Execute exits before entries. Insufficient cash means skip, not implicit financing or position resizing.
- Backfill on demand; update tracked tickers and needed benchmarks while the application runs, and catch up after restart. No collection while the host is off.
- Develop with explicit red-green-refactor TDD and no speculative general-purpose workflow engine.

## Approaches

A. Extend existing modules (selected): add immutable snapshots and links, preserve complete backtest inputs, extract a small shared rule evaluator, and reuse existing services and simulation. Incremental delivery with bounded regressions.

B. Replace modules with a universal workflow engine: flexible but changes execution, persistence, and UI together without a first-version need.

C. Build a full historical market platform first: appropriate for point-in-time dynamic screening, but requires historical universe and availability data beyond this version's sources and scope.

The user selected A. Existing legacy strategies and detector identifiers must remain readable; new semantics are explicitly versioned rather than silently applied to old results.

## Current implementation and gaps

Existing code includes optional Mongo storage (`src/storage/mongo.py`), cache/history and revisioned prices (`v2/data/cached_client.py`), full-universe scan history (`src/storage/history.py`), Analyze datasets and checkpoints (`src/storage/analysis.py`), a LangGraph analysis workflow, and a separate Lab backtest engine.

Screener already adds selections to Watchlists; Scanner already resolves Watchlists. Automatic analysis has partial source-result linkage. Manual Scanner -> Analyze currently passes only ticker/market. Saving selections does not preserve original filters. Backtest loading drops data provenance and does not freeze its resolved stock list. Scanner rules and Lab blocks are separate implementations. Existing dataset IDs alone do not prove reconstructible inputs. These are code observations, not proof that real Mongo storage has passed acceptance.

## Ownership and persisted objects

Extend existing models/repositories; exact table and module names below are conceptual and may be adapted by the implementer.

| Object | Durable contents | Storage |
| --- | --- | --- |
| Universe snapshot | Owner, resolved ticker list, market, selection time, filter definition/version, Screener snapshot date/ID, origin Watchlist ID when applicable | PostgreSQL |
| Scan execution/result | Owner, immutable universe reference, selected detector definitions/versions/parameters, execution time, per-ticker statuses, triggering values and data dates | PostgreSQL for required links/evidence; optional Mongo full history |
| Analysis run/report | Owner, source scan result reference and copied trigger context, analysis input timestamp, report and draft links | Existing SQL reports plus optional Mongo evidence/checkpoints |
| Strategy revision | Owner, immutable validated strategy JSON, rules/version, universe snapshot, originating report/scan references and confirmation time | PostgreSQL |
| Backtest run | Owner, strategy revision, exact universe, effective dates, costs, engine/rule versions, dataset manifest, completeness, result and original-run reference for replay | PostgreSQL |
| Frozen input payload | Exact ordered OHLCV/adjusted values, benchmark, actions where needed, instrument/session metadata consumed by engine; content hash | Optional Mongo, referenced by SQL manifest |

All user-owned links are resolved with owner checks, including links submitted directly to APIs. Market price observations may be shared; user reports, selections and configurations are private. Keys never enter snapshots, reports, manifests or checkpoints.

Snapshot a universe when the user saves a Screener selection. On each scan, freeze the actual resolved list again so later Watchlist edits cannot rewrite history. A standalone Watchlist scan has Watchlist provenance without inventing Screener filters. Retain originating snapshots when a mutable Watchlist/config is edited or removed; deleting that object does not cascade-delete run evidence. Existing legacy records show unavailable provenance honestly.

A missing Mongo database must not create a dangling required SQL foreign key or prevent standard execution. Record persistence state explicitly. Durable payload publication must precede marking a run replayable; partial writes cannot yield a replayable badge. A content hash verifies inputs but does not substitute for those inputs. Existing artifacts can remain readable if their linked mutable configurations disappear.

## Market data and time semantics

Use the existing provider/cache abstraction and Yahoo/Finnhub adapters. Historical daily signal calculations use adjusted closes; trade fills and corporate actions must use a coherent, documented price basis (see execution section). Live quotes continue to bypass historical caching.

Preserve market/session date, provider, retrieval/observation timestamp, revision/content identity and query coverage. Current financial metrics and later-revised observations must never be presented as known at an earlier historical decision date. First-version backtests use price/volume rules only and are labeled current-universe retrospective studies, with selection/survivorship limitations. Strict historical fundamental screening and historical index membership are out of scope.

Normal execution: resolve fixed universe -> obtain required bars plus rule warm-up and SPY -> validate inputs -> attempt persistence -> execute -> publish results and completeness. Insufficient warm-up means no-data, not a false rule. No forward-filled executable prices or invented zero-volume sessions. Missing ticker data is reported; results explicitly list included/excluded tickers and reasons.

Replay: read manifest and exact payload -> verify completeness/hash and supported engine/rule version -> execute without provider access. Missing data/version support fails with a clear reason and an alternative new online run. Keep original record immutable. Exact input reproduction is promised only for supported stored versions, not arbitrary future engine versions.

## Shared rule contract

Extract pure calculations from the three daily detectors; adapters obtain data, while evaluators receive bounded bars as of a session and return no-data / not-triggered / triggered, direction, severity, values, and actual data date. Both Scanner and Backtest call the same evaluator with the same parameters. No provider calls inside rules.

Defaults retain current meanings:

- Relative volume: latest volume / mean of prior 20 volumes >= 2; current bar excluded; direction from adjusted daily return.
- Closing breakout: adjusted close strictly outside prior 20 closing values, excluding current bar; equality is not a breakout.
- Relative strength: 20-session adjusted return spread against SPY >= +5 or <= -5 percentage points, using matching sessions.

Conditions include desired direction explicitly. A flat volume event may satisfy a neutral/any-direction volume condition but cannot silently act as a bullish signal. V1 groups are flat AND or OR lists, not nested arbitrary expressions. Use three-valued logic: AND is false if any operand is false, otherwise no-data if any is unknown; OR is true if any is true, otherwise no-data if any is unknown. Preserve operand outcomes and incomplete-evidence flags.

For entry ranking reuse existing weighted event-score semantics on satisfied entry conditions, with saved multipliers and deterministic ticker tie-break. No fundamental quant overlay in this new price-rule strategy profile. Existing Scanner configurations keep their prior behavior unless users opt into a rule group. Do not reinterpret retired detector IDs or legacy Lab blocks.

## Portfolio execution contract

New loop-created strategies use an explicit execution profile/version. Existing strategies keep legacy behavior unless deliberately converted to a new revision.

Implementation choices proposed for this version (not additional user requirements):

- Long-only fractional shares, fixed percentage of pre-entry portfolio equity per new position, bounded by max positions. Display and save initial capital, percentage, position limit, commission and slippage before confirmation. No hidden numeric trading defaults in execution.
- Size at execution open using available cash and current opens for held instruments where available, otherwise their most recent known close. Use one pre-entry equity valuation for the batch; no current-day closing marks in morning sizing. Reserve entry commission; skip an unaffordable target allocation and record why.
- Slippage is adverse on entry and exit; commission applies on both sides. Same-day completed exits free cash for entries. A ticker exited that morning cannot reuse an old pending entry; it may qualify again at that day's close.
- Holding count starts with the entry session as day one. On the Nth held session's close, a time exit queues for its next available open. Close-based stop/profit compares raw close with split-adjusted entry basis; fees are included in reported net P&L, not in trigger thresholds. Multiple exit reasons are recorded, with one sell order.
- Adjust share counts and cost basis for splits and credit cash dividends to holders entitled before the ex-date session; do not also book adjusted-close total returns as cash. Store corporate actions consumed by the engine. If required action data cannot be obtained reliably, flag the affected test as unsupported rather than fabricate economic returns. Add split/dividend regression cases before enabling the profile.
- If a scheduled execution session lacks a valid open, retain a pending order until the next supplied valid session within the run; disclose delayed fills. End-of-window pending orders expire; open holdings are marked at last available close and reported separately, without inventing liquidation trades. Do not claim realistic execution for unmodeled delistings/suspensions.
- Rule warm-up is loaded before the evaluation window without generating trades. Preserve existing IS/OOS reporting with separate simulations initialized in cash, warm-up allowed from preceding prices, no earlier holdings carried over. Benchmarks match each reported evaluation window.

## Analyze integration and user flow

1. Screener: save selected tickers with filters/time and optionally create Scanner configuration.
2. Scanner: show trigger evidence and actual bar date; Analyze action sends an owner-validated SQL result reference. Backend reconstructs trigger context, rather than trusting arbitrary UI metrics.
3. Analyze: display source signal evidence separately from newly fetched market evidence. Report remains a research artifact with limitations. Preserve user-selected sections/personas/rounds and existing opt-in auto-analysis behavior.
4. Create strategy: seed a structured draft from linked Scanner rules; AI may suggest supported variations, with assumptions visible. Require explicit user confirmation of dates, entry/exit, sizing, costs and universe. Reject unsupported executable blocks instead of approximating narrative opinions.
5. Backtest: show strategy, included universe, dates, costs, data completeness, metrics/trades and source links. Expose distinct Replay original data and Fetch latest and rerun actions, with replay disabled when unavailable.
6. Report/scan detail: show linked strategy revisions and backtest runs; a newer result never overwrites the meaning of an older report.

No automatic feedback loop changes strategy rules based on attractive results. Record parameter revisions; do not imply repeated tuning is out-of-sample validation. Existing Analyze signal-forward-return studies remain distinctly labeled and must not be confused with portfolio backtests.

## Local historical maintenance

Reuse the application's scheduler and worker conventions. Track the union of user Watchlists and enabled scan universes plus benchmarks; on-demand backtests can fetch other explicitly requested instruments. Fetch session gaps and refresh a bounded recent tail for provider corrections. Keep revisions needed by frozen runs. Use trading calendars for coverage, and do not treat provider errors as successful coverage or every empty response as a holiday.

Use one local maintenance execution at a time; no distributed lease infrastructure in this version. Persist progress per instrument/window, resume unfinished windows after restart, and use idempotent writes. An initial manual update and visible last-success/error state are sufficient controls. Periodic maintenance needs Mongo enabled to retain market history; otherwise skip proactive historical storage work while ordinary requests remain online-capable. User-owned Finnhub enrichment continues to require that user's saved key; shared daily maintenance uses Yahoo data.

## Delivery slices and TDD acceptance

Each slice: write a behavior test, observe the intended assertion failure, implement minimum behavior, run relevant regressions, refactor only while green. Read the invoked TDD skill's writing-good-tests.md before writing tests. Exercise actual rule/domain/repository code; mock external market/model transport only where necessary. No paid model calls in the test suite.

1. SQL provenance and navigation: saving a selection captures filters/tickers; later edits do not alter past runs; cross-owner references fail; manual analysis receives real triggering evidence; no-Mongo operation preserves links.
2. Dataset freezing/replay: manifest lists exact consumed inputs; failed persistence never yields replayable status; original replay makes zero external calls and reproduces deterministic outputs; updated provider data affects only new runs.
3. Shared rules: Scanner and Backtest agree for identical data/parameters; test excluded-current-bar baselines, adjusted closes, SPY date alignment, warm-up, direction filtering and three-valued groups.
4. Execution and strategy confirmation: enforce supported draft schema and explicit confirmation; next-open fills, no lookahead, deterministic ranking, single positions, insufficient cash, exit-before-entry, corporate actions, fees, pending expiry and IS/OOS boundaries.
5. Maintenance and end-to-end: repeated updates do not duplicate observations; restart resumes gaps; provider failures remain incomplete; real isolated PostgreSQL/Mongo integration and no-Mongo smoke verify the full click-to-result path.

Frontend behavior changes need tests for draft confirmation, provenance propagation and replay availability, plus build/lint and browser verification. Run the project's full test command before claiming completion, with test credentials/network configuration controlled so it cannot consume real paid keys or mutate user databases. Report failures and environmental blockers by name rather than hiding them behind targeted green tests. Local schema upgrades require a backup before migrations; use dedicated test databases for integration. Do not promise that all current tests pass before establishing baseline.

## Out of scope and builder discretion

Out of scope: full-market historical dynamic screening, historical fundamental/news trading rules, intraday fills, shorting/leverage/pyramiding, paper/live trading, distributed queues, arbitrary workflow DAG editor, automatic model trading, automatic parameter search, hosted infrastructure.

Builder may choose exact table names, small internal module boundaries, dataset serialization/compression, batching sizes and UI placement while preserving contracts. Prefer existing storage/history APIs over parallel frameworks. Keep existing configurations readable and migrate additively; no forced rewrite of old reports/results. Update conflicting historical-design docs to distinguish existing code, this approved target and deferred capabilities during implementation.

## Approval boundary

The user approved the scope decisions and approach A. This written design still awaits approval. After approval, produce a sequenced implementation plan, then implement with TDD. No production code or schema changes are part of authoring this document.
