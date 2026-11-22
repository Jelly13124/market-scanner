# Historical prices and the research loop implementation plan

**Goal.** A user can trace a backtest from the confirmed trading rules and exact price inputs back to a Scanner signal and the original Screener selection.

**Architecture.** PostgreSQL owns user actions and their relationships. MongoDB stores shared daily history, immutable input revisions and optional research evidence. Existing online analysis works when MongoDB is absent. The daily maintenance command requires a writable MongoDB. The first slice runs locally and independently of the web server.

[Approved spec](../specs/2026-11-17-history-research-loop-design.md) · [Two database ERDs](../../design/research-loop-erd.md)

For each checkbox, run the failing behavior test first, implement through the normal entry point, then rerun that test and the neighboring suite. Use local fixtures for provider/model responses in automated tests. Use a dedicated database for migration and live acceptance checks.

## 1. Seed the local daily-price history

- [x] Add tests in `tests/test_daily_history.py` for five calendar years, the close on a shortened trading day, a deduplicated benchmark, interrupted coverage and a repeat with no network calls.
- [x] Implement `python -m scripts.backfill_prices --universe nasdaq100_sp500`. Reuse the Scanner's universe loader, Yahoo adapter and shared revision writer in `src/storage/daily_prices.py`. Report coverage per instrument and a nonzero exit for unresolved windows.
- [x] Install the existing validators and indexes through `scripts.mongo_history`. Smoke-test real Yahoo and MongoDB with AAPL and SPY in a separate database before running the full universe.
- [x] Check the final unique instrument/session counts, bounds, SPY coverage and gaps against the exchange calendar. Repeat the command and compare revision counts. Document partial coverage and the operator commands in the README.

### Local acceptance on November 21, 2026

The local PostgreSQL installation had one enabled Scanner using `nasdaq100_sp500` and zero saved Watchlists. Its bundled snapshot resolved to 516 distinct symbols. Adding SPY produced 517 instruments. The local MongoDB instance was version 9.0.4, with 13 collections installed in `market_scanner`.

Independent queries checked the stored session dates against the 1,255 XNYS sessions from November 22, 2021 through November 20, 2026. MongoDB contained 634,625 distinct instrument/session pairs and 634,625 bar documents, all with adjusted closes. 501 instruments had full coverage, 13 had shorter series and three had zero bars. The first gap retry recovered one additional SNDK session. A third pass left all per-symbol bar counts unchanged. SPY, AAPL and BRK.B each returned 1,255 bars through the application's hybrid client with the online price provider disabled.

| Incomplete symbol | Stored sessions | First stored | Last stored |
| --- | ---: | --- | --- |
| ARM | 801 | 2023-09-14 | 2026-11-20 |
| AVB | 1 | 2026-08-14 | 2026-08-14 |
| BK | 0 | — | — |
| CEG | 1,216 | 2022-01-19 | 2026-11-20 |
| EA | 1 | 2026-08-04 | 2026-08-04 |
| EQR | 1 | 2026-08-17 | 2026-08-17 |
| GEHC | 987 | 2022-12-15 | 2026-11-20 |
| GEV | 667 | 2024-03-27 | 2026-11-20 |
| KVUE | 1 | 2026-10-30 | 2026-10-30 |
| PSKY | 0 | — | — |
| Q | 270 | 2025-10-27 | 2026-11-20 |
| SATS | 24 | 2026-10-20 | 2026-11-20 |
| SNDK | 446 | 2025-02-13 | 2026-11-20 |
| SOLV | 668 | 2024-03-26 | 2026-11-20 |
| VLTO | 787 | 2023-10-04 | 2026-11-20 |
| WBD | 0 | — | — |

Each attempted window retains its exact missing ranges in `data_sync_jobs.coverage.missing_ranges`. The dates above describe observed coverage. They do not establish listing dates or historical index membership.

## 2. Freeze the selected universe and Scanner evidence

- [x] In the Screener/Scanner repository tests, save a filtered selection, edit the source Watchlist and verify the old scan still resolves to its original symbols and filters. Attempt to reference a second user's snapshot and assert rejection.
- [x] Add `universe_snapshots` and additive nullable links for legacy rows in `app/backend/database/models.py` and an Alembic migration. Capture owner, selection time, filter JSON, Screener date and exact resolved symbols from the server.
- [x] Update `app/backend/routes/screener.py` and `app/backend/services/scanner_service.py`. Freeze the executed universe per run and retain each ticker's outcome, detector version, signal session and values. Exercise PostgreSQL with MongoDB disabled.
- [x] Pass the selected result ID from the Scanner panel into Analyze. In research route tests submit an owned result, an inaccessible result and a standalone ticker. Attach validated original trigger evidence separately from newly fetched observations.

The local acceptance run used an isolated PostgreSQL database, disabled MongoDB and fixture responses for market feeds and the model. The HTTP scan froze two tickers, selected one at 2.5× relative volume, and retained the source selection after Watchlist edits and config deletion. The resulting Analyze prompt, stored Markdown and HTML carried the original signal, independently dated analysis inputs and the owned SQL result link. A second user could access neither the snapshot nor a report run based on that result.

The Chrome regression runs with `npm run test:handoff` in `app/frontend`. It opens a queued scan, restores the result, inspects the frozen universe and signal components, and verifies that Analyze receives the original result ID and the selected debate settings. Scanner route tests also cover reconnecting after the worker has already finished.

## 3. Share the three daily rules

- [x] Add paired Scanner/Lab fixtures for relative volume, closing breakout and SPY-relative strength. Include equality at breakout, unequal benchmark dates, insufficient warm-up and an unavailable operand in AND/OR.
- [x] Extract pure versioned rule evaluators from `v2/scanner/detectors/`. Call them from Scanner and `src/lab/engine/signal_eval.py`. Both callers must return the same status, direction, evidence values and effective session for the same input.
- [x] Keep existing strategies and detector configurations on their original semantics. Test an old serialized strategy as well as a new rule group.

The Scanner and Backtest editors save the same versioned conditions. Backtest can copy a saved Scanner group into its own entry specification. A local comparison read 1,255 AAPL and SPY sessions from MongoDB (November 22, 2021 through November 20, 2026). The two paths agreed on all 3,765 per-rule observations, including 20 warm-up sessions per rule. The counts of raw triggers were 32 for relative volume, 333 for closing breakouts and 455 for relative strength, before applying a directional filter.

An HTTP acceptance run persisted a Scanner group in isolated PostgreSQL, copied its entry conditions to a Backtest strategy and ran the strategy over AAPL in 2024. It read AAPL and SPY through the real local history adapter with Yahoo access disabled, returned 15 in-sample and 7 out-of-sample closed trades, and retained the versioned rules when the saved result was reopened.

## 4. Confirm strategy revisions and execute them

- [x] Test an Analyze-originated draft through `app/backend/routes/lab.py`. Require explicit confirmation with entry, exit, cash, allocation, costs and dates. Reject an unsupported block or another owner's report.
- [x] Add immutable confirmed revisions in SQL for report-linked strategies, linked to strategy, source report, universe and originating scan where applicable. A later edit creates a new revision. Link each confirmed draft backtest to its executed revision.
- [ ] Implement the approved execution profile in `src/lab/engine/simulation.py`. Use small hand-calculated portfolios to check next-open fills, ranking, exit-before-entry, insufficient cash, fees, split/dividend handling and end-of-window positions. Verify IS and OOS start in cash.
- [x] Expose draft confirmation, costs, frozen universe members and report/Scanner provenance in Analyze and Backtest.
- [ ] Report per-ticker price exclusions in the execution results. A report's historical performance study remains distinct from the confirmed portfolio run.

## 5. Freeze and replay portfolio inputs

- [ ] In `tests/test_lab_backtest_runner.py`, change provider bars after a run. Strict replay must use zero network calls and reproduce trades and metrics. Fetch-and-rerun must allocate a new run ID.
- [ ] Extend `src/lab/backtest_runner.py` and the existing Mongo dataset repository with a portfolio manifest covering input order, bar revisions, actions, SPY, warm-up and supported engine/rule versions. Publish the verified payload before setting the SQL replayable state.
- [ ] Test unavailable Mongo, interrupted publication, missing revisions, hash mismatch and unsupported versions. Preserve ordinary online runs and show the reason when original-data replay is unavailable.

## 6. Maintain and verify the complete loop

- [ ] Extend `app/backend/services/scheduler_service.py` to resolve enabled Scanner universes plus Watchlists and SPY. Run a single maintenance pass at a time, catch up gaps after restart and refresh a bounded correction window. On a corporate action, check older overlapping bars for restatements and expand the refresh if the adjustment basis changed. Confirm that a changed bar appends one revision and old replay still reproduces.
- [ ] Exercise Screener → Scanner → Analyze → confirmation → Backtest in the browser against local PostgreSQL and MongoDB. Repeat standard execution with MongoDB disabled. Check owner isolation, source navigation and replay availability.
- [ ] Run the Python suite, frontend tests/build and migration upgrade against isolated databases. Publish verified installation and recovery steps alongside the local history commands.
