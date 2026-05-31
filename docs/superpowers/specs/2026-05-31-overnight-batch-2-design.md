# Overnight batch #2 — pagination + batch reports + stock-score

Unattended overnight run (user asleep). Build on branch `feature/multi-tenant-accounts`.
Autonomy rule: pick the sensible default on any ambiguity, record it in `findings.md`,
never block. Per-task commit (NO Co-Authored-By; never --no-verify). Frontend tasks must
pass `node node_modules/typescript/bin/tsc --noEmit` (zero errors); backend tasks ship
mock-based tests and leave `pytest tests/ -q` green. Use opus for every subagent (CLAUDE.md).

## Decisions (from the user)
- **Stock score = the conviction score.** The "综合评分 53/100" in reports IS the conviction /
  setup-quality score (`src/research/sections/conviction.py`, deterministic 6-category weighted),
  NOT the executive-summary `confidence_score`. The user wants the Analyze page to show that
  conviction score as "股票分数 / Stock Score" instead of confidence.
- **Batch reports: pick settings once via a dialog**, then run all selected (user's Q2 answer).
- Pagination: **20 per page** everywhere.

## Task 1 — Watchlist tab pagination (20/page)
`app/frontend/src/components/panels/watchlist/watchlist-tab.tsx`. The tab fetches all of a
list's live quotes at once. Paginate the **displayed** rows client-side, 20/page, with the same
Prev/Next + "第 X / Y 页 · 共 N 支" footer style as the Screener (`screener-tab.tsx` d0c516c).
Reset to page 0 when the selected watchlist changes or on refresh. tsc clean.

## Task 2 — Scanner results pagination (20/page)
Find where scan-run results render (the ranked tickers table — likely `scanner` panel /
`watchlist-table.tsx`). Paginate 20/page (client-side over the displayed results), same footer
pattern. Reset to page 0 when the viewed run changes. tsc clean.

## Task 3 — Batch run reports (multi-select → batch analyze)
- Screener already has row multi-select + "Add to watchlist". Add a **"批量跑报告 / Batch report"**
  button next to it (visible when ≥1 selected). The **Watchlist tab** gets row multi-select +
  the same button (user wants it on watchlists too).
- Clicking it opens a **settings dialog** (pick ONCE): objective (default general_research) +
  market (default US) — reuse the AnalyzeRunRequest fields the single-run uses. A confirm button
  "跑 N 个报告".
- On confirm: fire one analyze run per selected ticker via the existing analyze run endpoint
  (`analyze-service.ts` → `/research/analyze` / AnalyzeRunRequest; each is a background job that
  lands in Recent Reports when done). Run them with a small client-side concurrency limit (e.g.
  3 at a time) to avoid hammering the backend; show a toast "已开始 N 个分析,完成后进近期报告".
  **Cap the batch at 20** selected tickers (if more, disable/limit + a note) — guards against an
  accidental 100-stock LLM spend.
- No backend change expected (reuse the per-ticker analyze run). If the run endpoint can't be
  called headless per-ticker, add a thin `/research/analyze/batch` that loops — but prefer reusing
  the existing single endpoint N times.

## Task 4 — Stock score replaces confidence on the Analyze page
- **Backend** (`app/backend/routes/research.py` `_report_to_detail` ~L244 + `VerdictPayload` in
  `research_schemas.py` L188): add `stock_score: int | None` to `VerdictPayload`, populated from the
  report's **conviction** section total_score (the 0-100 setup-quality score). Source it from the
  conviction section's structured output if it carries the total; else recompute from its category
  scores (the runner already computes `sum(weight*score/100)` in conviction.py) or parse the
  rendered "总分/Score: X/100". Keep `confidence_score` on the payload (don't break it) but the UI
  switches to `stock_score`. If no conviction score is available, `stock_score = None`.
- **Frontend** (`verdict-card.tsx` + `types/analyze.ts` VerdictPayload + the report banner in
  `src/research/html_render.py` `_verdict_banner_html`): show `stock_score` labeled
  **"股票分数 / Stock Score"** instead of confidence. When `stock_score` is null, fall back to showing
  the confidence (so older reports still render) OR "—". Relabel + keep the same visual.
- A backend test: a report whose conviction section scored e.g. 53 → `_report_to_detail` verdict
  has `stock_score == 53`. tsc clean for the frontend.

## Verification + wrap-up
After all 4: `pytest tests/ -q` green; `tsc --noEmit` clean; restart the backend (Task 4 changed
it); append a wrap-up to `progress.md`; report wave-by-wave in the morning. Do NOT merge to main.
