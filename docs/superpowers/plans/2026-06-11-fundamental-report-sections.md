# Capital-Structure + Ownership-Structure Report Sections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add two new Analyze-report sections — `capital_structure` (资本结构) and `ownership_structure` (股权结构) — each grounding real numbers from verified data so the LLM narrates around facts, not hallucinations.

**Architecture:** Mirror the existing LLM-section pattern. READ these as the canonical templates before writing: `src/research/sections/financial_statements.py` (a Section with a deterministic grounded data block + an LLM narrative via the section runner), `src/research/sections/institutional_flow.py` (a recently-added section with a Python-built grounded block + a fetch module + SECTION_ORDER/heading-map registration), and `src/research/sections/base.py` (the `Section`/`SectionContext`/`load_prompt` API). Match their style exactly.

**Tech Stack:** Python (anaconda interpreter), pytest, the existing `src/research/` pipeline + `src.tools.api.search_line_items` + yfinance.

**Global constraints (every task):**
- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest <path> -q` — OFFLINE (synthetic data blocks; mock fetches; never hit network in tests).
- Commit per task; conventional message; **NO Co-Authored-By**; never `--no-verify`; explicit `git add <paths>` (never `-A`); never stage `.claude/settings.local.json`. `black` on touched `.py`. Branch `main`.
- **NEVER-RAISE**: a section/fetch with missing data renders a "data unavailable" note; the ticker is still reported. Every fetch wraps network in try/except → `[]`/`None`.
- **GROUNDED**: every number in the section's data block comes from real fetched data (not the LLM). The block is prepended so the existing anti-hallucination directive governs it.

Verified data (2026-06-11): `search_line_items(ticker, [...], end_date, period="annual")` populates `total_debt, shareholders_equity, total_liabilities, cash_and_equivalents, interest_expense, total_assets, outstanding_shares`. yfinance `Ticker(t).info` has `heldPercentInsiders, heldPercentInstitutions, sharesOutstanding`; `.major_holders` / `.institutional_holders` give the breakdown.

---

## Task 1: ownership data fetch

**Files:** Create `src/research/ownership_fetch.py` + `src/research/test_ownership_fetch.py`.

- [ ] **Step 1: failing test** — mock yfinance; assert `fetch_ownership("AAPL")` returns a dict with `insider_pct`, `institution_pct`, `institution_count`, `top_holders` (list of {name, pct}), `shares_outstanding`; and that a yfinance exception → a dict of `None`s (never raises).
- [ ] **Step 2: run → fail.**
- [ ] **Step 3: implement** `fetch_ownership(ticker) -> dict` reading `yf.Ticker(ticker).info` (`heldPercentInsiders`, `heldPercentInstitutions`, `sharesOutstanding`) + `.major_holders` (`institutionsCount`) + `.institutional_holders` (top rows → name+pctHeld). Wrap everything in try/except → all-`None` dict. Module-level `import yfinance as yf` inside the function (lazy) so import stays offline.
- [ ] **Step 4: run → pass. Step 5: commit** `feat(research): ownership data fetch (yfinance, best-effort)`.

## Task 2: capital_structure section

**Files:** Create `src/research/sections/capital_structure.py` + `src/research/prompts/modules/capital_structure.md` + `src/research/test_capital_structure.py`.

- [ ] **Step 1: failing test** — a synthetic `shared`/`ctx` whose line items give known numbers; assert the section's grounded block contains the computed ratios (debt/equity, net debt, leverage, interest coverage) with the right values, and that missing line items → a "data unavailable" note without raising.
- [ ] **Step 2: run → fail.**
- [ ] **Step 3: implement** — mirror `financial_statements.py`. A `_capital_block(ctx)` builds the grounded markdown from the 60d-lagged latest line item (reuse the lag helper pattern; the section gets the ticker's line items from `ctx.shared`): `debt/equity = total_debt/shareholders_equity`, `net_debt = total_debt − cash_and_equivalents`, `leverage = total_liabilities/total_assets`, `interest_coverage = operating_income/interest_expense` (operating_income from line items if present, else omit), `cash`, `shares_outstanding` (+ YoY dilution if a prior year is available). Each ratio guarded (None/zero-denominator → "n/a"). The `CapitalStructureSection(Section)` runs the LLM via the section runner with the block prepended; `name="capital_structure"`; prompt at `modules/capital_structure.md` (write a focused 1-paragraph system prompt: "you are a credit/balance-sheet analyst; narrate leverage, debt serviceability, liquidity, and capital allocation using ONLY the provided numbers").
- [ ] **Step 4: run → pass. Step 5: commit** `feat(research): capital-structure analysis section`.

## Task 3: ownership_structure section

**Files:** Create `src/research/sections/ownership_structure.py` + `src/research/prompts/modules/ownership_structure.md` + `src/research/test_ownership_structure.py`.

- [ ] **Step 1: failing test** — inject a stub `fetch_ownership` (monkeypatch) returning known values + a stub insider list; assert the grounded block shows insider %, institution %, top holders, and the insider-transaction net; missing ownership → "data unavailable", no raise.
- [ ] **Step 2: run → fail.**
- [ ] **Step 3: implement** — an `_ownership_block(ctx)` calling `fetch_ownership(ctx.request.ticker)` (Task 1) + reading the existing insider enrich off `ctx.shared` (the insider-transactions list already fetched) to show recent insider net buy/sell. `OwnershipStructureSection(Section)`, `name="ownership_structure"`, prompt `modules/ownership_structure.md` ("you are an ownership/insider analyst; narrate who owns it, institutional conviction, insider signal, and dilution using ONLY the provided numbers").
- [ ] **Step 4: run → pass. Step 5: commit** `feat(research): ownership-structure analysis section`.

## Task 4: register both sections + headings + regression

**Files:** Modify `src/research/models.py` (SECTION_ORDER), `src/research/html_render.py` (_HEADING_MAP + _HEADING_ZH_MAP), the section registry/factory wherever sections are instantiated (grep `SECTION_ORDER` consumers + where `financial_statements`/`institutional_flow` sections are registered — match that), and the section-count test.

- [ ] **Step 1: failing test** — update the section-count test to expect the new total; assert `capital_structure` + `ownership_structure` are in `SECTION_ORDER` and have en + zh headings.
- [ ] **Step 2: run → fail.**
- [ ] **Step 3: implement** — add `"capital_structure"` (after `financial_statements`) and `"ownership_structure"` (after it) to `SECTION_ORDER`; add `_HEADING_MAP["capital_structure"]="Capital Structure"`, `_HEADING_MAP["ownership_structure"]="Ownership Structure"`; `_HEADING_ZH_MAP[...]="资本结构" / "股权结构"`; register both Section classes wherever the orchestrator builds the section list (mirror how `institutional_flow` was wired — see its commit pattern). Add both to `_PARALLEL_SECTIONS` if that set exists.
- [ ] **Step 4: run → pass.**
- [ ] **Step 5: full research regression**: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest tests/research/ src/research/ -q` → green. **Step 6: commit** `feat(research): register capital-structure + ownership-structure sections (SECTION_ORDER + zh/en headings)`.

## Final
- [ ] Full `tests/research/` + `src/research/` suite green; the new sections never raise on missing data (assert in their tests). Append a per-task line to `progress.md`. Leave a one-line handoff noting (II) scanner signals + (III) scanner self-evolve are specced (docs/superpowers/specs/2026-06-11-fundamental-depth-and-scanner-design.md) for next session.

## Self-Review
- Coverage: spec's (I) → Tasks 1-4. Ownership report-only (no scanner) honored. Never-raise + grounded in every task. zh/en headings. Registration mirrors institutional_flow.
- No placeholders: each task gives the data source, the formulas, the file paths, the registration points. Boilerplate explicitly delegated to "mirror financial_statements.py / institutional_flow.py" (read-the-template, a legitimate reuse instruction).
