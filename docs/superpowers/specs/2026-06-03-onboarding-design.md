# New-User Onboarding — Design

**Date:** 2026-06-03
**Status:** Approved (ready for implementation plan)
**Scope:** Frontend only (`app/frontend/`). No backend or DB changes — reuses existing endpoints.

---

## Problem

A brand-new user who registers + logs in lands on a **blank main area** (the tab
store starts with zero open tabs) next to a sidebar of bare icons. Nothing tells
them:

1. That this is a **bring-your-own-key** app — until they add their own LLM key
   in Settings → API Keys, **every** analysis/scan fails with a cryptic "no API
   key" error.
2. What each feature (Analyze / Scanner / Screener / Lab) actually does.
3. How to perform a first action — Analyze in particular is an unusual
   node-canvas (Input node → section nodes → Run) that newcomers won't guess.

The only existing onboarding artifact is `components/panels/screener/empty-state.tsx`
(a good pattern to mirror). There is no welcome screen, checklist, or guidance.

## Goals / success criteria

A new user, with zero prior knowledge, can:

1. Understand what the app is within seconds of logging in.
2. Be guided to **add their API key first** (the hard prerequisite) before
   hitting a confusing failure.
3. Run their first analysis in one click.
4. See progress through a short getting-started checklist.

**Done = a new user reaches a successful first analysis without external help.**

## Out of scope (v1)

- **Guided spotlight tour (B)** — a step-by-step coachmark walkthrough of the
  sidebar. Deferred to a fast-follow; not in v1.
- Any backend/DB change. All state comes from existing endpoints + localStorage.

---

## Design

Three components + i18n. All frontend.

### 1. Home screen (replaces the blank main area)

**When shown:** in the main content area whenever **no tabs are open**
(`tabs.length === 0`). Also reachable any time via a new **Home** entry in the
left sidebar.

**Contents (top → bottom):**

- **Welcome hero** — title "Quant Lab" + one-line positioning ("AI deep-dive
  research · market scanning · backtesting — with your own API key").
- **🚀 Getting-started checklist** — 4 steps, each auto-ticked from real status,
  each with an action button:
  1. **Add your API key** → opens Settings (API Keys section). Done when an
     LLM-provider key exists (same check as the gate, §2).
  2. **Run your first analysis** → button "Try NVDA" fires the existing
     `analyzeBus.requestAnalyze({ticker:'NVDA', market:'us'})` + opens the
     Analyze tab. Done when the user has ≥1 research report.
  3. **Save a watchlist** → opens the Watchlist tab. Done when ≥1 watchlist
     entry exists.
  4. **Set up a scheduled report** → opens Settings (Scheduled reports). Done
     when ≥1 report schedule exists.
  - The whole card is dismissable (a localStorage `onboarding-checklist-dismissed`
    flag); once all 4 are done it auto-collapses to a small "✓ All set" line.
- **Feature cards** — Analyze / Scanner / Screener / Lab, each a one-line "what
  it does" + click → `openTab(...)` for that feature (reuses `TabService` +
  `useTabsContext().openTab`).

**Status detection** (on Home mount, parallel GETs, each isolated):
- key: the new `useApiKeysStatus()` hook (see §2).
- analysis: `analyzeService.listReports(undefined, 1)` → length > 0.
- watchlist: the existing watchlist list endpoint → any entry.
- schedule: `reportSchedulesService.list()` → length > 0.
Each step renders "loading → done/todo" independently; a failed probe shows the
step as "todo" (never blocks the screen).

### 2. Hard API-key gate

The user chose a **hard** gate: run actions are **disabled** until a key exists.

- **`ApiKeysStatusProvider`** (new context, mounted in `Layout.tsx` above the tab
  switcher) fetches `GET /api-keys` once on mount and exposes
  `{ hasKeys: boolean, loading: boolean, refresh: () => Promise<void> }`.
  `hasKeys` = the user has ≥1 saved key from an **LLM provider** — the providers
  `get_model` accepts (e.g. DeepSeek / OpenAI / Anthropic / Gemini / Groq),
  kept as a frontend constant mirrored from the backend. A **data-only** key
  (EODHD / Finnhub / Alpha Vantage / FRED) does **not** satisfy the gate, because
  every analysis needs an LLM. A `useApiKeysStatus()` hook reads it.
- **Gate points** (Run-type actions that need an LLM key):
  - Analyze toolbar **Run** button.
  - Scanner **Run / Run-now** buttons.
  - When `!hasKeys`: the button is `disabled`, its tooltip becomes
    "Add an API key first", and an adjacent **"Add API key →"** affordance opens
    the Settings tab (which defaults to the API Keys section).
- **Unlock:** `ApiKeysSettings` calls `refresh()` after a successful save, so the
  gate lifts + checklist step ① ticks without a reload.

(The Schedule control and one-click bus runs are **not** gated at the button —
they already surface errors gracefully; gating the explicit Run buttons covers
the "I clicked Run and got a cryptic error" path the gate exists to fix.)

### 3. Analyze first-visit hint

The Analyze canvas seeds a default template (Input node + sections + Run), so it
is not literally empty — the confusion is "what do I do with this?".

- A **dismissable hint banner** at the top of the Analyze panel, shown on first
  visit only (localStorage `analyze-hint-dismissed`):
  "👋 This is the analysis canvas — type a ticker in the Input node, then click
  **Run** (top-right) to generate a deep report." with a ✕ to dismiss.
- No coachmark positioning / overlay library — just a banner, mirroring the
  existing empty-state styling.

### 4. i18n

All new strings added to `i18n/locales/en.json` + `zh.json` under an `onboarding`
namespace (hero, checklist steps + actions, gate tooltip, analyze hint). Mirrors
the existing bilingual pattern.

---

## Architecture / files

**New files**
- `app/frontend/src/components/home/home-screen.tsx` — the Home view.
- `app/frontend/src/components/home/getting-started-checklist.tsx` — the checklist
  (status probes + step rows). (May live inside home-screen.tsx if small.)
- `app/frontend/src/contexts/api-keys-status-context.tsx` — `ApiKeysStatusProvider`
  + `useApiKeysStatus()`.

**Modified files**
- `app/frontend/src/components/Layout.tsx` — mount `ApiKeysStatusProvider`; render
  `<HomeScreen>` in the main area when `tabs.length === 0`.
- `app/frontend/src/components/panels/left/left-sidebar.tsx` — add a **Home** entry.
- `app/frontend/src/components/panels/analyze/analyze-toolbar.tsx` — gate the Run
  button on `useApiKeysStatus().hasKeys`.
- `app/frontend/src/components/panels/scanner/scanner-panel.tsx` — gate Run/Run-now.
- `app/frontend/src/components/settings/api-keys.tsx` — call `refresh()` after save.
- `app/frontend/src/components/panels/analyze/analyze-panel.tsx` — first-visit hint
  banner.
- `app/frontend/src/i18n/locales/en.json` + `zh.json` — `onboarding` namespace.

**Reused, unchanged:** `analyzeBus.requestAnalyze` (Try-NVDA), `useTabsContext().openTab`
+ `TabService` (feature cards), `analyzeService.listReports` /
`reportSchedulesService.list` / watchlist + api-keys services (status probes),
`screener/empty-state.tsx` styling.

## Data flow

```
App load → ApiKeysStatusProvider GET /api-keys → hasKeys
                                   │
              ┌────────────────────┼─────────────────────┐
        Analyze Run            Scanner Run            Home checklist ①
        disabled if !hasKeys   disabled if !hasKeys   done if hasKeys
              │
   Settings → save key → refresh() → hasKeys=true → all unlock + ① ticks

Home mount → parallel probes (reports / watchlist / schedules) → ticks ②③④
Home "Try NVDA" → analyzeBus.requestAnalyze → existing run path → report → ② ticks on next visit
```

## Error handling

- Every status probe is wrapped so a failed/timed-out GET leaves that step as
  "todo" and never blanks the Home or the gate (fail-safe: a probe failure must
  not lock the user out — but the **Run-button gate** is driven only by the
  authoritative `hasKeys`, which on fetch failure defaults to `false`
  conservatively, with the "Add API key →" path always available).
- The hard gate never traps the user: the disabled Run always pairs with a
  visible route to add the key.

## Testing

- `node node_modules/typescript/bin/tsc --noEmit` from `app/frontend/` — zero new
  errors.
- Manual smoke (the success criterion): fresh account → Home shows → Run is
  disabled + points to keys → add key → Run unlocks + ① ticks → "Try NVDA" →
  report appears → ② ticks.
- Optional: a small unit test for `useApiKeysStatus` (hasKeys true/false from a
  mocked list) if a frontend test harness is convenient; otherwise tsc + manual.
```
