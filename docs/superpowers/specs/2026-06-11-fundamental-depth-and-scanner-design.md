# Fundamental Depth (report sections) + Scanner Self-Evolve — Design

**Date:** 2026-06-11
**Status:** approved direction (build (I) now overnight; (II)+(III) specced for next session)

## Goal

Deepen the fundamental side of the product on two fronts the user asked for:
1. **Analyze report depth** — add **capital-structure** and **ownership-structure** analysis sections (valuation already exists).
2. **Scanner** — add fundamental screening dimensions, then apply the self-evolve methodology to auto-tune the scanner config.

## Scope split (honest, by risk)

- **(I) Two report sections — BUILD NOW (overnight, subagent-driven).** Well-understood pattern (mirror existing sections), data verified live, no backtest ⇒ no-lookahead-trivial.
- **(II) Scanner fundamental signals — SPEC ONLY (execute next).** The scanner is **detector-only** (event-based `EventTrigger`, no `signals/` dir); a continuous "quality" doesn't fit cleanly, and the architecture + the 4 scanner invariants need careful handling. **No-lookahead constraint:** capital structure + valuation are backtestable (line items carry `report_period`, lagged 60d); **ownership is a current-only snapshot (no history) ⇒ report-only, NOT a backtestable scanner signal** (same class as gamma/flow).
- **(III) Scanner self-evolve plugin — SPEC ONLY (execute after II).** A B+C-sized sub-project: the scanner's fitness is NOT directional alpha but an **A/B vs a random-pick baseline** (per the project's own design intent), and its config protocol (detector thresholds/weights) differs from the factor strategy. Depends on (II) existing.

## Data availability (verified live, 2026-06-11)

- **Capital structure** via `search_line_items` (annual, `report_period` → 60d-lagged): `total_debt`, `shareholders_equity`, `total_liabilities`, `cash_and_equivalents`, `interest_expense`, `total_assets`, `outstanding_shares` all populate for AAPL. (`long_term_debt`/`short_term_debt`/`total_equity` came back None → use `total_debt` + `shareholders_equity`.)
- **Ownership** via yfinance: `heldPercentInsiders` (1.63%), `heldPercentInstitutions` (65.8%), `institutionsCount` (7676), `institutional_holders` (top-10 rows), `sharesOutstanding`. CURRENT snapshot only (no history). Plus the existing insider-transactions enrich (historical).

---

## (I) Report sections — the build

Each mirrors an existing `src/research/sections/*.py` (e.g. `financial_statements.py`): a `Section` subclass with `name`, a `_Narrative` Pydantic output model, an LLM prompt at `src/research/prompts/modules/<name>.md`, deterministic GROUNDED data blocks built in Python (so the numbers are real, governed by the existing anti-hallucination directive), then registered in `SECTION_ORDER` (`src/research/models.py`) + `_HEADING_MAP` + `_HEADING_ZH_MAP` (`src/research/html_render.py`).

### Section A: `capital_structure` — "资本结构"
Deterministic grounded block (from 60d-lagged line items): debt/equity (`total_debt / shareholders_equity`), net debt (`total_debt − cash_and_equivalents`), leverage (`total_liabilities / total_assets`), interest coverage (operating income / `interest_expense`), cash position, share-count trend (dilution vs buyback from `outstanding_shares` YoY). LLM narrates the balance-sheet health + capital allocation around those real numbers. Placed after `financial_statements` in `SECTION_ORDER`.

### Section B: `ownership_structure` — "股权结构"
Deterministic grounded block: insider % held, institutional % held, institution count, top-10 institutional holders (name + %), shares outstanding, recent insider-transaction net (from the existing insider enrich). LLM narrates who owns it + insider conviction. New ownership data fetch (`src/research/ownership_fetch.py`, best-effort, never-raises) reusing the yfinance `.info` / `.major_holders` / `.institutional_holders` fields verified above. Placed after `capital_structure`.

Both sections: never raise (missing data → a "data unavailable" note, ticker still reported); zh/en headings; a section-count test update; an offline test with a synthetic data block asserting the grounded numbers render.

---

## (II) Scanner fundamental signals — SPEC (execute next)

Add backtestable fundamental dimensions to the scanner. PRE-WORK (next session): map the detector/scoring architecture (`v2/scanner/detectors/base.py`, `scoring.py`, the 4 invariants) to decide whether fundamental quality is a new detector (event: "balance-sheet-quality crossed a threshold") or a scoring input. Candidates (backtestable, 60d-lagged, no-lookahead): **capital-structure quality** (low leverage + interest coverage + net cash), **valuation** (cheap on E/P or EV/EBITDA — check if already present). **Ownership EXCLUDED** (no history). Must honor: std floor on any z-score, signals never raise, `None` vs `EventTrigger(triggered=False)`, per-worker `DataClient`. Gate every change through the scanner-invariant-reviewer.

## (III) Scanner self-evolve plugin — SPEC (execute after II)

Apply the `v2/self_evolve/` engine to the scanner config. Key DESIGN decisions to settle with the user first: (a) **fitness** = A/B selection-quality vs a random-pick baseline (NOT directional alpha — per `project_scanner_design_intent`), over train/val with the held-out test untouched; (b) the **adjustable config** = detector thresholds + scoring weights (the scanner's `skill_config`-equivalent), bounded; (c) reuse the engine's version store + keep/rollback + proposer seam; (d) the backtest = `run_scan` over historical as-of dates with the no-lookahead `CachedAsOfClient`. Depends on (II) giving the scanner fundamental dimensions worth tuning.

## Out of scope / risks

- Ownership as a backtestable scanner signal (no history) — report-only.
- (II)/(III) built blind tonight — explicitly deferred to avoid scanner-invariant violations.
- Deepening the existing valuation section — optional fast-follow.
